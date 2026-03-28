---
name: robot-action
description: Control Unitree G1 robot arm actions — list, execute by ID, or execute by name via g1_arm_action.（控制机器人手臂动作 — 通过 g1_arm_action 列出动作、按 ID 执行或按名称执行。）
metadata: {"nanobot":{"emoji":"💪","requires":{"bins":["g1_arm_action"]}}}
---

# Robot Action

Control robot's arm actions.


# Motion Availability Check[DO NOT SKIP!]
BEFORE executing any motion-related command:
    1. Run: `curl -s http://localhost:18790/api/home/status | jq '.data.available | any(. == "运动")'`
    2. If the output is `false`: STOP and tell the user "Motion mode is not enabled"
    4. If found: Proceed with the motion command
DO NOT skip this check. DO NOT execute motion commands without verification.

## API Reference

| Action | Method | Endpoint | Body |
|---|---|---|---|
| List available actions | `g1_arm_action -l` | — | — |
| Execute action by ID | `g1_arm_action -i <action_id>` | — | — |
| Execute action by name | `g1_arm_action --name <action_name>` | — | — |

### List available actions
```bash
g1_arm_action -l
```

Shows all available arm actions with their IDs and names.

### Execute action by ID
```bash
g1_arm_action -i <action_id>
```

Execute a predefined action by its numeric ID. Use `-l` first to discover available IDs.

### Execute action by name
```bash
g1_arm_action --name <action_name>
```

Execute a complex action by its name. Use `-l` first to discover available names.

## Usage guidelines

- Always do the motion availability check first. If motion mode is enabled, then run `g1_arm_action -l` to check available actions before executing.
- Prefer `-i <action_id>` for simple predefined actions.
- Use `--name <action_name>` for complex or composite actions.
- When the user describes a desired arm gesture or pose, list available actions first, then pick the closest match.
- **Grasping/placing objects is not within the scope of this skill.** If a user requests to grasp, pick up, or place an object, please use the `robot-grasp` skill.

---
name: robot-action
description: 控制机器人手臂动作 — 通过 g1_arm_action 列出动作、按 ID 执行或按名称执行。
metadata: {"nanobot":{"emoji":"💪","requires":{"bins":["g1_arm_action"]}}}
---

# 机器人动作

控制机器人的手臂动作。

# 运动可用性检查[不要跳过！]
在执行任何运动相关命令之前：
    1. 运行：`curl -s http://localhost:18790/api/home/status | jq '.data.available | any(. == "运动")'`
    2. 如果输出为 `false`：立即停止并告知用户"运动模式未启用"
    3. 如果输出为 `true`：继续执行运动命令

不要跳过此检查。未经验证不要执行运动命令。


### 列出可用动作
```bash
g1_arm_action -l
```

显示所有可用的手臂动作及其 ID 和名称。

### 按 ID 执行动作
```bash
g1_arm_action -i <action_id>
```

通过数字 ID 执行预定义动作。请先用 -l 查看可用 ID。

### 按名称执行动作
```bash
g1_arm_action --name <action_name>
```

通过名称执行复杂动作。请先用 -l 查看可用名称。

## 使用指南

- 在执行动作之前，务必先进行运动可用性检查。确认运动模式开启后，调用 `g1_arm_action -l` 检查可用动作。
- 对于简单的预定义动作，优先使用 `-i <action_id>`。
- 对于复杂或组合动作，使用 `--name <action_name>`。
- 当用户描述所需的手臂姿势或动作时，先列出可用动作，再选择最接近的匹配项。
- **抓取/放置物体不属于本 skill 的范围。** 如果用户要求抓取、拾取、放下物体，请使用 `robot-grasp` skill。
