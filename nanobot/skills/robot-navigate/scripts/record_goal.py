#!/usr/bin/env python3
import sys
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from g1_slam_client import SlamClient
from unitree_sdk2py.core.channel import ChannelSubscriber, ChannelFactoryInitialize
from unitree_sdk2py.idl.std_msgs.msg.dds_._String_ import String_

SLAM_INFO_TOPIC = "rt/slam_info"

POSE_FILE =  Path(__file__).resolve().parent / "poses.json"
STATE_FILE = Path(__file__).resolve().parent / "slam_state.json"

@dataclass
class PoseData:
    name: str
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    q_x: float = 0.0
    q_y: float = 0.0
    q_z: float = 0.0
    q_w: float = 1.0
    mode: int = 1


class GoalRecorder:
    def __init__(self, interface: str):
        ChannelFactoryInitialize(0, interface)

        self.current_pose = None

        self.sub = ChannelSubscriber(SLAM_INFO_TOPIC, String_)
        self.sub.Init(self.slam_info_callback, 1)

    def slam_info_callback(self, msg: String_):
        try:
            json_data = json.loads(msg.data)
            if json_data.get("errorCode", -1) != 0:
                return
            if json_data.get("type") == "pos_info":
                pose = json_data["data"]["currentPose"]
                self.current_pose = {
                    "x": float(pose.get("x", 0.0)),
                    "y": float(pose.get("y", 0.0)),
                    "z": float(pose.get("z", 0.0)),
                    "q_x": float(pose.get("q_x", 0.0)),
                    "q_y": float(pose.get("q_y", 0.0)),
                    "q_z": float(pose.get("q_z", 0.0)),
                    "q_w": float(pose.get("q_w", 1.0)),
                    "mode": 1,
                }
        except Exception as e:
            print(f"parse slam_info failed: {e}")

    def wait_pose(self, timeout=5.0):
        start = time.time()
        while time.time() - start < timeout:
            if self.current_pose is not None:
                return True
            time.sleep(0.1)
        return False


def load_poses():
    if POSE_FILE.exists():
        with POSE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {"poses": []}


def save_poses(data):
    with POSE_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python3 {sys.argv[0]} <goal_name>")
        sys.exit(-1)

    goal_name = sys.argv[1]

    recorder = GoalRecorder("eth0")

    print("等待当前位置...")
    if not recorder.wait_pose():
        print("获取当前位置失败")
        sys.exit(-1)

    pose = PoseData(name=goal_name, **recorder.current_pose)

    data = load_poses()
    data["poses"].append(asdict(pose))
    save_poses(data)

    print(f"已保存目标点: {goal_name}")
    print(asdict(pose))


if __name__ == "__main__":
    main()
