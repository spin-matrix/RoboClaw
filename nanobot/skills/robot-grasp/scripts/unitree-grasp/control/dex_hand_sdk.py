# for dex3-1
from unitree_sdk2py.core.channel import ChannelPublisher, ChannelSubscriber, ChannelFactoryInitialize # dds
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import HandCmd_, HandState_                               # idl
from unitree_sdk2py.idl.default import unitree_hg_msg_dds__HandCmd_

import numpy as np
from enum import IntEnum
import time
import os
import sys
import threading
from multiprocessing import Process, shared_memory, Array, Lock


unitree_tip_indices = [4, 9, 14] # [thumb, index, middle] in OpenXR
Dex3_Num_Motors = 7
kTopicDex3LeftCommand = "rt/dex3/left/cmd"
kTopicDex3RightCommand = "rt/dex3/right/cmd"
kTopicDex3LeftState = "rt/dex3/left/state"
kTopicDex3RightState = "rt/dex3/right/state"


class Dex3_1_DirectController:
    def __init__(self, fps=100.0, Unit_Test=True):
        self.fps = fps
        
        if not Unit_Test:
            ChannelFactoryInitialize(0)
        else:
            ChannelFactoryInitialize(0)

        # init
        self.LeftHandCmb_publisher = ChannelPublisher(kTopicDex3LeftCommand, HandCmd_)
        self.LeftHandCmb_publisher.Init()
        self.RightHandCmb_publisher = ChannelPublisher(kTopicDex3RightCommand, HandCmd_)
        self.RightHandCmb_publisher.Init()

        self.LeftHandState_subscriber = ChannelSubscriber(kTopicDex3LeftState, HandState_)
        self.LeftHandState_subscriber.Init()
        self.RightHandState_subscriber = ChannelSubscriber(kTopicDex3RightState, HandState_)
        self.RightHandState_subscriber.Init()

        self.left_hand_state_array  = Array('d', Dex3_Num_Motors, lock=True)  
        self.right_hand_state_array = Array('d', Dex3_Num_Motors, lock=True)

        # initialize subscribe thread
        self.subscribe_state_thread = threading.Thread(target=self._subscribe_hand_state)
        self.subscribe_state_thread.daemon = True
        self.subscribe_state_thread.start()

        self.left_msg = unitree_hg_msg_dds__HandCmd_()
        self.right_msg = unitree_hg_msg_dds__HandCmd_()
        
        # init control params
        self._init_hand_msg(self.left_msg, Dex3_1_Left_JointIndex)
        self._init_hand_msg(self.right_msg, Dex3_1_Right_JointIndex)

        # init predefined hand gestures
        self.open_left_target = [-0.02, -0.8, 0.1, -0.1, -0.1, -0.1, -0.1]
        self.close_left_target = [-0.02, 0.1, 1.3, -1.3, -1.3, -1.3, -1.3]
        self.open_right_target = [0.02, 0.8, -0.1, 0.1, 0.1, 0.1, 0.1]
        self.close_right_target = [0.02, -0.1, -1.3, 0.8, 0.8, 0.8, 0.8]

        self.object_hand = None # which hand has been used
        
        print("[DexHandController] Dex3-1 hand sdk init done..")

    def _init_hand_msg(self, msg, joint_indices):
        for id in joint_indices:
            ris_mode = self._RIS_Mode(id=id, status=0x01)
            msg.motor_cmd[id].mode = ris_mode._mode_to_uint8()
            msg.motor_cmd[id].q = 0.0
            msg.motor_cmd[id].dq = 0.0
            msg.motor_cmd[id].tau = 0.0
            msg.motor_cmd[id].kp = 1.5
            msg.motor_cmd[id].kd = 0.2

    class _RIS_Mode:
        def __init__(self, id=0, status=0x01, timeout=0):
            self.motor_mode = 0
            self.id = id & 0x0F
            self.status = status & 0x07
            self.timeout = timeout & 0x01

        def _mode_to_uint8(self):
            self.motor_mode |= (self.id & 0x0F)
            self.motor_mode |= (self.status & 0x07) << 4
            self.motor_mode |= (self.timeout & 0x01) << 7
            return self.motor_mode

    def ctrl_dual_hand(self, left_q, right_q):
        for idx, id in enumerate(Dex3_1_Left_JointIndex):
            self.left_msg.motor_cmd[id].q = left_q[idx]
        for idx, id in enumerate(Dex3_1_Right_JointIndex):
            self.right_msg.motor_cmd[id].q = right_q[idx]

        self.LeftHandCmb_publisher.Write(self.left_msg)
        self.RightHandCmb_publisher.Write(self.right_msg)
    
    def _subscribe_hand_state(self):
        while True:
            left_hand_msg  = self.LeftHandState_subscriber.Read()
            right_hand_msg = self.RightHandState_subscriber.Read()
            if left_hand_msg is not None and right_hand_msg is not None:
                # Update left hand state
                for idx, id in enumerate(Dex3_1_Left_JointIndex):
                    self.left_hand_state_array[idx] = left_hand_msg.motor_state[id].q
                    # print(f"left hand {idx}: {left_hand_msg.motor_state[id].q}")
                # Update right hand state
                for idx, id in enumerate(Dex3_1_Right_JointIndex):
                    self.right_hand_state_array[idx] = right_hand_msg.motor_state[id].q
            time.sleep(0.002)

    def _stop_hand_msg(self, msg, joint_indices):
        for id in joint_indices:
            ris_mode = self._RIS_Mode(id=id, status=0x01)
            msg.motor_cmd[id].mode = ris_mode._mode_to_uint8()
            msg.motor_cmd[id].q = 0.0
            msg.motor_cmd[id].dq = 0.0
            msg.motor_cmd[id].tau = 0.0
            msg.motor_cmd[id].kp = 0.0
            msg.motor_cmd[id].kd = 0.0
        self.LeftHandCmb_publisher.Write(msg)
        self.RightHandCmb_publisher.Write(msg)
        
    def ctrl_left_hand(self, left_q):
        for idx, id in enumerate(Dex3_1_Left_JointIndex):
            self.left_msg.motor_cmd[id].q = left_q[idx]
        self.LeftHandCmb_publisher.Write(self.left_msg)

    def ctrl_right_hand(self, right_q):
        for idx, id in enumerate(Dex3_1_Right_JointIndex):
            self.right_msg.motor_cmd[id].q = right_q[idx]
        self.RightHandCmb_publisher.Write(self.right_msg)

    # predefined hand gestures
    def open_hand(self, hand_flag="left"):
        if hand_flag == "left":
            for i in range(100):
                self.ctrl_left_hand(self.open_left_target)
                time.sleep(0.01)
        elif hand_flag == "right":
            for i in range(100):
                self.ctrl_right_hand(self.open_right_target)
                time.sleep(0.01)
        else:
            print("[DexHandController] Invalid hand. Use 'left' or 'right'.")
            return
        print(f"[DexHandController] Hand opened.")
    
    def close_hand(self, hand_flag="left"):
        if hand_flag == "left":
            for i in range(100):
                self.ctrl_left_hand(self.close_left_target)
                time.sleep(0.01)
        elif hand_flag == "right":
            for i in range(100):
                self.ctrl_right_hand(self.close_right_target)
                time.sleep(0.01)
        else:
            print("[DexHandController] Invalid hand. Use 'left' or 'right'.")
            return
        print(f"[DexHandController] Hand closed.")
    
    def release_hand(self):
        self._stop_hand_msg(self.left_msg, Dex3_1_Left_JointIndex)
        print(f"[DexHandController] Released hand control.")

