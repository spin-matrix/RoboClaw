#!/usr/bin/env python3
import sys
import json
import time
import threading
from pathlib import Path
import requests
import math
from g1_slam_client import SlamClient
from unitree_sdk2py.core.channel import ChannelSubscriber, ChannelFactoryInitialize
from unitree_sdk2py.idl.std_msgs.msg.dds_._String_ import String_
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient

POSE_FILE =  Path(__file__).resolve().parent / "poses.json"
STATE_FILE = Path(__file__).resolve().parent / "slam_state.json"

SLAM_KEY_INFO_TOPIC = "rt/slam_key_info"
SLAM_INFO_TOPIC = "rt/slam_info"

# ===== 你可以调的参数 =====
FORWARD_VX = 0.3          # 服务确认“无障碍”后，向前走一小段的速度
FORWARD_DURATION = 1.0    # 向前走一小段的持续时间（秒）

TURN_WZ = 0.6              # 左转角速度（rad/s），需要实机微调
TURN_90_DURATION = 3.1415926 / (5 * TURN_WZ)   # 粗略 90 度时长

MAX_ROTATION_CHECKS = 10    # 最多检查 4 个方向（共 360°）

WAIT_RESULT_POLL = 0.05    # 主线程等待导航结果的轮询间隔

NEAR_POS_THRESH = 0.20      # 距离目标点小于 0.30 米，认为位置已接近
NEAR_YAW_THRESH_DEG = 15.0   # 朝向差小于 20 度，认为朝向已接近

def load_state():
    if STATE_FILE.exists():
        with STATE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "has_map": False,
        "map_name": "",
        "initialized": False,
        "last_relocation_time": "",
        "current_goal": ""
    }


def save_state(state):
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=4, ensure_ascii=False)


def load_poses():
    if POSE_FILE.exists():
        with POSE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {"poses": []}


def get_pose_name(p, idx):
    return p.get("name", f"pose_{idx}")


def find_target_pose(poses, goal_name):
    for i, p in enumerate(poses):
        if get_pose_name(p, i) == goal_name:
            return p
    return None


