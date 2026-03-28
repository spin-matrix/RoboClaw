import json
from unitree_sdk2py.rpc.client import Client
from unitree_sdk2py.core.channel import ChannelFactoryInitialize

SLAM_SERVICE_NAME = "slam_operate"
SLAM_API_VERSION = "1.0.0.1"

ROBOT_API_ID_STOP_NODE = 1901
ROBOT_API_ID_START_MAPPING_PL = 1801
ROBOT_API_ID_END_MAPPING_PL = 1802
ROBOT_API_ID_START_RELOCATION_PL = 1804
ROBOT_API_ID_POSE_NAV_PL = 1102
ROBOT_API_ID_PAUSE_NAV = 1201
ROBOT_API_ID_RESUME_NAV = 1202


class SlamClient(Client):
    def __init__(self):
        super().__init__(SLAM_SERVICE_NAME, False)

    def Init(self):
        self._SetApiVerson(SLAM_API_VERSION)
        self._RegistApi(ROBOT_API_ID_STOP_NODE, 0)
        self._RegistApi(ROBOT_API_ID_START_MAPPING_PL, 0)
        self._RegistApi(ROBOT_API_ID_END_MAPPING_PL, 0)
        self._RegistApi(ROBOT_API_ID_START_RELOCATION_PL, 0)
        self._RegistApi(ROBOT_API_ID_POSE_NAV_PL, 0)
        self._RegistApi(ROBOT_API_ID_PAUSE_NAV, 0)
        self._RegistApi(ROBOT_API_ID_RESUME_NAV, 0)

    def stop_slam(self):
        parameter = {"data": {}}
        code, data = self._Call(ROBOT_API_ID_STOP_NODE, json.dumps(parameter))
        return code, data

    def start_mapping(self):
        parameter = {"data": {"slam_type": "indoor"}}
        code, data = self._Call(ROBOT_API_ID_START_MAPPING_PL, json.dumps(parameter))
        return code, data

    def end_mapping(self, pcd_name: str = "test"):
        parameter = {"data": {"address": f"/home/unitree/{pcd_name}.pcd"}}
        code, data = self._Call(ROBOT_API_ID_END_MAPPING_PL, json.dumps(parameter))
        return code, data

    def start_relocation(self, pcd_name: str = "test", pose: dict = None):
        parameter = {
            "data": {
                "x": 0.0,
                "y": 0.0,
                "z": 0.0,
                "q_x": 0.0,
                "q_y": 0.0,
                "q_z": 0.0,
                "q_w": 1.0,
                "address": f"/home/unitree/{pcd_name}.pcd",
            }
        }
        if pose is not None:
            parameter["data"].update(pose)

        code, data = self._Call(ROBOT_API_ID_START_RELOCATION_PL, json.dumps(parameter))
        return code, data

    def pause_navigation(self):
        parameter = {"data": {}}
        code, data = self._Call(ROBOT_API_ID_PAUSE_NAV, json.dumps(parameter))
        return code, data

    def resume_navigation(self):
        parameter = {"data": {}}
        code, data = self._Call(ROBOT_API_ID_RESUME_NAV, json.dumps(parameter))
        return code, data

    def pose_navigation(self, pose: dict):
        code, data = self._Call(ROBOT_API_ID_POSE_NAV_PL, json.dumps(pose))
        return code, data