class Dex3_1_Left_JointIndex(IntEnum):
    kLeftHandThumb0 = 0
    kLeftHandThumb1 = 1
    kLeftHandThumb2 = 2
    kLeftHandMiddle0 = 3
    kLeftHandMiddle1 = 4
    kLeftHandIndex0 = 5
    kLeftHandIndex1 = 6

class Dex3_1_Right_JointIndex(IntEnum):
    kRightHandThumb0 = 0
    kRightHandThumb1 = 1
    kRightHandThumb2 = 2
    kRightHandIndex0 = 3
    kRightHandIndex1 = 4
    kRightHandMiddle0 = 5
    kRightHandMiddle1 = 6


if __name__ == "__main__":
    """
    [关节角度说明] 以左手为例, 右手同理对称控制但符号相反
    - 大拇指
        0 保持0即可, 左右转为正负, 其中以手心指向方向, 逆时针为正
        1 负, 垂直于手为0, 扩张为正, 最大约0.8, 收缩为负，最大约-0.8
        2 负 
    - 食指 & 中指
        3 4 5 6 负, 伸直为0, 弯曲为负, 范围约-0.1~-1.5

    [控制方式说明] 1.单步控制 2.平滑控制
    - 两种方式都可以，但都需要限定关节范围，不能超过灵巧手限制，否则后续无法执行命令
    - 对于第二种方式，指定的初始位置很重要，一般需要循环等待获取非零当前初始状态，才可执行
    """
    hand_ctrl = Dex3_1_DirectController(Unit_Test=True)
    hand_ctrl.close_hand("left")
    hand_ctrl.release_hand()



    # target_left = [-0.021564174443483353, 0.6272138357162476, 1.6098734140396118, -1.5759963989257812, -1.690682053565979, -1.5748772621154785, -1.6696088314056396]
    # target_right = [-0.03433346375823021, -0.9274282455444336, -1.4750117063522339, 1.5631415843963623, 1.6800073385238647, 1.1243813037872314, 1.6955289840698242]
    # for i in range(100):
    #     target_left = list(hand_ctrl.left_hand_state_array)
    # for i in range(100):
    #     target_left[3] += 0.005
    #     target_left[4] += 0.005 
    #     target_left[5] += 0.005
    #     target_left[6] += 0.005
    #     hand_ctrl.ctrl_dual_hand(target_left, target_right)
    #     time.sleep(0.02)
    # hand_ctrl._stop_hand_msg(hand_ctrl.left_msg, Dex3_1_Left_JointIndex)