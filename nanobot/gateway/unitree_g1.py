"""Hardware interface for the Unitree G1 robot via the g1_loco_client CLI.

Reference: https://support.unitree.com/home/zh/G1_developer/rpc_routine

Key flags
---------
--network_interface <iface>            网卡名，默认 eth0
--set_velocity "vx vy omega [dur]"     设置速度并可选持续时间(秒)
--move "vx vy omega"                   持续运动（不带时长）
--stop_move                            停止运动
--damp                                 进入阻尼模式
--start                                进入主运控
--stand_up                             站立
--squat                                蹲下
--sit                                  落座
--balance_stand                        平衡站立
--zero_torque                          零力矩模式
--continous_gait true/false            连续步态
--switch_move_mode true/false          切换运动模式
--set_speed_mode 0/1/2/3               走跑最高速度档位
--set_fsm_id <id>                      设置状态机 id（动作）
"""

from __future__ import annotations

import asyncio
import shutil
from typing import Optional

from loguru import logger

from nanobot.gateway.models import Action

DEFAULT_NETWORK_INTERFACE = "eth0"

# parameter for named actions (wave / handshake / etc.)
_ALL_ACTIONS: dict[str, Action] = {
    "release_arm": Action(action_id="release_arm", action_name="手臂复位", action_params={"id": 99, "duration": 2.0, "icon_url": "/static/icons/放下手臂.png"}),
    "blow_kiss_with_left_hand": Action(action_id="blow_kiss_with_left_hand", action_name="左手飞吻", action_params={"id": 12, "duration": 8.0, "icon_url": "/static/icons/左手飞吻.png"}),
    "blow_kiss_with_right_hand": Action(action_id="blow_kiss_with_right_hand", action_name="右手飞吻", action_params={"id": 13, "duration": 8.0, "icon_url": "/static/icons/右手飞吻.png"}),
    "both_hands_up": Action(action_id="both_hands_up", action_name="双手举起", action_params={"id": 15, "duration": 6.5, "icon_url": "/static/icons/双手举起.png"}),
    "clamp": Action(action_id="clamp", action_name="鼓掌", action_params={"id": 17, "duration": 6.5, "icon_url": "/static/icons/鼓掌.png"}),
    # "high_five": Action(action_id="high_five", action_name="击掌", action_params={"id": 18, "duration": 6.5, "icon_url": "/static/icons/击掌.png"}),
    # "make_heart_with_right_hand": Action(action_id="make_heart_with_right_hand", action_name="右手比心", action_params={"id": 21, "duration": 6.5, "icon_url": "/static/icons/右手比心.png"}),
    "refuse": Action(action_id="refuse", action_name="拒绝", action_params={"id": 22, "duration": 6.5, "icon_url": "/static/icons/拒绝.png"}),
    "right_hand_up": Action(action_id="right_hand_up", action_name="右手举起", action_params={"id": 23, "duration": 6.5, "icon_url": "/static/icons/右手举起.png"}),
    # "ultraman_ray": Action(action_id="ultraman_ray", action_name="奥特曼光线", action_params={"id": 24, "duration": 7.5, "icon_url": "/static/icons/奥特曼光线.png"}),
    # "wave_under_head": Action(action_id="wave_under_head", action_name="挥手", action_params={"id": 25, "duration": 7.5, "icon_url": "/static/icons/挥手.png"}),
    # "wave_above_head": Action(action_id="wave_above_head", action_name="高举挥手", action_params={"id": 26, "duration": 8.0, "icon_url": "/static/icons/高举挥手.png"}),
    "shake_hand": Action(action_id="shake_hand", action_name="握手", action_params={"id": 27, "duration": 6.0, "icon_url": "/static/icons/握手.png"}),
    "box_both_hand_win": Action(action_id="box_both_hand_win", action_name="双手高举欢呼", action_params={"id": 30, "duration": 6.5, "icon_url": "/static/icons/双手高举欢呼.png"}),
    # "box_left_hand_win": Action(action_id="box_left_hand_win", action_name="左手出拳胜利", action_params={"id": 28, "duration": 6.5, "icon_url": "/static/icons/左手出拳胜利.png"}),
    # "box_right_hand_win": Action(action_id="box_right_hand_win", action_name="右手出拳胜利", action_params={"id": 29, "duration": 6.5, "icon_url": "/static/icons/右手出拳胜利.png"}),
    # "right_hand_on_heart": Action(action_id="right_hand_on_heart", action_name="右手放胸口", action_params={"id": 33, "duration": 7.5, "icon_url": "/static/icons/右手放胸口.png"}),
    # "Waist_Drum_Dance": Action(action_id="Waist_Drum_Dance", action_name="腰鼓舞", action_params={"name": "Waist_Drum_Dance", "duration": 10.5, "icon_url": "/static/icons/腰鼓舞.png"}),
    # "Scratch_head": Action(action_id="Scratch_head", action_name="挠头", action_params={"name": "Scratch_head", "duration": 9.0, "icon_url": "/static/icons/挠头.png"}),
    # "Spin_discs": Action(action_id="Spin_discs", action_name="转盘舞", action_params={"name": "Spin_discs", "duration": 8.0, "icon_url": "/static/icons/转盘舞.png"}),
    # "speak": Action(action_id="speak", action_name="朗读", action_params={"content": "你好！", "duration": 3.0, "icon_url": "/static/icons/朗读.png"}),
}

