import time
import sys
import argparse
import requests

from action_executor import ActionExecutor

DETECTOR_URL = "http://127.0.0.1:50022"

def get_interested_detection(target: str):
    try:
        resp = requests.get(f"{DETECTOR_URL}/detect/{target}", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                return data["result"]
        return None
    except requests.exceptions.RequestException as e:
        print(f"[Unitree] HTTP request failed: {e}")
        return None

def parse_arg():
    parser = argparse.ArgumentParser(description="use sdk to grasp")
    parser.add_argument(
        'target',
        type=str,
        help='target object class to grasp'
    )
    parser.add_argument(
        '--detector-url',
        type=str,
        default=DETECTOR_URL,
        help='YOLODetector service URL (default: http://127.0.0.1:8000)'
    )
    args = parser.parse_args()
    return args

if __name__ == "__main__":
    args = parse_arg()
    target = args.target
    DETECTOR_URL = args.detector_url

    executor = ActionExecutor()

    try:
        if target is None:
            print("[Unitree] Grasp failed: No target provided")
            raise ValueError("No target provided")

        # Step 1: Detect objects
        s = time.time()
        while True:
            detection = get_interested_detection(target)
            if detection:
                coords = detection["world"]
                if coords[0] > 1.0:
                    print(f"Detected object is too far for grasp.")
                    time.sleep(1)
                    continue
                else:
                    break
            time.sleep(1)
            if time.time() - s > 10:
                print(f"[Unitree] Grasp failed: No {target} detection within timeout")
                exit(1)

        # Step 2: Move to expected distance
        # cur_dis = coords[0]
        # expect_dis = 0.4
        # if cur_dis > expect_dis:
        #     # executor.move_forward(cur_dis - expect_dis + 0.1)
        # else:
        #     print("Already within expected distance.")

        # Step 3: Execute grasping action
        s = time.time()
        while True:
            detection = get_interested_detection(target)
            if detection:
                coords = detection["world"]
                if coords[0] > 1.0:
                    print(f"Detected object is too far for grasp.")
                    time.sleep(1)
                    continue
                else:
                    break
            time.sleep(1)
            if time.time() - s > 10:
                print(f"[Unitree] Grasp failed: No {target} detection within timeout")
                exit(1)

        suc = executor.grasp(coords)
        if suc:
            print(f"[Unitree] Grasp success: Use {executor.hand_ctrl.object_hand} hand")
        else:
            print("[Unitree] Grasp failed")

    except Exception as e:
        print(f"[Unitree] Grasp failed: An error occurred: {e}")
