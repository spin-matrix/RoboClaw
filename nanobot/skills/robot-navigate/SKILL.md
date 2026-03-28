---
name: robot-navigate
description: Navigate the robot to predefined goal locations.（将机器人导航至预定义目标位置。）
metadata: {"nanobot":{"emoji":"🧭"}}
---

# Robot Navigate

Navigate the robot to predefined goal locations, and record new goals.


## Overview

This skill covers the full robot navigation lifecycle, comprising four sub-functions with the following execution order:

```
Mapping → Pose Initialization → Mark Waypoints (repeatable) → Navigate
```

Get SLAM State can be called at any time to query the current system state.

All underlying scripts live in `{baseDir}/scripts/`.

---

# Motion Availability Check [DO NOT SKIP!]
BEFORE executing any motion-related command:
    1. Run: `curl -s http://localhost:18790/api/home/status | jq '.data.available | any(. == "运动")'`
    2. If the output is `false`: STOP and tell the user "Motion mode is not enabled"
    4. If found: Proceed with the motion command
DO NOT skip this check. DO NOT execute motion commands without verification.


## Sub-function 1: Mapping

**Trigger:** The user asks the robot to map a new environment, or the existing map needs to be rebuilt.

**Workflow:**

1. Capture the current camera frame.

2. Inform the user: "Mapping is about to begin. Are you ready?"

3. Wait for the user to confirm they are ready.

4. Start mapping:
```bash
   uv run {baseDir}/scripts/build_map.py start
```

5. Inform the user: "Mapping has started. Please use the remote control to drive the robot in a complete loop around the area to be mapped. Let me know when you are done."

6. Wait for the user to confirm the robot has completed the loop.

7. End mapping:
```bash
   uv run {baseDir}/scripts/build_map.py end
```

8. Inform the user that mapping is complete and they can proceed to pose initialization.
```

---

## Sub-function 2: Pose Initialization (Relocation)

**Trigger:** After mapping is complete and before first use of navigation, or when the robot has lost its position and needs to relocalize.

**Workflow:**

1. Capture the current camera frame。

2. Start relocation:
```bash
   uv run {baseDir}/scripts/init_pose.py eth0
```

3. Read the returned result:
   - `statusCode == 0` → `initialized` is saved as `true` in `slam_state.json`. Inform the user that initialization succeeded.
   - `statusCode != 0` → Inform the user: "The robot is not within the mapped area. Please move the robot back into the mapped area and try again." Do not proceed with any navigation operations.

---

## Sub-function 3: Mark Navigation Waypoint

**Trigger:** The user says "I want to add a new navigation waypoint" or similar.

**Prerequisite:** Pose initialization (sub-function 2) must have been completed. If not, prompt the user to run initialization first.

This sub-function involves a multi-turn dialogue, as follows:
```
1. Capture the current camera frame。

2. Robot replies:
   "Please make sure you are within the mapped area, then use the remote
    control to drive the robot to the position you want to mark. Let me
    know when you are done."

3. Wait for the user to confirm (e.g. "Done", "I've marked it", "OK", etc.).

4. Robot replies:
   "Please give this waypoint a name."

5. Wait for the user to provide a name (e.g. "fridge").

6. Record the waypoint:

   uv run {baseDir}/scripts/record_goal.py <goal_name>

7. Read the returned result:
   - Outputs "已保存目标点: <name>" → Inform the user the waypoint was saved,
     e.g. "The current position has been marked as 'fridge'."
   - Outputs "获取当前位置失败" → Inform the user that marking failed.
```

---

## Sub-function 4: Navigate

**Trigger:** The user asks the robot to go to a previously marked waypoint.

**Workflow:**

1. Check prerequisites — get current SLAM state:
```bash
   cat {baseDir}/scripts/slam_state.json
```

   Confirm `has_map == true` and `initialized == true`. If any condition is not met → Inform the user which prerequisite is missing.

2. Check target waypoint — list available goals:
```bash
   uv run {baseDir}/scripts/nav_to_goal.py --list
```

   Confirm the target waypoint is in the returned list. If not → Inform the user the waypoint does not exist.

3. Capture the current camera frame。

4. Start navigation:
```bash
   uv run {baseDir}/scripts/nav_to_goal.py --target <goal_name>
