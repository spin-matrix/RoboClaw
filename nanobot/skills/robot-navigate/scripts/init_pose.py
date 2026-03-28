#!/usr/bin/env python3
import sys
import json
from datetime import datetime
from pathlib import Path

from g1_slam_client import SlamClient
from unitree_sdk2py.core.channel import ChannelFactoryInitialize

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
    if len(sys.argv) < 2:
        print(f"Usage: python3 {sys.argv[0]} <networkInterface>")
        sys.exit(-1)

    interface = sys.argv[1]

    state = load_state()
    if not state["has_map"]:
        print("当前本地状态显示没有地图，请先运行 build_map.py")
        sys.exit(-1)

    print("请确认机器人已经放到初始化位置附近。")
    input("确认后按回车开始重定位...")

    ChannelFactoryInitialize(0, "eth0")

    client = SlamClient()
    client.SetTimeout(10.0)
    client.Init()

    code, data = client.start_relocation(pcd_name=state["map_name"])
    print(f"[start_relocation] statusCode={code}")
    print(f"[start_relocation] data={data}")

    state["initialized"] = (code == 0)
    state["last_relocation_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_state(state)

    # code, data = client.stop_slam()
    # print(f"[stop_slam] statusCode={code}")
    # print(f"[stop_slam] data={data}")


if __name__ == "__main__":
    main()