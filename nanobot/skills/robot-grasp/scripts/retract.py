import time
import sys
import argparse


from action_executor import ActionExecutor

def parse_arg():
    parser = argparse.ArgumentParser(description="use sdk to retract")
    parser.add_argument(
        'hand',
        type=str,
        help='which hand to retract, left or right'
    )
    args = parser.parse_args()
    return args

if __name__ == "__main__":
    executor = ActionExecutor()

    try:    
        args = parse_arg()
        hand_flag = args.hand
        suc = executor.retract(hand_flag)
        if suc:
            print(f"[Unitree] Retract success: Use {hand_flag} hand")
        else:
            print("[Unitree] Retract failed")

    except Exception as e:
        print(f"[Unitree] Retract failed: An error occurred: {e}")
