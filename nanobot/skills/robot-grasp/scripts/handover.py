import time
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
    parser = argparse.ArgumentParser(description="use sdk to handover")
    parser.add_argument(
        'hand',
        type=str,
        help='which hand to handover, left or right'
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
    hand_flag = args.hand
    DETECTOR_URL = args.detector_url

    executor = ActionExecutor()

    try:
        # Step 1: Detect person
        s = time.time()
        while True:
            detection = get_interested_detection("person")
            if detection:
                coords = detection["world"]
                if coords[0] > 3.0:
                    print(f"Detected human is too far for handover.")
                    time.sleep(1)
                    continue
                else:
                    break
            time.sleep(1)
            e = time.time()
            if e - s > 10:
                print(f"[Unitree] Handover failed: No person detected within timeout.")
                exit(1)

        # Step 2: Move to expected distance
        cur_dis = coords[0]
        expect_dis = 0.6
        if cur_dis > expect_dis:
            executor.move_forward(cur_dis - expect_dis)
        else:
            print("Already within expected distance.")

        # Step 3: Execute handover action
        suc = executor.hand_over(hand_flag)
        if suc:
            print(f"[Unitree] Handover success")
        else:
            print("[Unitree] Handover failed")

    except Exception as e:
        print(f"[Unitree] Handover failed: An error occurred: {e}")