class NavRunner:
    def __init__(self, interface: str):
        ChannelFactoryInitialize(0, interface)

        self.lock = threading.Lock()

        # 导航任务状态
        self.is_arrived = False
        self.task_finished = False
        self.last_result = None
        self.task_failed = False
        self.nav_active = False

        # 当前目标点
        self.current_target = None
        self.current_pose = None

        # 碰撞处理状态
        self.collision_paused = False
        self.handling_collision = False

        # 线程事件
        self.collision_event = threading.Event()
        self.shutdown_event = threading.Event()

        self.client = SlamClient()
        self.client.SetTimeout(10.0)
        self.client.Init()

        self.sport_client = LocoClient()
        self.sport_client.SetTimeout(3.0)
        self.sport_client.Init()

        self.key_sub = ChannelSubscriber(SLAM_KEY_INFO_TOPIC, String_)
        self.key_sub.Init(self.key_info_callback, 1)

        self.info_sub = ChannelSubscriber(SLAM_INFO_TOPIC, String_)
        self.info_sub.Init(self.slam_info_callback, 1)

        self.worker_thread = threading.Thread(
            target=self.collision_worker,
            daemon=True
        )
        self.worker_thread.start()

    # ======== 工具函数 ========
    def _ret_ok(self, ret):
        if isinstance(ret, tuple):
            return len(ret) > 0 and ret[0] == 0
        return ret == 0

    def _make_nav_payload(self, pose):
        return {
            "data": {
                "targetPose": {
                    "x": pose["x"],
                    "y": pose["y"],
                    "z": pose["z"],
                    "q_x": pose["q_x"],
                    "q_y": pose["q_y"],
                    "q_z": pose["q_z"],
                    "q_w": pose["q_w"],
                },
                "mode": int(pose.get("mode", 1))
            }
        }

    # ======== 订阅回调 ========
    def key_info_callback(self, msg: String_):
        try:
            json_data = json.loads(msg.data)
        except Exception as e:
            print(f"parse slam_key_info failed: {e}")
            return

        if json_data.get("errorCode", -1) != 0:
            print(f"[slam_key_info][ERROR] {json.dumps(json_data, ensure_ascii=False)}")
            return

        if json_data.get("type") != "task_result":
            return

        is_arrived = bool(json_data.get("data", {}).get("is_arrived", False))
        target_name = json_data.get("data", {}).get("targetNodeName", "unknown")

        with self.lock:
            # 在手动碰撞处理期间，底层可能给旧任务发 failed/cancelled
            # 这类结果直接忽略，避免把新流程打断
            if self.handling_collision and (not is_arrived):
                print(f"忽略碰撞处理期间的失败 task_result: {target_name}")
                print(json.dumps(json_data, indent=4, ensure_ascii=False))
                return

            self.task_finished = True
            self.is_arrived = is_arrived
            self.last_result = json_data
            self.task_failed = not is_arrived
            self.nav_active = False

        if is_arrived:
            print(f"I arrived {target_name}")
        else:
            print(f"I not arrived {target_name}")
            print(json.dumps(json_data, indent=4, ensure_ascii=False))

    def slam_info_callback(self, msg: String_):
        try:
            json_data = json.loads(msg.data)
        except Exception as e:
            print(f"parse slam_info failed: {e}")
            return

        msg_type = json_data.get("type")

        # 1) 实时更新当前位置
        if json_data.get("errorCode", -1) == 0 and msg_type == "pos_info":
            try:
                pose = json_data["data"]["currentPose"]
                with self.lock:
                    self.current_pose = pose
            except Exception as e:
                print(f"parse pos_info failed: {e}")
            return

        # 2) collision 可能带 errorCode=421，不要按 errorCode 过滤
        if msg_type != "collision":
            return

        should_trigger = False

        with self.lock:
            if (
                self.nav_active
                and (not self.task_finished)
                and (not self.collision_paused)
                and (not self.handling_collision)
            ):
                self.collision_paused = True
                self.handling_collision = True
                should_trigger = True

        if not should_trigger:
            return

        print(f"[slam_info][collision] {json.dumps(json_data, ensure_ascii=False)}")
        self.collision_event.set()

    # ======== 导航动作 ========
    def nav_to(self, pose):
        with self.lock:
            self.is_arrived = False
            self.task_finished = False
            self.last_result = None
            self.task_failed = False
            self.nav_active = False
            self.collision_paused = False
            self.current_target = pose

        payload = self._make_nav_payload(pose)

        code, data = self.client.pose_navigation(payload)
        print(f"[pose_navigation] statusCode={code}")
        print(f"[pose_navigation] data={data}")

        if code == 0:
            with self.lock:
                self.nav_active = True

        return code

    def pause_nav(self):
        ret = self.client.pause_navigation()
        print(f"[pause_navigation] ret={ret}")
        return self._ret_ok(ret)

    def resume_nav(self):
        ret = self.client.resume_navigation()
        print(f"[resume_navigation] ret={ret}")
        if self._ret_ok(ret):
            with self.lock:
                self.nav_active = True
                self.collision_paused = False
            return 0
        return -1

    # ======== 服务确认逻辑 ========
    def query_obstacle_service(self):
        """
        返回:
            True  -> 确认有障碍
            False -> 确认无障碍

        这里你必须替换成老师给你的真实服务调用。
        下面只是一个占位示例。
        """
        try:
            # ===== TODO: 替换这里 =====
            #
            # 例如：
            # result = your_client.check_obstacle()
            # return bool(result.has_obstacle)
            #
            # 当前先默认“有障碍”，避免误撞。
            #
            print("[query_obstacle_service] 当前是占位逻辑，请替换成真实服务调用。默认返回: 有障碍")
            res = requests.get("http://127.0.0.1:50020/get_status")
            if res:
                res_data = res.json()
                is_safe = res_data.get("is_safe") == False
                unsafe_side = res_data.get("unsafe_side")

            else:
                raise Exception(f"HTTP 请求失败，状态码: {res.status_code}")
            return is_safe,unsafe_side

        except Exception as e:
            print(f"请求障碍确认服务失败: {e}")
            # 安全起见：服务失败时按“有障碍”处理
            return True

    # ======== 手动动作 ========
    def forward_a_little(self):
        print("服务确认无障碍，向前走一小段...")

        ret = self.sport_client.SetVelocity(
            FORWARD_VX,
            0.0,
            0.0,
            FORWARD_DURATION
        )
        print(f"[forward_a_little][SetVelocity] ret={ret}")

        time.sleep(FORWARD_DURATION + 0.15)
        return 0

    def turn_left_90(self):
        print(f"服务确认有障碍，左转 90°，duration={TURN_90_DURATION:.2f}s")

        ret = self.sport_client.SetVelocity(
            0.0,
            0.0,
            TURN_WZ,
            TURN_90_DURATION
        )
        print(f"[turn_left_90][SetVelocity] ret={ret}")

        time.sleep(TURN_90_DURATION + 0.2)
        return 0

    def turn_right_90(self):
        print(f"右转 90°，duration={TURN_90_DURATION:.2f}s")

        ret = self.sport_client.SetVelocity(
            0.0,
            0.0,
            -TURN_WZ,
            TURN_90_DURATION
        )
        print(f"[turn_right_90][SetVelocity] ret={ret}")

        time.sleep(TURN_90_DURATION + 0.2)
        return 0


    def turn_by_unsafe_side(self, unsafe_side):
        """
        规则：
        - 右边不安全 -> 左转
        - 左边不安全 -> 右转
        - 其他情况 -> 默认左转
        """

        side = str(unsafe_side).strip().lower()

        if side in ("right", "r", "右", "right_side"):
            print("检测到右边不安全，执行左转 90°")
            return self.turn_left_90()

        elif side in ("left", "l", "左", "left_side"):
            print("检测到左边不安全，执行右转 90°")
            return self.turn_right_90()

        else:
            print(f"unsafe_side={unsafe_side} 无法识别，默认左转 90°")
            return self.turn_left_90()

    def _yaw_from_pose(self, pose):
        """
        从 2D pose 提取 yaw。
        默认按 q_z / q_w 计算，适合平面导航。
        """
        qz = float(pose.get("q_z", 0.0))
        qw = float(pose.get("q_w", 1.0))
        return 2.0 * math.atan2(qz, qw)


    def _normalize_angle(self, angle):
        while angle > math.pi:
            angle -= 2.0 * math.pi
        while angle < -math.pi:
            angle += 2.0 * math.pi
        return angle


    def _angle_diff(self, a, b):
        return abs(self._normalize_angle(a - b))


    def is_near_target(self, target):
        """
        判断当前位姿是否已经足够接近目标点，且朝向也足够接近。
        """
        with self.lock:
            pose = self.current_pose

        if pose is None:
            return False

        try:
            dx = float(pose["x"]) - float(target["x"])
            dy = float(pose["y"]) - float(target["y"])
            dist = math.hypot(dx, dy)

            current_yaw = self._yaw_from_pose(pose)
            target_yaw = self._yaw_from_pose(target)
            yaw_diff = self._angle_diff(current_yaw, target_yaw)

            yaw_thresh = math.radians(NEAR_YAW_THRESH_DEG)

            print(
                f"[near_target_check] dist={dist:.3f} m, "
                f"yaw_diff={math.degrees(yaw_diff):.1f} deg"
            )

            return dist <= NEAR_POS_THRESH and yaw_diff <= yaw_thresh

        except Exception as e:
            print(f"is_near_target failed: {e}")
            return False


    def mark_arrived_locally(self, target):
        target_name = target.get("name", "unknown")

        with self.lock:
            self.task_finished = True
            self.is_arrived = True
            self.task_failed = False
            self.nav_active = False
            self.last_result = {
                "type": "local_arrival",
                "data": {
                    "targetNodeName": target_name
                }
            }

        print(f"当前已足够接近目标点 {target_name}，直接判定到达成功。")

    # ======== 碰撞处理策略 ========
    def handle_collision_strategy(self, target):
        """
        流程:
            1. pause_navigation
            2. 请求服务确认
            3. 无障碍 -> 向前走一小段 -> 重新导航
            4. 有障碍 -> 左转 90° -> 再请求服务
            5. 最多转 4 次（360°）
            6. 若 360° 仍有障碍 -> 返回失败
        """
        print("开始碰撞处理流程...")

        if not self.pause_nav():
            print("暂停导航失败，本次碰撞处理失败。")
            return False

        with self.lock:
            self.nav_active = False

        # 最多检查 4 个朝向
        for i in range(MAX_ROTATION_CHECKS):
            has_obstacle, unsafe_side = self.query_obstacle_service()
            print("判定机器人是否与目标点相近")
            if self.is_near_target(target):
                self.mark_arrived_locally(target)
                return True

            if not has_obstacle:
                print(f"第 {i + 1} 次确认：无障碍")
                self.forward_a_little()

                # 小步向前后，重新发送导航去原目标点
                code = self.nav_to(target)
                if code != 0:
                    print("向前走后恢复导航失败。")
                    return False

                print("已恢复导航到原目标点。")
                return True

            print(f"第 {i + 1} 次确认：有障碍")

            # 如果已经检查到第 4 个方向了，还都有障碍，直接失败
            if i == MAX_ROTATION_CHECKS - 1:
                print("已经转满 360° 仍然有障碍，报告失败。")
                return False

            self.turn_by_unsafe_side(unsafe_side)

        return False

    # ======== worker 线程 ========
    def collision_worker(self):
        while not self.shutdown_event.is_set():
            self.collision_event.wait()

            if self.shutdown_event.is_set():
                break

            self.collision_event.clear()

            with self.lock:
                target = self.current_target
                task_dead = self.task_finished or self.task_failed

            if task_dead or target is None:
                with self.lock:
                    self.handling_collision = False
                    self.collision_paused = False
                continue

            ok = self.handle_collision_strategy(target)

            with self.lock:
                if not ok:
                    self.task_finished = True
                    self.is_arrived = False
                    self.task_failed = True
                    self.nav_active = False

                self.handling_collision = False
                self.collision_paused = False

    # ======== 主线程等待 ========
    def wait_for_result(self, timeout_sec=180.0):
        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            with self.lock:
                if self.task_finished:
                    return "arrived" if self.is_arrived else "failed"
            time.sleep(WAIT_RESULT_POLL)

        return "timeout"

    def is_task_dead(self):
        with self.lock:
            return self.task_finished or self.task_failed

    def close(self):
        self.shutdown_event.set()
        self.collision_event.set()
        if self.worker_thread.is_alive():
            self.worker_thread.join(timeout=1.0)


