"""
机器人安全监测 FastAPI 服务
========================================
实时模式：通过 ImageClient 从 image_server 获取 RGBD 图像
后台运行生产者-消费者线程，用户通过 GET /get_status 获取当前安全状态。
当 is_safe 或 unsafe_side 发生改变时，自动向 controller server 发送通知。

用法：
  uvicorn safety_service:app --host 0.0.0.0 --port 8000
  # 可选环境变量覆盖参数（见下方配置）

API：
  GET /get_status  →  {"is_safe": bool, "score": float, "frame_idx": int, "timestamp": float, "datetime": str, "latency_ms": float}
"""

import os
import sys
import time
import queue
import threading
import datetime

import numpy as np
import cv2
import requests

from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

# ══════════════════════════════════════════════
#  可调参数（可通过环境变量覆盖）
# ══════════════════════════════════════════════
OBSTACLE_DIST_M  = float(os.getenv("OBSTACLE_DIST_M",  "1.0"))
BLOCK_SIZE       = int(os.getenv("BLOCK_SIZE",         "8"))
BLOCK_THRESHOLD  = float(os.getenv("BLOCK_THRESHOLD",  "0.9"))
THRESHOLD        = float(os.getenv("THRESHOLD",        "0.55"))
BOUND_THRESHOLD  = float(os.getenv("BOUND_THRESHOLD",  "0.4"))
LEFT_BOUND       = float(os.getenv("LEFT_BOUND",       "0.2"))
RIGHT_BOUND      = float(os.getenv("RIGHT_BOUND",      "0.8"))
DEPTH_8BIT_MAX_M = float(os.getenv("DEPTH_8BIT_MAX_M", "5.0"))
DEPTH_16BIT_SCALE= float(os.getenv("DEPTH_16BIT_SCALE","0.001"))
HOLE_FILL_MODE   = int(os.getenv("HOLE_FILL_MODE",     "0"))

# ImageClient 连接参数
IMAGE_SERVER_HOST = os.getenv("IMAGE_SERVER_HOST", "127.0.0.1")
REQUEST_PORT      = int(os.getenv("REQUEST_PORT",  "60002"))
RGBD_PORT         = int(os.getenv("RGBD_PORT",     "60003"))
CAMERA            = os.getenv("CAMERA",            "head_camera")
INTERVAL          = float(os.getenv("INTERVAL",    "0.3"))

# Controller server 参数
CONTROLLER_SERVER_URL = os.getenv(
    "CONTROLLER_SERVER_URL", "http://127.0.0.1:18790"
)
NOTIFY_TIMEOUT = float(os.getenv("NOTIFY_TIMEOUT", "2.0"))


# ══════════════════════════════════════════════
#  Hole Filling
# ══════════════════════════════════════════════
def hole_filling_filter(depth_raw: np.ndarray, mode: int = None) -> np.ndarray:
    if mode is None:
        mode = HOLE_FILL_MODE

    filled = depth_raw.copy()
    mask   = (filled == 0)

    if mode == -1 or not np.any(mask):
        return filled

    if mode == 0:
        for i in range(filled.shape[0]):
            row  = filled[i]
            mask = (row == 0)
            if not np.any(mask):
                continue
            idx = np.where(~mask, np.arange(len(row)), 0)
            np.maximum.accumulate(idx, out=idx)
            row[mask] = row[idx[mask]]
            filled[i] = row

    elif mode == 1:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        scale  = 1000.0
        tmp    = np.clip(filled * scale, 0, 65535).astype(np.uint16)
        dilated = cv2.dilate(tmp, kernel).astype(np.float32) / scale
        filled  = np.where(mask, dilated, filled)

    elif mode == 2:
        kernel5  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        kernel11 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
        scale    = 1000.0
        tmp      = np.clip(filled * scale, 0, 65535).astype(np.uint16)
        BIG      = np.iinfo(np.uint16).max
        BIG_F    = BIG / scale
        no_zero  = np.where(tmp == 0, BIG, tmp)
        e5  = cv2.erode(no_zero.astype(np.uint16), kernel5).astype(np.float32)  / scale
        e11 = cv2.erode(no_zero.astype(np.uint16), kernel11).astype(np.float32) / scale
        e5  = np.where(e5  >= BIG_F, 0.0, e5)
        e11 = np.where(e11 >= BIG_F, 0.0, e11)
        filled = np.where(mask & (e5 > 0),  e5,  filled)
        filled = np.where((filled == 0) & (e11 > 0), e11, filled)

    return filled