```

5. Read the returned result:
   - Outputs "已到达" / `is_arrived: true` → Inform the user the robot has arrived at the target.
   - Navigation fails → Report failure and reason to the user.

6. **Collision handling** (built into `nav_to_goal.py`):
   - Pause navigation → Query obstacle service → If clear: advance and resume; if blocked: turn 90° and retry.
   - If all four directions are blocked: report failure to the user.

---

## Sub-function 5: Get SLAM State

**Trigger:** Whenever the current navigation system state needs to be queried, or as a prerequisite check before executing navigation.

**Workflow:**

1. Capture the current camera frame。

2. Get SLAM state and goal list:
```bash
   cat {baseDir}/scripts/slam_state.json
   uv run {baseDir}/scripts/nav_to_goal.py --list
```

3. Report the current navigation system state to the user.

**State fields in `slam_state.json`:**

| Field | Description |
|---|---|
| `has_map` | Whether a map has been built |
| `initialized` | Whether pose initialization has been completed |
| `current_goal` | The goal the robot is currently navigating to (if any) |

---

## Sub-function 6: Delete Current Map

**Trigger:** The user asks to delete the current map, clear all navigation data, or start fresh.

**Workflow:**

1. Warn the user:
   "This will permanently delete the current map and all saved waypoints. Are you sure you want to continue?"

2. Wait for the user to confirm.

3. Delete the map state and waypoint files:
```bash
rm -f {baseDir}/scripts/slam_state.json
rm -f {baseDir}/scripts/poses.json
```

4. Read the result:
   - Both files deleted successfully → Inform the user: "The current map and all waypoints have been deleted. You will need to run Mapping and Pose Initialization before navigating again."
   - Deletion fails (e.g. permission error) → Report the error to the user and do not proceed.

## Notes

- Do not rewrite any output prefix format.
- The waypoint marking flow must follow the full multi-turn dialogue. Do not skip user confirmation steps and call the underlying script directly.
- If relocation fails, the user must be prompted to manually move the robot back into the mapped area. Do not retry automatically.
- Navigation is autonomous — the robot will plan a path and move to the goal on its own, with automatic collision avoidance (pause, check obstacles, turn or advance, resume).
- Use `record_goal.py` to save the robot's current position as a new named goal, with the goal stored in `{baseDir}/scripts/poses.json`.
- Use `--list` to dynamically view all available goals from `poses.json`.

---

---
name: robot-navigate
description: 将机器人导航至预定义目标位置。
metadata: {"nanobot":{"emoji":"🧭"}}
---

# 机器人导航

将机器人导航至预定义目标位置，并记录新的目标点。

## 前置条件

在执行以下所有子功能前，先检查运动模式是否已启用：
```bash
curl http://localhost:18790/api/home/status | jq .data.available
```
返回值应包含 `"运动"`，例如：
```json
["对话", "视觉识别", "运动"]
```
若列表中没有 `"运动"`，说明运动模式未开启，请告知用户："**请先开启运动模式**"，不要继续执行后续命令。

## 概述

本技能涵盖完整的机器人导航生命周期，由四个子功能组成，执行顺序如下：
```
建图 → 位置初始化 → 标记目标点（可重复）→ 导航
```

获取 SLAM 状态可在任意时刻调用，用于查询当前系统状态。

所有底层脚本位于 `{baseDir}/scripts/` 目录下。

---

# 运动可用性检查[不要跳过！]
在执行任何运动相关命令之前：
    1. 运行：`curl -s http://localhost:18790/api/home/status | jq '.data.available | any(. == "运动")'`
    2. 如果输出为 `false`：立即停止并告知用户"运动模式未启用"
    3. 如果输出为 `true`：继续执行运动命令

不要跳过此检查。未经验证不要执行运动命令。


## 子功能 1：建图

**触发条件：** 用户要求机器人对新环境建图，或现有地图需要重建。

**工作流程：**

1. 采集当前摄像头帧。

2. 告知用户："建图即将开始，请问您准备好了吗？"

3. 等待用户确认已准备好。

4. 开始建图：
```bash
   uv run {baseDir}/scripts/build_map.py start
```

5. 告知用户："建图已开始，请使用遥控器驾驶机器人绕待建图区域完整行驶一圈，完成后请告知我。"

6. 等待用户确认机器人已完成绕行。

7. 结束建图：
```bash
   uv run {baseDir}/scripts/build_map.py end
```

8. 告知用户建图已完成，可继续进行位置初始化。
```
---

## 子功能 2：位置初始化（重定位）

**触发条件：** 建图完成后首次使用导航前，或机器人丢失位置需要重新定位时。

**工作流程：**

1. 采集当前摄像头帧。

2. 开始重定位：
```bash
   uv run {baseDir}/scripts/init_pose.py eth0
