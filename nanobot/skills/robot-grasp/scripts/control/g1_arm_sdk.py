import time
import sys

from unitree_sdk2py.core.channel import ChannelPublisher, ChannelFactoryInitialize
from unitree_sdk2py.core.channel import ChannelSubscriber, ChannelFactoryInitialize
from unitree_sdk2py.idl.default import unitree_hg_msg_dds__LowCmd_
from unitree_sdk2py.idl.default import unitree_hg_msg_dds__LowState_
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_
from unitree_sdk2py.utils.crc import CRC
from unitree_sdk2py.utils.thread import RecurrentThread
from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import MotionSwitcherClient

import numpy as np

kPi = 3.141592654

class G1JointIndex:
    # Left leg
    LeftHipPitch = 0
    LeftHipRoll = 1
    LeftHipYaw = 2
    LeftKnee = 3
    LeftAnklePitch = 4
    LeftAnkleB = 4
    LeftAnkleRoll = 5
    LeftAnkleA = 5

    # Right leg
    RightHipPitch = 6
    RightHipRoll = 7
    RightHipYaw = 8
    RightKnee = 9
    RightAnklePitch = 10
    RightAnkleB = 10
    RightAnkleRoll = 11
    RightAnkleA = 11

    WaistYaw = 12
    WaistRoll = 13        # NOTE: INVALID for g1 23dof/29dof with waist locked
    WaistA = 13           # NOTE: INVALID for g1 23dof/29dof with waist locked
    WaistPitch = 14       # NOTE: INVALID for g1 23dof/29dof with waist locked
    WaistB = 14           # NOTE: INVALID for g1 23dof/29dof with waist locked

    # Left arm
    LeftShoulderPitch = 15
    LeftShoulderRoll = 16
    LeftShoulderYaw = 17
    LeftElbow = 18
    LeftWristRoll = 19
    LeftWristPitch = 20   # NOTE: INVALID for g1 23dof
    LeftWristYaw = 21     # NOTE: INVALID for g1 23dof

    # Right arm
    RightShoulderPitch = 22
    RightShoulderRoll = 23
    RightShoulderYaw = 24
    RightElbow = 25
    RightWristRoll = 26
    RightWristPitch = 27  # NOTE: INVALID for g1 23dof
    RightWristYaw = 28    # NOTE: INVALID for g1 23dof

    kNotUsedJoint = 29 # NOTE: Weight