# ══════════════════════════════════════════════
#  深度图解码
# ══════════════════════════════════════════════
def decode_depth_to_meters(depth_uint16: np.ndarray, depth_scale: float) -> np.ndarray:
    return depth_uint16.astype(np.float32) * depth_scale


# ══════════════════════════════════════════════
#  ROI & 安全得分
# ══════════════════════════════════════════════
def extract_roi(depth_m: np.ndarray) -> tuple:
    h, w = depth_m.shape
    r0, r1 = 0, h
    c0, c1 = int(w * LEFT_BOUND), int(w * RIGHT_BOUND)
    region   = depth_m[r0:r1, c0:c1]
    roi_info = dict(r0=r0, r1=r1, c0=c0, c1=c1, h=h, w=w)
    return region, roi_info


def compute_safety_score(region: np.ndarray) -> tuple:
    bs = BLOCK_SIZE
    h, w = region.shape
    h_crop = (h // bs) * bs
    w_crop = (w // bs) * bs
    region = region[:h_crop, :w_crop]

    pixel_binary = np.where(region > OBSTACLE_DIST_M, 1.0, 0.0)

    n_rows = h_crop // bs
    n_cols = w_crop // bs
    blocks = (pixel_binary
              .reshape(n_rows, bs, n_cols, bs)
              .transpose(0, 2, 1, 3))
    block_means   = blocks.mean(axis=(2, 3))
    block_binary  = np.where(block_means > BLOCK_THRESHOLD, 1.0, 0.0)
    overall_score = float(block_binary.mean())

    return overall_score, block_binary, block_means


# ══════════════════════════════════════════════
#  单帧处理
# ══════════════════════════════════════════════
def process_depth(depth_raw: np.ndarray) -> dict:
    depth_m          = hole_filling_filter(depth_raw)
    region, roi_info = extract_roi(depth_m)

    left_bound_region  = depth_m[:, 0:roi_info["c0"]]
    right_bound_region = depth_m[:, roi_info["c1"]:]

    left_score,  _, _ = compute_safety_score(left_bound_region)
    right_score, _, _ = compute_safety_score(right_bound_region)
    score,       _, _ = compute_safety_score(region)

    is_safe = (
        score > THRESHOLD
        and left_score  > BOUND_THRESHOLD
        and right_score > BOUND_THRESHOLD
    )
    return {
        "score":       score,
        "left_score":  left_score,
        "right_score": right_score,
        "is_safe":     is_safe,
        "result":      "safe" if is_safe else "unsafe",
    }


# ══════════════════════════════════════════════
#  最新状态（线程安全）
# ══════════════════════════════════════════════
_status_lock = threading.Lock()
_latest_status: dict = {
    "is_safe":     None,
    "unsafe_side": None,
    "score":       None,
    "left_score":  None,
    "right_score": None,
    "frame_idx":   -1,
    "timestamp":   None,
    "datetime":    None,
    "latency_ms":  None,
    "error":       "No frame received yet",
}

# 上一次通知时的关键状态，用于变化检测（仅在消费者线程中读写，无需额外锁）
_SENTINEL = object()           # 哨兵值，表示"从未设置过"
_prev_is_safe:    object = _SENTINEL
_prev_unsafe_side: object = _SENTINEL


def _set_status(update: dict):
    with _status_lock:
        _latest_status.update(update)


def get_status_snapshot() -> dict:
    with _status_lock:
        return dict(_latest_status)


# ══════════════════════════════════════════════
#  通知 Controller Server
# ══════════════════════════════════════════════
def _notify_server(is_safe: bool, unsafe_side) -> None:
    """
    向 controller server 发送 GET 请求，通知当前安全状态。

    目标接口：GET <CONTROLLER_SERVER_URL>/api/controller/external
    期望响应：{"ok": true, "safe": true, "unsafe_side": "left"/"right"/null}

    本函数在独立线程中被调用（fire-and-forget），异常只打印不上抛。
    """
    url = f"{CONTROLLER_SERVER_URL.rstrip('/')}/api/controller/external"
    params = {
        "safe": "true" if is_safe else "false",
        "unsafe_side": "" if unsafe_side is None else unsafe_side,
    }
    try:
        resp = requests.post(url, json=params, timeout=NOTIFY_TIMEOUT)
        resp.raise_for_status()
        print(
            f"[Notify] → {url}  safe={is_safe}  unsafe_side={unsafe_side}  "
            f"status={resp.status_code}  body={resp.text[:120]}"
        )
    except requests.RequestException as e:
        print(f"[Notify] ERROR notifying controller server: {e}")


def _notify_async(is_safe: bool, unsafe_side) -> None:
    """在独立守护线程中异步发送通知，不阻塞消费者。"""
    t = threading.Thread(
        target=_notify_server,
        args=(is_safe, unsafe_side),
        daemon=True,
    )
    t.start()


# ══════════════════════════════════════════════
#  生产者
# ══════════════════════════════════════════════
def _producer(client, interval: float, frame_queue: queue.Queue, stop_event: threading.Event):
    frame_idx = 0
    print(f"[Producer] started  camera={CAMERA}  interval={interval:.3f}s")

    while not stop_event.is_set():
        t_req = time.time()
        try:
            result = client.get_rgbd_frame(camera=CAMERA, timeout=int(interval * 2000))
        except Exception as e:
            print(f"[Producer] get_rgbd_frame error: {e}")
            stop_event.wait(0.1)
            continue

        if result is None:
            print(f"[Producer] frame {frame_idx} timeout, skipping")
            stop_event.wait(max(0.0, interval - (time.time() - t_req)))
            continue

        _, depth_uint16, metadata = result
        depth_scale = metadata.get("depth_scale", DEPTH_16BIT_SCALE)
        depth_raw   = decode_depth_to_meters(depth_uint16, depth_scale)

        item = (frame_idx, depth_raw, t_req)

        if frame_queue.full():
            try:
                frame_queue.get_nowait()
            except queue.Empty:
                pass
        frame_queue.put(item)
        frame_idx += 1

        stop_event.wait(max(0.0, interval - (time.time() - t_req)))

    print("[Producer] stopped")


# ══════════════════════════════════════════════
#  消费者
# ══════════════════════════════════════════════
def _consumer(frame_queue: queue.Queue, stop_event: threading.Event):
    global _prev_is_safe, _prev_unsafe_side

    print("[Consumer] started")

    while not stop_event.is_set() or not frame_queue.empty():
        try:
            item = frame_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        frame_idx, depth_raw, t_captured = item
        t_proc = time.time()

        try:
            result = process_depth(depth_raw)
        except Exception as e:
            print(f"[Consumer] frame {frame_idx} processing error: {e}")
            _set_status({"error": str(e), "frame_idx": frame_idx})
            continue

        t_now      = time.time()
        latency_ms = (t_now - t_captured) * 1000.0
        dt_str     = datetime.datetime.fromtimestamp(t_captured).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        is_safe = result["is_safe"]
        if is_safe == False:
            unsafe_side = "right" if result["left_score"] > result["right_score"] else "left"
        else:
            unsafe_side = None

        _set_status({
            "is_safe":     is_safe,
            "unsafe_side": unsafe_side,
            "score":       round(result["score"],       4),
            "left_score":  round(result["left_score"],  4),
            "right_score": round(result["right_score"], 4),
            "result":      result["result"],
            "frame_idx":   frame_idx,
            "timestamp":   round(t_captured, 3),
            "datetime":    dt_str,
            "latency_ms":  round(latency_ms, 1),
            "error":       None,
        })

        # ── 状态变化检测 & 通知 ──────────────────────────────────────
        state_changed = (
            _prev_is_safe is _SENTINEL           # 首帧，视为"变化"
            or is_safe    != _prev_is_safe
            or unsafe_side != _prev_unsafe_side
        )
        if state_changed:
            print(
                f"[StateChange] is_safe: {_prev_is_safe!r} → {is_safe!r}  "
                f"unsafe_side: {_prev_unsafe_side!r} → {unsafe_side!r}"
            )
            _notify_async(is_safe, unsafe_side)
            _prev_is_safe     = is_safe
            _prev_unsafe_side = unsafe_side
        # ─────────────────────────────────────────────────────────────

        tag = "✅ SAFE  " if is_safe else "⚠️  UNSAFE"
        print(
            f"[Frame {frame_idx:06d}]  {dt_str}  "
            f"M={result['score']:.3f}  L={result['left_score']:.3f}  R={result['right_score']:.3f}  "
            f"{tag} unsafe_side={unsafe_side}  latency={latency_ms:.1f}ms  proc={(t_now-t_proc)*1000:.1f}ms"
        )

    print("[Consumer] stopped")


# ══════════════════════════════════════════════
#  FastAPI 应用
# ══════════════════════════════════════════════
app = FastAPI(title="Robot Safety Monitor", version="1.0")

_stop_event      = threading.Event()
_frame_queue     = queue.Queue(maxsize=1)
_producer_thread: threading.Thread = None
_consumer_thread: threading.Thread = None


@app.on_event("startup")
def startup():
    global _producer_thread, _consumer_thread

    # 动态导入 ImageClient
    teleimager_src = os.path.expanduser("~/projects/teleimager/src")
    if teleimager_src not in sys.path:
        sys.path.insert(0, teleimager_src)

    try:
        from teleimager.image_client import ImageClient
    except ImportError as e:
        print(f"[ERROR] Cannot import ImageClient: {e}")
        raise RuntimeError("ImageClient not available") from e

    client = ImageClient(
        host=IMAGE_SERVER_HOST,
        request_port=REQUEST_PORT,
        rgbd_request_port=RGBD_PORT,
    )
    print(f"[INFO] Connected to image_server at {IMAGE_SERVER_HOST}  "
          f"req={REQUEST_PORT}  rgbd={RGBD_PORT}")

    _producer_thread = threading.Thread(
        target=_producer,
        args=(client, INTERVAL, _frame_queue, _stop_event),
        name="Producer", daemon=True,
    )
    _consumer_thread = threading.Thread(
        target=_consumer,
        args=(_frame_queue, _stop_event),
        name="Consumer", daemon=True,
    )

    _producer_thread.start()
    _consumer_thread.start()
    print("[INFO] Background threads started")


@app.on_event("shutdown")
def shutdown():
    print("[INFO] Shutting down background threads...")
    _stop_event.set()
    if _producer_thread:
        _producer_thread.join(timeout=5)
    if _consumer_thread:
        _consumer_thread.join(timeout=5)
    print("[INFO] Shutdown complete")


@app.get("/get_status")
def get_status():
    """
    返回最新一帧的安全检测结果。

    Response fields:
      - is_safe      (bool | null)   : 是否安全
      - unsafe_side  (str | null)    : 不安全侧（"left"/"right"/null）
      - score        (float | null)  : 中间区域安全得分 (0~1)
      - left_score   (float | null)  : 左侧区域安全得分
      - right_score  (float | null)  : 右侧区域安全得分
      - frame_idx    (int)           : 帧序号（-1 表示尚未收到帧）
      - timestamp    (float | null)  : 帧采集 Unix 时间戳
      - datetime     (str | null)    : 帧采集时间（人类可读）
      - latency_ms   (float | null)  : 端到端延迟（ms）
      - error        (str | null)    : 错误信息（无错误时为 null）
    """
    return JSONResponse(content=get_status_snapshot())


# ══════════════════════════════════════════════
#  直接运行入口
# ══════════════════════════════════════════════
if __name__ == "__main__":
    uvicorn.run("safety_service_notify:app", host="0.0.0.0", port=50020, reload=False)
