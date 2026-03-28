# Tool Usage Notes

Tool signatures are provided automatically via function calling.
This file documents non-obvious constraints and usage patterns.

## exec — Safety Limits

- Commands have a configurable timeout (default 60s)
- Dangerous commands are blocked (rm -rf, format, dd, shutdown, etc.)
- Output is truncated at 10,000 characters
- `restrictToWorkspace` config can limit file access to the workspace

## cron — Scheduled Reminders

- Please refer to cron skill for usage.

# 工具使用说明

工具签名通过函数调用自动提供。
本文件记录了一些不易察觉的约束条件和使用模式。

## exec — 安全限制

- 命令有可配置的超时时间（默认 60 秒）
- 危险命令会被拦截（如 rm -rf、format、dd、shutdown 等）
- 输出内容截断上限为 10,000 个字符
- `restrictToWorkspace` 配置可将文件访问限制在工作区范围内

## cron — 定时提醒

- 请参阅 cron 技能以了解用法。