```

3. 读取返回结果：
   - `statusCode == 0` → `slam_state.json` 中 `initialized` 已保存为 `true`。告知用户初始化成功。
   - `statusCode != 0` → 告知用户："机器人不在已建图区域内。请将机器人移回已建图区域后重试。" 不得继续执行任何导航操作。

---

## 子功能 3：标记导航目标点

**触发条件：** 用户说"我想添加一个新的目标点"或类似表述。

**前提条件：** 必须已完成位置初始化（子功能 2）。若未完成，提示用户先执行初始化。

本子功能涉及多轮对话，流程如下：
```
1. 采集当前摄像头帧。

2. 机器人回复：
   "请确保您在已建图区域内，然后使用遥控器将机器人驾驶至您想要标记的位置。完成后请告知我。"

3. 等待用户确认（例如"完成了"、"我标好了"、"好的"等）。

4. 机器人回复：
   "请为该路径点命名。"

5. 等待用户提供名称（例如"冰箱"）。

6. 记录路径点：
```bash
uv run {baseDir}/scripts/record_goal.py <目标名称>
```
示例：
将当前位置记录为"厨房"：
```bash
uv run {baseDir}/scripts/record_goal.py 厨房
```

7. 读取返回结果：
   - 输出"已保存目标点: <name>" → 告知用户路径点已保存，
     例如："当前位置已标记为'冰箱'。"
   - 输出"获取当前位置失败" → 告知用户标记失败。
```

---

## 子功能 4：导航

**触发条件：** 用户要求机器人前往之前标记的路径点。

**工作流程：**

1. 检查前提条件 — 获取当前 SLAM 状态：
```bash
cat {baseDir}/scripts/slam_state.json
```

   确认 `has_map == true` 且 `initialized == true`。若任一条件不满足 → 告知用户缺少哪项前提条件。

2. 检查目标路径点 — 列出可用目标点：
```bash
uv run {baseDir}/scripts/nav_to_goal.py --list
```

   确认目标路径点在返回列表中。若不存在 → 告知用户该路径点不存在。

3. 采集当前摄像头帧。

4. 开始导航：
```bash
uv run {baseDir}/scripts/nav_to_goal.py --target <目标名称>
```
示例：
导航至客厅：
```bash
uv run {baseDir}/scripts/nav_to_goal.py -t 客厅
```

5. 读取返回结果：
   - 输出"已到达" / `is_arrived: true` → 告知用户机器人已到达目标位置。
   - 导航失败 → 向用户报告失败原因（`message` 字段内容）。

6. **碰撞处理**（内置于 `nav_to_goal.py` 中）：
   - 暂停导航 → 查询障碍物服务 → 若通畅：前进并恢复；若受阻：旋转 90° 后重试。
   - 若四个方向均被阻挡：向用户报告失败。

---

## 子功能 5：获取 SLAM 状态

**触发条件：** 任何需要查询当前导航系统状态时，或作为执行导航前的前提条件检查。

**工作流程：**

1. 采集当前摄像头帧。

2. 获取 SLAM 状态和目标点列表：
```bash
cat {baseDir}/scripts/slam_state.json
uv run {baseDir}/scripts/nav_to_goal.py --list
```

3. 向用户报告当前导航系统状态。

**`slam_state.json` 中的状态字段：**

| 字段 | 描述 |
|---|---|
| `has_map` | 是否已建图 |
| `initialized` | 是否已完成位姿初始化 |
| `current_goal` | 机器人当前正在导航的目标点（如有） |

---

## 子功能 6：删除当前建图

**触发条件：** 用户要求删除当前地图、清除所有导航数据，或希望重新开始建图。

**工作流程：**

1. 警告用户：
   "此操作将永久删除当前地图及所有已保存的目标点，是否确认继续？"

2. 等待用户确认。

3. 删除地图状态文件和目标点文件：
```bash
rm -f {baseDir}/scripts/slam_state.json
rm -f {baseDir}/scripts/poses.json
```

4. 读取执行结果：
   - 两个文件均成功删除 → 告知用户："当前地图及所有目标点已删除。如需再次导航，请重新执行建图和位置初始化。"
   - 删除失败（如权限不足）→ 向用户报告错误，不得继续执行后续操作。

## 注意事项

- 不得重写任何输出前缀格式。
- 目标点标记流程必须遵循完整的多轮对话。不得跳过用户确认步骤直接调用底层脚本。
- 若重定位失败，必须提示用户手动将机器人移回已建图区域，不得自动重试。
- 导航为自主执行 — 机器人将自动规划路径并移动至目标位置，具备自动避障功能（暂停、检测障碍物、转向或前进、恢复）。
- 使用 `record_goal.py` 将机器人当前位置保存为新的命名目标，目标存储于 `{baseDir}/scripts/poses.json`。
- 使用 `--list` 可从 `poses.json` 动态查看所有可用目标。
