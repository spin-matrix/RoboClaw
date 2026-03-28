import sys
import time
import math
import numpy as np
import pinocchio as pin
import requests
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
from control.g1_arm_sdk import Custom
# from control.linker_hand_sdk import O6_DirectJointController
from control.dex_hand_sdk import Dex3_1_DirectController

ARM_IK_URL = "http://127.0.0.1:50021"

def call_ik(left_pos, right_pos):
    """
    Call arm_ik_server to solve IK.
    left_pos / right_pos: [x, y, z, roll, pitch, yaw]
    Returns: joint list (17 elements) or raises RuntimeError.
    """
    resp = requests.post(
        f"{ARM_IK_URL}/api/server/ik",
        json={"left_pos": left_pos, "right_pos": right_pos},
        timeout=5,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data["success"]:
        raise RuntimeError("IK server returned failure.")
    return data["joints"]


class ActionExecutor:
    def __init__(self, arm_ik_url=ARM_IK_URL):
        global ARM_IK_URL
        ARM_IK_URL = arm_ik_url

        # self.hand_ctrl = O6_DirectJointController(
        #     left_can_port="can1",
        #     right_can_port="can0",
        #     fps=50.0,
        # )
        self.hand_ctrl = Dex3_1_DirectController()

        self.arm_ctrl = Custom()
        self.arm_ctrl.Init()

        ChannelFactoryInitialize(0, "eth0")
        self.sport_client = LocoClient()
        self.sport_client.SetTimeout(5.0)
        self.sport_client.Init()

        self.kPi = math.pi
        self.is_running = False

    def _arm_pos_control(self, target_left_pos, target_right_pos):
        """
        pos format: [x, y, z, roll, pitch, yaw]
        """
        if not self.is_running:
            raise RuntimeError("Executor is not running.")

        target_q = call_ik(target_left_pos, target_right_pos)
        self.arm_ctrl.Control(target_q)

    def _single_arm_pos_control(self, target_pos, arm_flag):
        """
        pos format: [x, y, z, roll, pitch, yaw]
        arm_flag: 'left' or 'right'
        """
        if not self.is_running:
            raise RuntimeError("Executor is not running.")

        if arm_flag == 'left':
            flag = 1
        elif arm_flag == 'right':
            flag = -1
        else:
            print("Invalid arm. Use 'left' or 'right'.")
            return

        another_pos = [0.25, 0.25 * flag, 0.1, 0.0, 0.0, 0.0]

        if arm_flag == 'left':
            target_q = call_ik(target_pos, another_pos)
            # replace right-arm joints with fixed pose
            q_another = [0, -self.kPi / 9 * flag, 0, self.kPi / 2, 0, 0, 0]
            target_q = target_q[:7] + q_another + [0] * 3
        else:
            target_q = call_ik(another_pos, target_pos)
            q_another = [0, -self.kPi / 9 * flag, 0, self.kPi / 2, 0, 0, 0]
            target_q = q_another + target_q[7:14] + [0] * 3

        self.arm_ctrl.Control(target_q)

    def _arm_joint_control(self, target_q):
        """
        q format: [q1, q2, ..., q14] without waist
        """
        if not self.is_running:
            raise RuntimeError("Executor is not running.")

        target_q_full = target_q + [0] * 3
        self.arm_ctrl.Control(target_q_full)

    def move_forward(self, distance, speed=0.3):
        duration = distance / speed
        self.sport_client.SetVelocity(speed, 0, 0, duration)
        time.sleep(duration)

    def stop_move(self):
        self.sport_client.SetVelocity(0, 0, 0, 1)

    def shake(self):
        self.sport_client.ShakeHand()
        time.sleep(3)
        self.sport_client.ShakeHand()

    def grasp(self, target_coords):
        """
        coords format: [x, y, z]
        """
        if target_coords is None:
            print("[ActionExecutor] Grasp target is None!")
            return False
        elif target_coords[0] < 0:
            print("[ActionExecutor] Grasp target is negative in x direction!")
            return False
        elif target_coords[0] < 0.1:
            print("[ActionExecutor] Grasp target is too close!")
            return False
        elif target_coords[0] > 0.45:
            print("[ActionExecutor] Grasp target is too far!")
            return False

        arm_flag = "left" if target_coords[1] > 0 else "right"
        flag = 1 if arm_flag == "left" else -1

        self.is_running = True
        try:
            print("[ActionExecutor] Grasping at coords: ", target_coords, " with", arm_flag, "arm.")
            self.hand_ctrl.object_hand = arm_flag

            # [Stage 1] Move arm to pre-grasp position and open hand
            pre_pos = [0.1, 0.25 * flag, target_coords[2] + 0.1, 0.0, 0.0, 0.0]
            self._single_arm_pos_control(pre_pos, arm_flag)
            self.hand_ctrl.open_hand(arm_flag)

            # [Stage 2] Move arm to mid pos
            mid_pos_1 = [
                (0.1 + target_coords[0]) / 2, target_coords[1], target_coords[2] + 0.2,
                0.0, 0.0, 0.0
            ]
            self._single_arm_pos_control(mid_pos_1, arm_flag)

            # [Stage 3] Move arm to grasp position and close hand
            grasp_pos = [
                # target_coords[0] - 0.05, target_coords[1], target_coords[2],
                target_coords[0] + 0.05, target_coords[1], target_coords[2]+0.1,
                0.8 * flag, 0.0, 0.0
            ]
            self._single_arm_pos_control(grasp_pos, arm_flag)
            self.hand_ctrl.close_hand(arm_flag)

            print("[ActionExecutor] Grasp completed.")
            return True

        except Exception as e:
            print("[ActionExecutor] Grasp error: ", e)
            return False

        finally:
            self.is_running = False

    def regrasp(self, target_coords):
        """
        coords format: [x, y, z]
        """
        if target_coords is None:
            print("[ActionExecutor] Grasp target is None!")
            return False
        elif target_coords[0] < 0:
            print("[ActionExecutor] Grasp target is negative in x direction!")
            return False
        elif target_coords[0] < 0.1:
            print("[ActionExecutor] Grasp target is too close!")
            return False
        elif target_coords[0] > 0.45:
            print("[ActionExecutor] Grasp target is too far!")
            return False

        arm_flag = "left" if target_coords[1] > 0 else "right"
        flag = 1 if arm_flag == "left" else -1

        self.is_running = True
        try:
            print("[ActionExecutor] Regrasping at coords: ", target_coords, " with", arm_flag, "arm.")
            self.hand_ctrl.object_hand = arm_flag

            self.hand_ctrl.open_hand(arm_flag)
            grasp_pos = [
                target_coords[0] + 0.05, target_coords[1], target_coords[2] + 0.05,
                0.0, 0.0, 0.0
            ]
            self._single_arm_pos_control(grasp_pos, arm_flag)
            self.hand_ctrl.close_hand(arm_flag)

            print("[ActionExecutor] Regrasp completed.")
            return True

        except Exception as e:
            print("[ActionExecutor] Regrasp error: ", e)
            return False

        finally:
            self.is_running = False

    def hand_over(self, arm_flag=None):
        if arm_flag is None:
            arm_flag = self.hand_ctrl.object_hand

        if arm_flag is None:
            print("[ActionExecutor] No object to hand over!")
            return False

        self.is_running = True
        try:
            print("[ActionExecutor] Handing over from", arm_flag, "hand.")
            flag = 1 if arm_flag == "left" else -1
            hand_over_pos = [0.35, 0.25 * flag, 0.15, 0.0, 0.0, 0.0]
            self._single_arm_pos_control(hand_over_pos, arm_flag)

            time.sleep(1)
            self.hand_ctrl.open_hand(arm_flag)

            self.release()
            print("[ActionExecutor] Hand over completed.")
            return True

        except Exception as e:
            print("[ActionExecutor] Hand over error:", e)
            return False

        finally:
            self.is_running = False
            self.hand_ctrl.object_hand = None

    def retract(self, arm_flag=None):
        self.is_running = True
        try:
            if arm_flag is None:
                arm_flag = self.hand_ctrl.object_hand

            if arm_flag == 'left':
                flag = 1
            elif arm_flag == 'right':
                flag = -1
            else:
                print("No object inhand, cannot retract!")
                return
            print("[ActionExecutor] Retracting", arm_flag, "arm.")

            self.hand_ctrl.close_hand(arm_flag)
            mid_pos = [0.3, 0.25 * flag, 0.25, 0.0, 0.0, 0.0]
            self._single_arm_pos_control(mid_pos, arm_flag)

            pre_pos = [0.05, 0.3 * flag, 0.15, 0.0, 0.0, 0.0]
            self._single_arm_pos_control(pre_pos, arm_flag)

            self.arm_ctrl.Release()

            print("[ActionExecutor] Retract completed.")
            return True

        except Exception as e:
            print("[ActionExecutor] Retract error:", e)
            return False

        finally:
            self.is_running = False

    def release(self):
        self.hand_ctrl.release_hand()
        self.arm_ctrl.Release()


if __name__ == "__main__":
    executor = ActionExecutor()
    # executor.hand_over("right")
    # executor.shake()
    while True:
        try:
            target_coords = [0.35, -0.1, 0.1]
            suc = executor.grasp(target_coords)
            if suc:
                executor.retract()
            input()
        except KeyboardInterrupt:
            print("[ActionExecutor] User interrupted. Exiting...")
            executor.release()
            sys.exit(0)
