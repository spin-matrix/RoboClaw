---
name: robot-move
description: Control robot locomotion — move, rotate, and stop via g1_loco_client.（控制机器人运动——通过g1_loco_client实现移动、旋转和停止操作。）
metadata: {"nanobot":{"emoji":"🤖","requires":{"bins":["g1_loco_client"]}}}
---

# Robot Move

Control the robot's movement and rotation using `g1_loco_client`.
When moving forward, first check security status via api call
`curl -LsSf http://localhost:18790/api/controller/external`
and ensure the response contains `"safe": true` before issuing
 forward movement commands.

# Motion Availability Check [DO NOT SKIP!]
BEFORE executing any motion-related command:
    1. Run: `curl -s http://localhost:18790/api/home/status | jq '.data.available | any(. == "运动")'`
    2. If the output is `false`: STOP and tell the user "Motion mode is not enabled"
    4. If found: Proceed with the motion command
DO NOT skip this check. DO NOT execute motion commands without verification.

## Command format

```bash
g1_loco_client --network_interface=eth0 --set_velocity="vx vy omega duration"
```

Parameters:
- **vx** — forward/backward speed (m/s). Positive = forward, negative = backward.
- **vy** — left/right speed (m/s). Positive = left, negative = right.
- **omega** — rotational speed (rad/s). Positive = turn left, negative = turn right.
- **duration** — (optional) how long the motion lasts in seconds. If omitted, default value is 1s.

## Common examples

Check safety status before moving forward:
```bash
curl -LsSf http://localhost:18790/api/controller/external
```
If the response contains `"safe": true`, then it's safe to move forward.

Move forward at 0.5 m/s for 2 seconds:
```bash
g1_loco_client --network_interface=eth0 --set_velocity="0.5 0 0 2"
```

Move backward at 0.3 m/s for 1.5 seconds:
```bash
g1_loco_client --network_interface=eth0 --set_velocity="-0.3 0 0 1.5"
```

Strafe left at 0.3 m/s for 1 second:
```bash
g1_loco_client --network_interface=eth0 --set_velocity="0 0.3 0 1"
```

Strafe right at 0.3 m/s for 1 second:
```bash
g1_loco_client --network_interface=eth0 --set_velocity="0 -0.3 0 1"
```

Rotate left (counter-clockwise) at 0.5 rad/s for 2 seconds:
```bash
g1_loco_client --network_interface=eth0 --set_velocity="0 0 0.5 2"
```

Rotate right (clockwise) at 0.5 rad/s for 2 seconds:
```bash
g1_loco_client --network_interface=eth0 --set_velocity="0 0 -0.5 2"
```

Move forward while turning left:
```bash
g1_loco_client --network_interface=eth0 --set_velocity="0.4 0 0.3 3"
```

## Stop and other modes

Stop all movement:
```bash
g1_loco_client --network_interface=eth0 --stop_move
```

## Safety notes

- Keep speeds low (0.2–0.5 m/s) in confined spaces.
- Always issue `--stop_move` if the robot needs to halt immediately.
- Use short durations (1–3s) and chain commands rather than issuing a single long movement.

---
name: robot-move
description: 控制机器人运动——通过g1_loco_client实现移动、旋转和停止操作。
metadata: {"nanobot":{"emoji":"🤖","requires":{"bins":["g1_loco_client"]}}}
---

# 机器人移动
使用`g1_loco_client`控制机器人的移动与旋转。
在向前移动之前，通过API调用
`curl -LsSf http://localhost:18790/api/controller/external`检查安全状态，
并确保响应中包含`"safe": true`，然后再发出向前移动的命令。

# 运动可用性检查[不要跳过！]
在执行任何运动相关命令之前：
    1. 运行：`curl -s http://localhost:18790/api/home/status | jq '.data.available | any(. == "运动")'`
    2. 如果输出为 `false`：立即停止并告知用户"运动模式未启用"
    3. 如果输出为 `true`：继续执行运动命令

不要跳过此检查。未经验证不要执行运动命令。

## 命令格式
```bash
g1_loco_client --network_interface=eth0 --set_velocity="线速度x 线速度y 角速度 持续时间"
```

参数说明：
- **线速度x（vx）** — 前后移动速度（米/秒）。正值为向前，负值为向后。
- **线速度y（vy）** — 左右平移速度（米/秒）。正值为向左，负值为向右。
- **角速度（omega）** — 旋转速度（弧度/秒）。正值为左转，负值为右转。
- **持续时间（duration）** — （可选）运动持续的秒数。若省略，默认值为1秒。

## 常用示例

检查安全状态后再向前移动：
```bash
curl -LsSf http://localhost:18790/api/controller/external
```
如果响应中包含`"safe": true`，则可以安全地向前移动。

以0.5米/秒的速度向前移动2秒：
```bash
g1_loco_client --network_interface=eth0 --set_velocity="0.5 0 0 2"
```

以0.3米/秒的速度向后移动1.5秒：
```bash
g1_loco_client --network_interface=eth0 --set_velocity="-0.3 0 0 1.5"
```

以0.3米/秒的速度向左平移1秒：
```bash
g1_loco_client --network_interface=eth0 --set_velocity="0 0.3 0 1"
```

以0.3米/秒的速度向右平移1秒：
```bash
g1_loco_client --network_interface=eth0 --set_velocity="0 -0.3 0 1"
```

以0.5弧度/秒的速度向左（逆时针）旋转2秒：
```bash
g1_loco_client --network_interface=eth0 --set_velocity="0 0 0.5 2"
```

以0.5弧度/秒的速度向右（顺时针）旋转2秒：
```bash
g1_loco_client --network_interface=eth0 --set_velocity="0 0 -0.5 2"
```

向前移动同时左转：
```bash
g1_loco_client --network_interface=eth0 --set_velocity="0.4 0 0.3 3"
```

## 停止及其他模式
停止所有运动：
```bash
g1_loco_client --network_interface=eth0 --stop_move
```

## 安全注意事项
- 在狭窄空间内保持低速（0.2–0.5米/秒）。
- 若需机器人立即停止，务必执行`--stop_move`指令。
- 使用短持续时间（1–3秒）并链式发送指令，而非单次发送长时运动指令。