def list_goals():
    """列出当前可用的目标点。"""
    state = load_state()
    if not state["has_map"]:
        print("当前没有地图，请先建图")
        sys.exit(-1)

    all_poses = load_poses()["poses"]
    if not all_poses:
        print("当前没有目标点，请先运行 record_goal.py")
        sys.exit(-1)

    print("当前可用目标点:")
    for i, p in enumerate(all_poses):
        print("-", get_pose_name(p, i))


def navigate_to(goal_name):
    """导航到指定目标点。"""
    state = load_state()
    if not state["has_map"]:
        print("当前没有地图，请先建图")
        sys.exit(-1)

    if not state["initialized"]:
        print("当前未初始化，请先运行 init_pose.py")
        sys.exit(-1)

    all_poses = load_poses()["poses"]
    if not all_poses:
        print("当前没有目标点，请先运行 record_goal.py")
        sys.exit(-1)

    runner = NavRunner("eth0")

    try:
        target = find_target_pose(all_poses, goal_name)
        if target is None:
            print(f"未找到目标点: {goal_name}")
            print("当前可用目标点:")
            for i, p in enumerate(all_poses):
                print("-", get_pose_name(p, i))
            return

        code = runner.nav_to(target)
        if code != 0:
            print("导航请求发送失败。")
            return

        state["current_goal"] = goal_name
        save_state(state)

        print("等待导航结果...")

        while True:
            result = runner.wait_for_result(timeout_sec=1800.0)

            if result == "arrived":
                print(f"已到达 {goal_name}。")
                break

            elif result == "failed":
                print(f"导航到 {goal_name} 失败。")
                break

            else:
                print(f"导航到 {goal_name} 超时。")
                break

    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，准备退出。")

    finally:
        runner.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Unitree G1 机器人导航工具")
    parser.add_argument("-l", "--list", action="store_true", help="列出当前可用的目标点")
    parser.add_argument("-t", "--target", type=str, help="导航到指定目标点")

    args = parser.parse_args()

    if args.list:
        list_goals()
    elif args.target:
        navigate_to(args.target)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
