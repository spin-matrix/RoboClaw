---
name: robot-grasp
description: Control robot grasping actions — grasp objects, retract arms, and handover items via scripts.（控制机器人抓取动作 — 通过演示脚本抓取物体、收回手臂及向用户递交物品。）
metadata: {"nanobot":{"emoji":"🦾","requires":{"bins":["python"]}}}
---

# Robot Grasp

Control the robot's manipulation capabilities, including object grasping, arm retraction, and handing over items to users.


# Motion Availability Check [DO NOT SKIP!]
BEFORE executing any motion-related command:
    1. Run: `curl -s http://localhost:18790/api/home/status | jq '.data.available | any(. == "运动")'`
    2. If the output is `false`: STOP and tell the user "Motion mode is not enabled"
    4. If found: Proceed with the motion command
DO NOT skip this check. DO NOT execute motion commands without verification.


## Scope of Application
Before performing the grasp, the object list in `{baseDir}/objects.txt` **must** be read first.
- If the target object **is in the list** → proceed with the grasp process
- If the target object **is not in the list** → directly inform the user that "the current object cannot be graspped" and abort the operation


## Command Format

All commands should be executed from the `{baseDir}/scripts/` directory using the specific uv environment Python interpreter.
```bash
cd {baseDir}/scripts/ && uv run [script_name].py [argument]
```

## Core Actions

### 1. Grasp Object

Grasp a specific item on a surface based on its class name.
* Script: `grasp.py`
* Arguments: `object_name` (e.g., apple, bottle, orange)
Example:
```bash
cd {baseDir}/scripts/ && uv run grasp.py apple
```

### 2. Retract Arm

Retract the specified arm after performing a grasp.
* Script: `retract.py`
* Arguments: `left` or `right`

Example (Retract Right Arm):
```bash
cd {baseDir}/scripts/ && uv run retract.py right
```

### 3. Handover

Identify a user and hand over the item held in the specified hand.
* Script: `handover.py`
* Arguments: `left` or `right`

Example (Handover from Left Hand):
```bash
cd {baseDir}/scripts/ && uv run handover.py left
```

## Execution Results

The scripts will return a text output. Successful execution is indicated by a string starting with `[Unitree]`.

Example:
* Success: "[Unitree] Grasp success: Use right hand"
* Success: "[Unitree] Handover success"
* Failure: Returns detailed error messages without the success prefix.

## Safety and Operational Notes

* **Object Recognition**: Before performing the `grasp` action, ensure that the target object is clearly visible in the robot's camera field of view. If the object is not visible, navigate to the location of the object first.If the user specifies going to a specific location to pick up an object, it is also necessary to first determine whether the object exists.
* **Workspace Safety**: Ensure no humans or fragile obstacles are within the arm's reach during `retract` or `handover` motions.
* **Sequential Logic**: It is recommended to call `retract` after a `grasp` to ensure the robot returns to a stable posture before moving.

---
name: robot-grasp
description: 控制机器人抓取动作 — 通过演示脚本抓取物体、收回手臂及向用户递交物品。
metadata: {"nanobot":{"emoji":"🦾","requires":{"bins":["python"]}}}
---

# 机器人抓取

控制机器人的操控能力，包括物体抓取、手臂收回以及向用户递交物品。

# 运动可用性检查[不要跳过！]
在执行任何运动相关命令之前：
    1. 运行：`curl -s http://localhost:18790/api/home/status | jq '.data.available | any(. == "运动")'`
    2. 如果输出为 `false`：立即停止并告知用户"运动模式未启用"
    3. 如果输出为 `true`：继续执行运动命令

不要跳过此检查。未经验证不要执行运动命令。

## 适用范围
在执行抓取之前，**必须**先读取`{baseDir}/objects.txt`中的物体列表。
- 若目标物体**在列表中** → 继续执行抓取流程
- 若目标物体**不在列表中** → 直接告知用户"当前物体不可抓取"，中止操作

## 命令格式

所有命令须在 `{baseDir}/scripts/` 目录下，使用指定 uv 环境的 Python 解释器执行。
```bash
cd {baseDir}/scripts/ && uv run [script_name].py [argument]
```

## 核心动作

### 1. 抓取物体

根据类别名称抓取表面上的特定物品。
* 脚本：`grasp.py`
* 参数：`object_name`（例如，苹果、瓶子、橙子）
示例：
```bash
cd {baseDir}/scripts/ && uv run grasp.py apple
```

### 2. 收回手臂

抓取完成后收回指定手臂。
* 脚本：`retract.py`
* 参数：`left`（左）或 `right`（右）

示例（收回右臂）：
```bash
cd {baseDir}/scripts/ && uv run retract.py right
```

### 3. 递交物品

识别用户并将指定手中持有的物品递交给用户。
* 脚本：`handover.py`
* 参数：`left`（左）或 `right`（右）

示例（从左手交接）：
```bash
cd {baseDir}/scripts/ && uv run handover.py left
```

## 执行结果
脚本将返回文本输出。执行成功的标识为以`[Unitree]`开头的字符串。

示例：
* 成功："[Unitree] 抓取成功：使用右手"
* 成功："[Unitree] 交接成功"
* 失败：返回不含成功前缀的详细错误信息

## 安全与操作注意事项


* **物体识别**：在执行 `grasp` 动作前，确保目标物体在机器人摄像头视野中清晰可见，如果物体不可见需要先导航至物体所在处。若用户指定去某个具体位置拿取物体，也需要先判断物体是否存在。
* **工作区安全**：在执行 `retract` 或 `handover` 动作期间，确保手臂活动范围内没有人员或易碎障碍物。
* **顺序逻辑**：建议在 `grasp` 之后调用 `retract`，以确保机器人在移动前恢复稳定姿态。
