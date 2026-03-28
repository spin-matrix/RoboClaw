import time

from action_executor import ActionExecutor
from yolo_detector import YOLODetector

executor = ActionExecutor()
detector = YOLODetector("./models/yolov8s-seg.pt", False)
detector.start()

target_class = "orange"


if __name__ == "__main__":
    try:
        while True:
            # Step 1: Detect target class objects
            while True:
                detection = detector.get_interested_detection(target_class)
                if detection:
                    coords = detection["world"]
                    break
                time.sleep(1)

            # input("Press any key to continue.")
            
            # Step 2: Move to expected distance
            cur_dis = coords[0]
            expect_dis = 0.4
            if cur_dis > expect_dis:
                executor.move_forward(cur_dis-expect_dis+0.1)
            else:
                print("Already within expected distance.")

            # Step 3: Execute grasping action
            while True:
                # Refresh detection to get updated coords
                detection = detector.get_interested_detection(target_class)
                if detection:
                    coords = detection["world"]
                    break
                time.sleep(1)
                
            # input("Press any key to continue.")
            suc = executor.grasp(coords)
            # input("Press any key to continue.")

            if suc:
                # Step 4: Execute other action
                # arm_flag = "left" if coords[1] > 0 else "right"
                # executor.hand_ctrl.open_hand(arm_flag) # here just open hand

                # Step 5: Retract arm
                executor.retract()
            else:
                print("Grasping failed. Retrying...")

            user_input = input("Press 'n' to grasp next object, otherwise exit.")
            if user_input.lower() != 'n':
                break

    except KeyboardInterrupt:
        user_input = input("Demo interrupted. Press 'r' to release arm.")
        if user_input.lower() == 'r':
            executor.release()
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        detector.stop()
