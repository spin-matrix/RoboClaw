#!/usr/bin/env python3

import sys
import os
import time
import numpy as np
from multiprocessing import Process, Array, Lock
import threading
import pathlib

linker_hand_sdk_path = './control/linkerhand-python-sdk'
sys.path.append(linker_hand_sdk_path)
sys.path.append(str(pathlib.Path(os.getcwd()).parent))

from LinkerHand.linker_hand_api import LinkerHandApi

O6_Num_Motors = 6

# 预设关节姿态 (归一化, 长度 6)
#   顺序: [thumb_pitch, thumb_yaw, index, middle, ring, pinky]

class O6_DirectJointController:
    """
    直接关节控制版 Linker Hand O6 双手控制器。

    使用示例:
        ctrl = O6_DirectJointController()
        ctrl.open_hand("right")
        ctrl.close_hand("both")
        ctrl.release_hand("left")
        ctrl.set_joints("right", [1.0, 0.5, 0.8, 0.8, 0.8, 0.8])  # 精细控制
    """

    def __init__(
        self,
        left_can_port: str = "can1",
        right_can_port: str = "can0",
        fps: float = 50.0,
    ):
        """
        :param left_can_port:  左手 CAN 接口名，None 表示不启用左手。
        :param right_can_port: 右手 CAN 接口名，None 表示不启用右手。
        :param fps:            控制循环频率 (Hz)。
        """
        print(
            f"[O6] Initializing — left_can:{left_can_port}  "
            f"right_can:{right_can_port}  fps:{fps}"
        )
        # 初始化常量
        self._POSE_RELEASE = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]    # 全部伸直复位
        self._POSE_OPEN    = [0.8, 0.0, 1.0, 1.0, 1.0, 1.0]    # 拇指侧摆内收，其余伸直
        # self._POSE_CLOSE   = [0.5, 0.1, 0.25, 0.25, 0.25, 0.25]  # 弯曲约 75%，用于抓取
        self._POSE_CLOSE   = [0.5, 0.0, 0.7, 0.7, 0.7, 0.7]  # 弯曲约 75%，用于抓取

        self._HAND_SIDES = ("left", "right", "both")
        self.object_hand = None

        self.fps = fps
        self.left_can_port  = left_can_port
        self.right_can_port = right_can_port

        # ── 关节指令共享数组 [左手×6, 右手×6]，初始全部伸直 ─────────────────
        self._joint_cmd = Array('d', O6_Num_Motors * 2, lock=True)
        with self._joint_cmd.get_lock():
            self._joint_cmd[:] = self._POSE_CLOSE * 2

        # ── 关节状态共享数组（硬件反馈，归一化 [0,1]）────────────────────────
        self._left_state  = Array('d', O6_Num_Motors, lock=True)
        self._right_state = Array('d', O6_Num_Motors, lock=True)

        # ── 向外暴露的状态/动作记录数组 ──────────────────────────────────────
        self._state_lock   = Lock()
        self._shared_state  = Array('d', O6_Num_Motors * 2, lock=False)
        self._shared_action = Array('d', O6_Num_Motors * 2, lock=False)

        # ── 初始化 LinkerHand API（主进程，用于状态订阅线程）────────────────
        self._left_api, self._right_api = self._init_api(left_can_port, right_can_port)

        # ── 启动硬件状态订阅线程 ──────────────────────────────────────────────
        threading.Thread(target=self._subscribe_state, daemon=True).start()

        # ── 启动控制子进程 ────────────────────────────────────────────────────
        Process(
            target=O6_DirectJointController._control_loop,
            args=(
                self._joint_cmd,
                self._left_state,
                self._right_state,
                self._state_lock,
                self._shared_state,
                self._shared_action,
                left_can_port,
                right_can_port,
                fps,
            ),
            daemon=True,
        ).start()

        print("[O6] Controller ready.\n")

    # ─────────────────────────────────────────────────────────────────────────
    # 公开动作接口
    # ─────────────────────────────────────────────────────────────────────────

    def open_hand(self, side: str):
        """
        张开手掌（预备抓取姿态）。
        拇指侧摆内收 (yaw=0.3)，拇指屈伸伸直，其余四指全部伸直。

        :param side: "left" | "right" | "both"
        """
        self._apply_pose(side, self._POSE_OPEN)
        print(f"[O6] open_hand  → {side}")

    def close_hand(self, side: str):
        """
        握拳抓取（弯曲约 75%）。
        所有关节弯曲至约 25% 位置（即弯曲 75%），适合稳定抓取。

        :param side: "left" | "right" | "both"
        """
        self._apply_pose(side, self._POSE_CLOSE)
        print(f"[O6] close_hand → {side}")

    def release_hand(self, side: str="both"):
        """
        松开复位（全部伸直）。
        所有关节恢复 1.0（完全伸直），用于释放物体或初始化姿态。

        :param side: "left" | "right" | "both"
        """
        self._apply_pose(side, self._POSE_RELEASE)
        print(f"[O6] release_hand → {side}")

    def set_joints(self, side: str, pose: list):
        """
        直接指定归一化关节角度（精细控制接口）。

        :param side: "left" | "right" | "both"
        :param pose: 长度 6 的列表，每个值 [0.0, 1.0]
                     顺序: [thumb_pitch, thumb_yaw, index, middle, ring, pinky]
        """
        assert len(pose) == O6_Num_Motors, \
            f"pose 长度必须为 {O6_Num_Motors}，当前为 {len(pose)}"
        self._apply_pose(side, pose)

    def get_state(self) -> dict:
        """
        读取当前关节状态（硬件反馈，归一化 [0,1]）。

        :return: {"left": [float×6], "right": [float×6]}
        """
        with self._state_lock:
            return {
                "left":  list(self._shared_state[:O6_Num_Motors]),
                "right": list(self._shared_state[O6_Num_Motors:]),
            }

    # ─────────────────────────────────────────────────────────────────────────
    # 内部实现
    # ─────────────────────────────────────────────────────────────────────────

    def _apply_pose(self, side: str, pose: list):
        """将姿态写入对应手的指令槽（线程安全）。"""
        assert side in self._HAND_SIDES, \
            f"side 必须为 {self._HAND_SIDES}，当前为 '{side}'"
        with self._joint_cmd.get_lock():
            if side in ("right", "both"):
                self._joint_cmd[O6_Num_Motors:] = pose
            if side in ("left", "both"):
                self._joint_cmd[:O6_Num_Motors] = pose
        time.sleep(2)

    def _subscribe_state(self):
        """
        后台线程：持续从硬件读取关节状态并写入共享数组。
        硬件返回值范围 [0, 255] → 归一化到 [0, 1]。
        """
        print("[O6] State subscribe thread started.")
        while True:
            for api, state_arr, label in (
                (self._left_api,  self._left_state,  "left"),
                (self._right_api, self._right_state, "right"),
            ):
                if api is None:
                    continue
                msg = api.get_state()
                if msg is not None and len(msg) == O6_Num_Motors:
                    with state_arr.get_lock():
                        for i in range(O6_Num_Motors):
                            state_arr[i] = msg[i] / 255.0
                elif msg is not None:
                    print(
                        f"[O6] Unexpected {label} state length: {len(msg)}"
                    )
            time.sleep(0.002)   # ~500 Hz 轮询

    @staticmethod
    def _init_api(left_can_port, right_can_port):
        """初始化左右手 API，端口为 None 则跳过。"""
        left_api  = (
            LinkerHandApi(hand_joint='O6', hand_type="left",  can=left_can_port)
            if left_can_port else None
        )
        right_api = (
            LinkerHandApi(hand_joint='O6', hand_type="right", can=right_can_port)
            if right_can_port else None
        )
        return left_api, right_api

    @staticmethod
    def _control_loop(
        joint_cmd,
        left_state_arr,
        right_state_arr,
        state_lock,
        shared_state,
        shared_action,
        left_can_port,
        right_can_port,
        fps,
    ):
        """
        控制子进程主循环（静态方法，避免 multiprocessing 序列化整个实例）。

        每帧:
          1. 从 joint_cmd 读取归一化指令 [0,1]
          2. 缩放为 [0,255] 并发送给硬件
          3. 将状态/动作写入共享记录数组
        """
        left_api, right_api = O6_DirectJointController._init_api(
            left_can_port, right_can_port
        )
        print("[O6] Control process started.")

        while True:
            t0 = time.time()

            # 读取并裁切指令
            with joint_cmd.get_lock():
                cmd = np.clip(np.array(joint_cmd[:]), 0.0, 1.0)

            left_q  = cmd[:O6_Num_Motors]
            right_q = cmd[O6_Num_Motors:]

            # [0,1] → [0,255] → 发送
            left_cmd  = [int(v * 255) for v in left_q]
            right_cmd = [int(v * 255) for v in right_q]
            if left_api  is not None: left_api.finger_move(pose=left_cmd)
            if right_api is not None: right_api.finger_move(pose=right_cmd)

            # 读取硬件状态
            left_st  = (np.array(left_state_arr[:])  if left_api  is not None
                        else np.zeros(O6_Num_Motors))
            right_st = (np.array(right_state_arr[:]) if right_api is not None
                        else np.zeros(O6_Num_Motors))

            # 写入共享记录
            with state_lock:
                shared_state[:]  = np.concatenate((left_st,  right_st))
                shared_action[:] = np.concatenate((left_q,   right_q))

            time.sleep(max(0.0, 1.0 / fps - (time.time() - t0)))


if __name__ == '__main__':

    ctrl = O6_DirectJointController(
        left_can_port="can1",       # None = 不启用左手
        right_can_port="can0",
        fps=50.0,
    )

    try:
        ctrl.close_hand("left")
        ctrl.open_hand("right")
        ctrl.close_hand("right")
        ctrl.open_hand("right")
        ctrl.release_hand("right")
    except KeyboardInterrupt:
        print("\n[INFO] 用户中断。")
    finally:
        ctrl.release_hand("both")
        time.sleep(0.5)
        print("[INFO] 已复位，程序退出。")