class Custom:
    def __init__(self):
        ChannelFactoryInitialize(0)

        self.time_ = 0.0
        self.control_dt_ = 0.02  
        self.duration_ = 3.0   
        self.counter_ = 0
        self.weight = 0.
        self.weight_rate = 0.2
        self.kp = 60.
        self.kd = 1.5
        self.dq = 0.
        self.tau_ff = 0.
        self.mode_machine_ = 0
        self.low_cmd = unitree_hg_msg_dds__LowCmd_()  
        self.low_state = None # 当前手臂关节状态
        self.first_update_low_state = False
        self.crc = CRC()
        self.done = False

        self.target_joint = [0,0] * 17 # 初始化占位

        self.arm_joints = [
          G1JointIndex.LeftShoulderPitch,  G1JointIndex.LeftShoulderRoll,
          G1JointIndex.LeftShoulderYaw,    G1JointIndex.LeftElbow,
          G1JointIndex.LeftWristRoll,      G1JointIndex.LeftWristPitch,
          G1JointIndex.LeftWristYaw,
          G1JointIndex.RightShoulderPitch, G1JointIndex.RightShoulderRoll,
          G1JointIndex.RightShoulderYaw,   G1JointIndex.RightElbow,
          G1JointIndex.RightWristRoll,     G1JointIndex.RightWristPitch,
          G1JointIndex.RightWristYaw,
          G1JointIndex.WaistYaw,
          G1JointIndex.WaistRoll,
          G1JointIndex.WaistPitch
        ]

    def Init(self):
        # create publisher #
        self.arm_sdk_publisher = ChannelPublisher("rt/arm_sdk", LowCmd_)
        self.arm_sdk_publisher.Init()

        # create subscriber # 
        self.lowstate_subscriber = ChannelSubscriber("rt/lowstate", LowState_)
        self.lowstate_subscriber.Init(self.LowStateHandler, 10)

        # init thread
        self.lowCmdWriteThreadPtr = None

        print("[ArmController] G1 arm7 sdk init done.")

    def Start(self, release=False):
        # reset state before start thread
        self.time_ = 0.0
        self.done = False

        self.lowCmdWriteThreadPtr = RecurrentThread(
            interval=self.control_dt_, target=self.LowCmdWrite, name="control", args=(release,)
        )
        while self.first_update_low_state == False:
            time.sleep(1)

        if self.first_update_low_state == True:
            self.lowCmdWriteThreadPtr.Start()

    def Stop(self):
        # stop control thread
        if self.lowCmdWriteThreadPtr is not None:
            self.lowCmdWriteThreadPtr.Wait()

    def LowStateHandler(self, msg: LowState_):
        self.low_state = msg

        if self.first_update_low_state == False:
            self.first_update_low_state = True
        
    def LowCmdWrite(self, release=False):
        self.time_ += self.control_dt_

        if self.time_ < self.duration_:
            self.low_cmd.motor_cmd[G1JointIndex.kNotUsedJoint].q = 1 # 1:Enable arm_sdk, 0:Disable arm_sdk
            # [Stage 1] transform to the target joint smoothly 
            for i, joint in enumerate(self.arm_joints):
                ratio = np.clip(self.time_ / self.duration_, 0.0, 1.0)
                self.low_cmd.motor_cmd[joint].tau = 0. 
                self.low_cmd.motor_cmd[joint].q = ratio * self.target_joint[i] + (1.0 - ratio) * self.low_state.motor_state[joint].q 
                self.low_cmd.motor_cmd[joint].dq = 0. 
                self.low_cmd.motor_cmd[joint].kp = self.kp 
                self.low_cmd.motor_cmd[joint].kd = self.kd
        elif self.time_ < self.duration_ * 2 and release:
            # [Stage 2] release arm_sdk 
            ratio = np.clip((self.time_ - self.duration_) / (self.duration_), 0.0, 1.0)
            self.low_cmd.motor_cmd[G1JointIndex.kNotUsedJoint].q =  (1 - ratio) # 1:Enable arm_sdk, 0:Disable arm_sdk
        else:
            self.done = True
  
        self.low_cmd.crc = self.crc.Crc(self.low_cmd)
        self.arm_sdk_publisher.Write(self.low_cmd)

    def Control(self, joint):
        self.target_joint = joint
        self.Start()

        while not self.done:        
            time.sleep(0.1)
        print("[ArmController] Control Done!")

        self.Stop()

    def Release(self):
        # first stop current thread
        self.Stop()
        
        self.target_joint = [
            0.0, kPi/9, 0.0, kPi/2, 0.0, 0.0, 0.0, 
            0.0, -kPi/9, 0.0, kPi/2, 0.0, 0.0, 0.0, 
            0.0, 0.0, 0.0
        ] # set robot back to zero posture
        self.Start(release=True)
        
        while not self.done:        
            time.sleep(0.1)
        print("[ArmController] Release Done!")

        self.Stop()
        self.arm_sdk_publisher.Close()
        time.sleep(1)


if __name__ == '__main__':

    print("WARNING: Please ensure there are no obstacles around the robot while running this example.")
    input("Press Enter to continue...")

    if len(sys.argv)>1:
        ChannelFactoryInitialize(0, sys.argv[1])
    else:
        ChannelFactoryInitialize(0)

    custom = Custom()
    custom.Init()
    
    # target_joint = [
    #     0.0, kPi/3, 0.0, kPi/2, 0.0, 0.0, 0.0, 
    #     0.0, -kPi/3, 0.0, kPi/2, 0.0, 0.0, 0.0, 
    #     0.0, 0.0, 0.0
    # ]
    target_joint = [
        0.0, kPi/3, 0.0, kPi/2, 0.0, 0.0, 0.0, 
        0.0, -kPi/10, 0.0, kPi/2, 0.0, 0.0, 0.0, 
        0.0, 0.0, 0.0
    ]
    custom.Control(target_joint)
    target_joint = [
        0.0, kPi/3, 0.0, 0.0, 0.0, 0.0, 0.0, 
        0.0, -kPi/9, 0.0, kPi/2, 0.0, 0.0, 0.0, 
        0.0, 0.0, 0.0
    ]
    custom.Control(target_joint)
    input("Press Enter to release...")
    custom.Release()

    