# Direction → (vx, vy, omega) sign multipliers; magnitude comes from speed.
_MOVE_VEC: dict[str, tuple[float, float, float]] = {
    "forward":  ( 1,  0,  0),
    "backward": (-1,  0,  0),
    "left":     ( 0,  1,  0),
    "right":    ( 0, -1,  0),
}

_ROTATE_VEC: dict[str, tuple[float, float, float]] = {
    "left":  (0, 0,  1),
    "right": (0, 0, -1),
}


class LocoClient:
    """Thin async wrapper around the *g1_loco_client* binary.

    If the binary is absent from PATH every call is a no-op (log only),
    so the gateway runs fine on dev machines without robot hardware.
    """

    def __init__(self, network_interface: str = DEFAULT_NETWORK_INTERFACE) -> None:
        self.network_interface = network_interface
        loco_client_binary = shutil.which("g1_loco_client")
        arm_action_binary = shutil.which("g1_arm_action")
        audio_client_binary = shutil.which("g1_audio_client")
        self._loco_client_binary: Optional[str] = loco_client_binary
        self._arm_action_binary: Optional[str] = arm_action_binary
        self._audio_client_binary: Optional[str] = audio_client_binary

        if loco_client_binary:
            logger.info("g1_loco_client found: {} (interface={})", loco_client_binary, network_interface)
        else:
            logger.warning(
                "g1_loco_client not found in PATH — move/rotate commands will be skipped"
            )
        if arm_action_binary:
            logger.info("g1_arm_action found: {}", arm_action_binary)
        else:
            logger.warning(
                "g1_arm_action not found in PATH — arm action commands will be skipped"
            )
        if audio_client_binary:
            logger.info("g1_audio_client found: {}", audio_client_binary)
        else:
            logger.warning(
                "g1_audio_client not found in PATH — audio commands will be skipped"
            )

    @property
    def loco_client_available(self) -> bool:
        return self._loco_client_binary is not None

    @property
    def arm_action_available(self) -> bool:
        return self._arm_action_binary is not None

    @property
    def audio_client_available(self) -> bool:
        return self._audio_client_binary is not None

    @property
    def all_actions(self) -> dict[str, Action]:
        return _ALL_ACTIONS

    # ── internal ──────────────────────────────────────────────────────────────

    async def _loco_client_exec(self, *flags: str) -> None:
        """Run: g1_loco_client --network_interface <iface> <flags...>"""
        if not self._loco_client_binary:
            logger.info("g1_loco_client unavailable, skipping: {}", " ".join(flags))
            return
        args = [self._loco_client_binary, f"--network_interface={self.network_interface}", *flags]
        logger.info("g1_loco_client: {}", " ".join(args))
        proc = await asyncio.create_subprocess_exec(*args)
        await proc.wait()

    async def _arm_action_exec(self, *flags: str) -> None:
        """Run: g1_arm_action -n <iface> <flags...>"""
        if not self._arm_action_binary:
            logger.info("g1_arm_action unavailable, skipping: {}", " ".join(flags))
            return
        args = [self._arm_action_binary, *flags]
        logger.info("g1_arm_action: {}", " ".join(args))
        proc = await asyncio.create_subprocess_exec(*args)
        await proc.wait()
        proc = await asyncio.create_subprocess_exec(self._arm_action_binary, "-i", "99")  # reset to default pose after action
        await proc.wait()
        await asyncio.sleep(0.5)  # 增加延时确保动作完成，避免后续动作过快导致机械臂卡顿

    async def _audio_client_exec(self, *flags: str) -> None:
        """Run: g1_audio_client <iface> <content>"""
        if not self._audio_client_binary:
            logger.info("g1_audio_client unavailable, skipping: {}", " ".join(flags))
            return
        args = [self._audio_client_binary, "eth0", *flags]
        logger.info("g1_audio_client: {}", " ".join(args))
        proc = await asyncio.create_subprocess_exec(*args)
        await proc.wait()

    # ── public API ────────────────────────────────────────────────────────────

    async def stop(self) -> None:
        """停止运动（--stop_move）。"""
        await self._loco_client_exec("--stop_move")

    async def damp(self) -> None:
        """进入阻尼模式（--damp）。"""
        await self._loco_client_exec("--damp")

    async def speak(self, content: str) -> None:
        """朗读文本。"""
        await self._audio_client_exec(content)

    async def initialize(self) -> None:
        """进入主运控模式并站立。"""
        await self._loco_client_exec("--damp")  # 先进入阻尼模式确保安全
        await asyncio.sleep(3)  # 等待进入阻尼
        await self._loco_client_exec("--stand_up")
        await asyncio.sleep(5)  # 等待站立完成
        await self._loco_client_exec("--set_fsm_id=501") # 切换到主运控的状态机，允许执行动作

    async def move(self, direction: str, duration: float, speed: float) -> None:
        """向指定方向运动 duration 秒。

        使用 --set_velocity "vx vy omega duration" 一次性传入方向、速度和时长。
        """
        speed = max(0.2, speed)  # 速度过低可能无法启动，设置最低阈值
        vec = _MOVE_VEC.get(direction)
        if vec is None:
            logger.error("Unknown move direction: {}", direction)
            return
        vx = vec[0] * speed
        vy = vec[1] * speed
        omega = vec[2] * speed
        velocity_str = f"{vx} {vy} {omega} {duration}"
        logger.info("move direction={} speed={:.2f} duration={:.1f}s → --set_velocity {!r}",
                    direction, speed, duration, velocity_str)
        await self._loco_client_exec(f'--set_velocity="{velocity_str}"')
        await asyncio.sleep(duration)  # ensure sequential execution of commands with duration

    async def rotate(self, direction: str, duration: float, speed: float) -> None:
        """原地旋转 duration 秒。"""
        speed = max(0.3, speed)  # 旋转时速度过低可能无法启动，设置最低阈值
        vec = _ROTATE_VEC.get(direction)
        if vec is None:
            logger.error("Unknown rotate direction: {}", direction)
            return
        omega = vec[2] * speed
        velocity_str = f"0 0 {omega} {duration}"
        logger.info("rotate direction={} speed={:.2f} duration={:.1f}s → --set_velocity {!r}",
                    direction, speed, duration, velocity_str)
        await self._loco_client_exec(f'--set_velocity="{velocity_str}"')
        await asyncio.sleep(duration)  # ensure sequential execution of commands with duration

    async def perform(self, action_id: str) -> None:
        """执行命名动作。"""
        action = _ALL_ACTIONS.get(action_id)
        if action is None:
            logger.error("Unknown action_id for hardware: {}", action_id)
            return
        logger.info("perform action_id={}", action_id)

        if action_id == "speak":
            content = action.action_params.get("content", "")
            await self.speak(content)
            return

        _id = action.action_params.get("id")
        if "id" in action.action_params:
            _id = action.action_params["id"]
            await self._arm_action_exec("-i", str(_id))
        elif "name" in action.action_params:
            name = action.action_params["name"]
            await self._arm_action_exec("--name", name)
        else:
            logger.error("action_id {} has no 'id' or 'name' param", action_id)

    async def execute_ability(self, actions: list[dict]) -> None:
        """按顺序执行一组动作（ability）。"""
        for action in actions:
            action_id: str = action.get("action_id", "")
            params: dict = action.get("action_params", {})
            speed: float = float(params.get("speed", 0.5))
            duration: float = float(params.get("duration", 1.0))

            if action_id.startswith("move_"):
                await self.move(action_id[len("move_"):], duration, speed)
            elif action_id.startswith("rotate_"):
                await self.rotate(action_id[len("rotate_"):], duration, speed)
            else:
                await self.perform(action_id)


# 全局单例，所有路由共享
loco = LocoClient()
