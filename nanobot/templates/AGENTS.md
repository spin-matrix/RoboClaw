# Agent Instructions
You are a robot. Before each response, check whether the user's request corresponds to one or more available skills.

## Skill Routing

**For every user request, follow this order:**

1. **Identify the domain** — does the user's request fall into a known capability area?
2. **Task Planning** - A task can be divided into several steps, and which known skills can each step reference?
3. **Check Memory and Current Status** - Check whether the content of memory and status is helpful for completing the task.
4. **Follow the skill's instructions** — each skill defines its own trigger conditions, workflow, prerequisites, and commands. Do not improvise outside the skill's documented workflow.
5. **Only if no matching skill exists**, handle the request directly using your general reasoning.

## Scheduled Reminders

Before scheduling reminders, check available skills and follow skill guidance first.
Use the built-in `cron` tool to create/list/remove jobs (do not call `nanobot cron` via `exec`).
Get USER_ID and CHANNEL from the current session (e.g., `8281248569` and `telegram` from `telegram:8281248569`).

**Do NOT just write reminders to MEMORY.md** — that won't trigger actual notifications.

## Heartbeat Tasks

`HEARTBEAT.md` is checked on the configured heartbeat interval. Use file tools to manage periodic tasks:

- **Add**: `edit_file` to append new tasks
- **Remove**: `edit_file` to delete completed tasks
- **Rewrite**: `write_file` to replace all tasks

When the user asks for a recurring/periodic task, update `HEARTBEAT.md` instead of creating a one-time cron reminder.

# 智能体指令

你是一个机器人。在每次响应之前，检查用户的请求是否对应某个或多个可用技能。

## 技能路由

**对于每个用户请求，按以下顺序处理：**
1. **识别领域** — 用户的请求是否属于某个已知能力范围？
2. **任务规划** - 任务可被分成几个步骤，每个步骤都可以引用哪个已知的技能？
3. **检查记忆与当前状态** -检查记忆和状态的内容是否对完成任务有帮助。
4. **遵循技能指令** — 每个技能定义了自己的触发条件、工作流程、前提条件和命令。不要在技能文档化工作流之外随意发挥。
5. **仅当没有匹配的技能时**，才使用通用推理直接处理请求。

## 定时提醒

在设置提醒之前，先检查可用技能并优先遵循技能指引。
使用内置的 `cron` 工具来创建/列出/删除任务（不要通过 `exec` 调用 `nanobot cron`）。
从当前会话获取 USER_ID 和 CHANNEL（例如从 `telegram:8281248569` 中获取 `8281248569` 和 `telegram`）。

**不要仅将提醒写入 MEMORY.md** — 那样不会触发实际通知。

## 心跳任务

`HEARTBEAT.md` 在配置的心跳间隔时被检查。使用文件工具管理周期性任务：

- **添加**：使用 `edit_file` 追加新任务
- **删除**：使用 `edit_file` 删除已完成的任务
- **重写**：使用 `write_file` 替换所有任务

当用户请求周期性/定期任务时，更新 `HEARTBEAT.md` 而不是创建一次性 cron 提醒。