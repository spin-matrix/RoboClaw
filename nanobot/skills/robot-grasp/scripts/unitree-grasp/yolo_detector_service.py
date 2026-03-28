import time
import cv2
import numpy as np
import multiprocessing as mp
from multiprocessing import Process, Value, Array, shared_memory
from ultralytics import YOLO
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from teleimager.image_client import ImageClient
from tools.coordinate_transform import *


class YOLODetector:
    def __init__(self, model_path, visualize=False,
                 image_client_host='127.0.0.1',
                 image_client_request_port=60000,
                 image_client_rgbd_port=60003,
                 image_client_camera='head_camera',
                 service_host='0.0.0.0',
                 service_port=50022):
        self.model_path = model_path
        self.visualize = visualize

        self.image_client_host = image_client_host
        self.image_client_request_port = image_client_request_port
        self.image_client_rgbd_port = image_client_rgbd_port
        self.image_client_camera = image_client_camera

        self.service_host = service_host
        self.service_port = service_port

        self.color_shm = None
        self.depth_shm = None

        self.width = 640
        self.height = 480
        self.fps = 30

        self.color_shape = (self.height, self.width, 3)
        self.depth_shape = (self.height, self.width)
        self.color_dtype = np.uint8
        self.depth_dtype = np.float32

        self.result_shm = mp.Manager().list()
        self.intr_shm = Array('f', 9)

        self.capture_proc = None
        self.infer_proc = None
        self.vis_proc = None
        self.service_proc = None
        self.is_running = Value('b', False)
        self.capture_ready = mp.Event()

        self.interested_classes = ["bottle", "orange", "apple", "person"]

    def start(self):
        if self.is_running.value:
            return "Already running."

        self.color_shm = shared_memory.SharedMemory(create=True, size=np.prod(self.color_shape) * self.color_dtype().nbytes)
        self.depth_shm = shared_memory.SharedMemory(create=True, size=np.prod(self.depth_shape) * self.depth_dtype().nbytes)

        self.is_running.value = True

        self.capture_proc = Process(target=self._capture_loop, daemon=True)
        self.infer_proc = Process(target=self._inference_loop, daemon=True)
        self.service_proc = Process(target=self._service_loop, daemon=True)
        self.capture_proc.start()
        self.infer_proc.start()
        self.service_proc.start()
        if self.visualize:
            self.vis_proc = Process(target=self._visualize_loop, daemon=True)
            self.vis_proc.start()
        return "Pipeline started."

    def stop(self):
        if not self.is_running.value:
            return "Not running."
        self.is_running.value = False
        time.sleep(1)
        for proc in [self.capture_proc, self.infer_proc, self.service_proc]:
            if proc and proc.is_alive():
                proc.terminate()
        if self.visualize and self.vis_proc and self.vis_proc.is_alive():
            self.vis_proc.terminate()
        if self.color_shm:
            self.color_shm.close()
            self.color_shm.unlink()
        if self.depth_shm:
            self.depth_shm.close()
            self.depth_shm.unlink()
        return "Pipeline stopped."

    def get_latest_detections(self):
        print(list(self.result_shm))
        return list(self.result_shm)

    def get_interested_detection(self, class_name):
        if class_name not in self.interested_classes:
            print(f"[YOLODetector] {class_name} is not in interested classes.")
            return None
        detections = self.get_latest_detections()
        interested = [d for d in detections if d["class"] == class_name]
        if interested:
            target = min(interested, key=lambda d: d["world"][0])
            print(f"[YOLODetector] Detected {class_name} at coords: {target['world']}.")
            if target["world"][0] < 0.0:
                print(f"[YOLODetector] Ignored {class_name} because invalid distance.")
                return None
            return target
        else:
            print("[YOLODetector] No interested objects detected. Retrying...")
            return None

    # ---------------- Service Loop ----------------
    def _service_loop(self):
        app = FastAPI()
        result_shm = self.result_shm
        interested_classes = self.interested_classes

        def _get_detection(class_name):
            if class_name not in interested_classes:
                return None, f"{class_name} is not in interested classes"
            detections = list(result_shm)
            interested = [d for d in detections if d["class"] == class_name]
            if not interested:
                return None, "No interested objects detected"
            target = min(interested, key=lambda d: d["world"][0])
            if target["world"][0] < 0.0:
                return None, f"Ignored {class_name} because invalid distance"
            return target, None

        @app.get("/detect/{class_name}")
        def detect(class_name: str):
            target, error = _get_detection(class_name)
            if error:
                return JSONResponse(status_code=404, content={"success": False, "error": error})
            return {"success": True, "result": target}

        @app.get("/detections")
        def detections():
            return {"success": True, "result": list(result_shm)}

        @app.get("/health")
        def health():
            return {"status": "ok"}

        print(f"[YOLODetector] HTTP service on http://{self.service_host}:{self.service_port}")
        uvicorn.run(app, host=self.service_host, port=self.service_port, log_level="warning")

    # ---------------- Capture Loop ----------------
    def _capture_loop(self):
        client = ImageClient(
            host=self.image_client_host,
            request_port=self.image_client_request_port,
            rgbd_request_port=self.image_client_rgbd_port,
            request_bgr=True
        )
        print("[YOLODetector] Connecting to ImageClient...")

        _debug_saved = False
        intr_initialized = False
        while not intr_initialized:
            result = client.get_rgbd_frame(camera=self.image_client_camera, timeout=2000)
            if result is None:
                print("[YOLODetector] Waiting for ImageClient RGBD frame...")
                time.sleep(0.5)
                continue
            rgb_image, depth_image, metadata = result
            intr = client.get_intrinsics_matrix()
            intr = np.array(intr, dtype=np.float32).reshape(3, 3)
            self.intr_shm[:] = intr.flatten()
            intr_initialized = True

        self.capture_ready.set()
        print("[YOLODetector] Capture started.")

        color_buf = np.ndarray(self.color_shape, dtype=self.color_dtype, buffer=self.color_shm.buf)
        depth_buf = np.ndarray(self.depth_shape, dtype=self.depth_dtype, buffer=self.depth_shm.buf)

        try:
            while self.is_running.value:
                result = client.get_rgbd_frame(camera=self.image_client_camera, timeout=2000)
                if result is None:
                    print("[YOLODetector] Failed to get RGBD frame, retrying...")
                    time.sleep(0.1)
                    continue

                rgb_image, depth_image, metadata = result

                if rgb_image.shape[:2] != (self.height, self.width):
                    rgb_image = cv2.resize(rgb_image, (self.width, self.height))
                if depth_image.shape[:2] != (self.height, self.width):
                    depth_image = cv2.resize(depth_image, (self.width, self.height), interpolation=cv2.INTER_NEAREST)

                np.copyto(color_buf, rgb_image.astype(self.color_dtype))
                np.copyto(depth_buf, depth_image.astype(self.depth_dtype) * metadata['depth_scale'])

                if not _debug_saved:
                    cv2.imwrite("/tmp/debug_rgb.png", rgb_image)
                    depth_meters = depth_image.astype(np.float32) * metadata['depth_scale']
                    depth_vis = (depth_meters * 1000).clip(0, 65535).astype(np.uint16)
                    cv2.imwrite("/tmp/debug_depth.png", depth_vis)
                    print(f"[YOLODetector] Debug images saved.")
                    print(f"  depth_scale : {metadata['depth_scale']}")
                    print(f"  depth min   : {depth_meters[depth_meters > 0].min():.4f} m")
                    print(f"  depth max   : {depth_meters.max():.4f} m")
                    print(f"  depth center: {depth_meters[self.height//2, self.width//2]:.4f} m")
                    _debug_saved = True

        except Exception as e:
            print(f"[YOLODetector] Capture error: {e}")
        finally:
            client.close()
            print("[YOLODetector] Capture stopped.")

    # ---------------- Inference Loop ----------------
    def _inference_loop(self):
        model = YOLO(self.model_path)
        print("[YOLODetector] YOLO model loaded.")

        self.capture_ready.wait()
        intr = np.frombuffer(self.intr_shm.get_obj(), dtype=np.float32).reshape((3, 3))
        extr = get_default_extrinsics()
        self.tf = CoordinateTransformer(intr, extr)
        print("[YOLODetector] Inference started.")

        color_buf = np.ndarray(self.color_shape, dtype=self.color_dtype, buffer=self.color_shm.buf)
        depth_buf = np.ndarray(self.depth_shape, dtype=self.depth_dtype, buffer=self.depth_shm.buf)

        try:
            while self.is_running.value:
                color_img = color_buf.copy()
                depth_img = depth_buf.copy()

                results = model(color_img, conf=0.5, verbose=False)
                result = results[0]
                class_names = result.names
                detections = []
                for box in result.boxes:
                    class_name = class_names[int(box.cls[0])]
                    u, v = map(int, box.xywh[0][:2])
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    roi_size = 3
                    roi = depth_img[v-roi_size:v+roi_size+1, u-roi_size:u+roi_size+1]
                    depth = float(np.median(roi))
                    x_w, y_w, z_w = self.tf.pixel_to_world([u, v], depth)

                    detections.append({
                        "class": class_name,
                        "bbox": [x1, y1, x2, y2],
                        "pixel": [u, v],
                        "world": [x_w, y_w, z_w]
                    })

                self.result_shm[:] = detections
                time.sleep(0.1)

        except Exception as e:
            print(f"[YOLODetector] Inference error: {e}")
            time.sleep(0.1)
        finally:
            print("[YOLODetector] Inference stopped.")

    # ---------------- Visualizer Loop ----------------
    def _visualize_loop(self):
        print("[YOLODetector] Visualizer started.")
        color_buf = np.ndarray(self.color_shape, dtype=self.color_dtype, buffer=self.color_shm.buf)

        try:
            while self.is_running.value:
                color_frame = color_buf.copy()
                detections = self.get_latest_detections()

                for detection in detections:
                    class_name = detection["class"]
                    x1, y1, x2, y2 = detection["bbox"]
                    u, v = detection["pixel"]
                    x_w, y_w, z_w = detection["world"]

                    cv2.rectangle(color_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.circle(color_frame, (u, v), 6, (0, 0, 255), -1)
                    text = f"{class_name}: ({x_w:.2f}, {y_w:.2f}, {z_w:.2f})"
                    cv2.putText(color_frame, text, (u + 10, v - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                cv2.imshow("YOLO Visualizer", color_frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

        except Exception as e:
            print(f"[YOLODetector] Visualizer error: {e}")
            time.sleep(0.1)
        finally:
            cv2.destroyAllWindows()
            print("[YOLODetector] Visualizer stopped.")


if __name__ == "__main__":
    try:
        detector = YOLODetector("./models/yolov8s-seg.pt", visualize=True,
                                service_host='0.0.0.0', service_port=50022)
        detector.start()
        print("[YOLODetector] Service running. Press Ctrl+C to stop.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[YOLODetector] Interrupted by user, shutting down...")
    finally:
        detector.stop()
