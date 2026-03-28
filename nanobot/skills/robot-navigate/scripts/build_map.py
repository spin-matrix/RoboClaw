#!/usr/bin/env python3
import sys
import json
from pathlib import Path

from g1_slam_client import SlamClient
from unitree_sdk2py.core.channel import ChannelFactoryInitialize

POSE_FILE =  Path(__file__).resolve().parent / "poses.json"
STATE_FILE = Path(__file__).resolve().parent / "slam_state.json"


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


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("start", "end"):
        print(f"Usage: python3 {sys.argv[0]} start | end [map_name]")
        sys.exit(-1)
    

    action = sys.argv[1]

    

    ChannelFactoryInitialize(0, "eth0")

    client = SlamClient()
    client.SetTimeout(10.0)
    client.Init()

    if action == "start":
        code, data = client.start_mapping()
        print(f"[start_mapping] statusCode={code}")
        print(f"[start_mapping] data={data}")

    elif action == "end":
        # map_name = sys.argv[2] if len(sys.argv) > 2 else "test"
        map_name = "map"

        code, data = client.end_mapping(pcd_name=map_name)
        print(f"[end_mapping] statusCode={code}")
        print(f"[end_mapping] data={data}")

        state = {
            "has_map": True,
            "map_name": map_name,
            "initialized": False,
            "last_relocation_time": "",
            "current_goal": ""
        }
        save_state(state)

        if POSE_FILE.exists():
            POSE_FILE.unlink()
            print("旧目标点已清空，请基于新地图重新记录目标点。")

        code, data = client.stop_slam()
        print(f"[stop_slam] statusCode={code}")
        print(f"[stop_slam] data={data}")


if __name__ == "__main__":
    main()
