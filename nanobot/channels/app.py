"""App channel — HTTP API channel served through the gateway server."""

from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass, field as dc_field
from typing import Any

from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base
from nanobot.providers.base import LLMProvider
# from text_cleaner.clean import TextCleaner

_HINT_SUMMARY_PROMPT = "用不超过10个字概括这个工具调用在做什么，只输出概括内容，不要任何额外文字。坚决不允许输出工具调用的参数或细节，不允许输出代码，只概括它的目的或作用。"
_HINT_SUMMARY_TIMEOUT = 5  # seconds
_DEFAULT_TOOL_HINTS = [
    "正在调用工具",
    "思考中",
    "处理中",
    "正在操作",
    "稍等一下",
    "正在执行",
    "工作中",
    "请稍候",
]

# Regex to strip markdown formatting and emoji from text before TTS
_MD_PATTERN = re.compile(
    r"```[\s\S]*?```"       # fenced code blocks
    r"|`[^`]*`"             # inline code
    r"|!\[[^\]]*\]\([^)]*\)"  # images
    r"|\[[^\]]*\]\([^)]*\)"   # links → keep text handled below
    r"|[*_~`#>|]+"          # emphasis, headings, blockquotes, etc.
    r"|\-{3,}"              # horizontal rules
)
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002702-\U000027B0"  # dingbats
    "\U00002600-\U000026FF"  # misc symbols
    "\U000024C2"             # circled M
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero width joiner
    "\U000020E3"             # combining enclosing keycap
    "\U00002934-\U00002935"  # arrows
    "\U000023E9-\U000023FA"  # media control symbols
    "\U0000200B"             # zero width space
    "\U00003030\U000025AA\U000025AB\U000025FE\U000025FD"
    "]+",
    flags=re.UNICODE,
)


# def _strip_for_tts(text: str) -> str:
#     """Remove markdown symbols and emoji so TTS reads clean text."""
#     # Replace links [text](url) with just text
#     text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
#     text = _MD_PATTERN.sub("", text)
#     text = _EMOJI_PATTERN.sub("", text)
#     # Collapse whitespace
#     text = re.sub(r"\n{2,}", "\n", text).strip()
#     text = text.replace("\n", " ")  # TTS may read newlines as "new line"
#     return text

# cleaner = TextCleaner()

# def _strip_for_tts(text: str) -> str:
#     print(text)
#     return cleaner.clean(text)


class AppConfig(Base):
    """App channel configuration — HTTP API served through the gateway."""

    enabled: bool = True
    allow_from: list[str] = Field(default_factory=lambda: ["*"])  # Allowed sender IDs


# ---------------------------------------------------------------------------
# /config interactive flow — state machine
# ---------------------------------------------------------------------------

@dataclass
class _ConfigSession:
    """Tracks the state of an interactive /config session for one chat."""

    state: str = "select_provider"  # select_provider | input_api_key | ask_continue | input_model
    provider_specs: list[Any] = dc_field(default_factory=list)  # cached configurable ProviderSpecs
    selected_provider_name: str = ""  # e.g. "anthropic"


def _get_configurable_providers():
    """Return provider specs that accept an API key (not OAuth, not local-only)."""
    from nanobot.providers.registry import PROVIDERS
    return [s for s in PROVIDERS if not s.is_oauth and not s.is_local and not s.is_direct]


def _build_provider_list(specs) -> str:
    """Build a numbered list of providers for display."""
    lines = ["请选择要配置的 Provider（输入序号）：\n"]
    lines.append("  0. 取消配置")
    for i, spec in enumerate(specs, 1):
        lines.append(f"  {i}. {spec.label}")
    return "\n".join(lines)


class AppChannel(BaseChannel):
    """HTTP API channel for client apps, driven by the gateway server."""

    name = "app"
    display_name = "App"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return AppConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = AppConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: AppConfig = config
        # Per-chat response queues: chat_id -> asyncio.Queue[OutboundMessage]
        self._response_queues: dict[str, asyncio.Queue[OutboundMessage]] = {}
        self._tool_hints: dict[str, str] = {}  # chat_id -> str
        self._hint_provider: LLMProvider | None = None
        self._hint_model: str | None = None
        # Per-chat /config interactive sessions
        self._config_sessions: dict[str, _ConfigSession] = {}

    async def start(self) -> None:
        """Mark the channel as running. HTTP requests are handled by the gateway."""
        self._running = True
        logger.info("App channel started (HTTP API via gateway)")

    async def stop(self) -> None:
        """Stop the channel."""
        self._running = False
        self._response_queues.clear()
        self._tool_hints.clear()

    async def send(self, msg: OutboundMessage) -> None:
        """Store an outbound message so the HTTP API can deliver it."""
        if msg.metadata.get("_tool_hint"):
            summary = await self._summarize_tool_hint(msg.content)
            logger.info("Storing tool hint for chat_id={}: {}", msg.chat_id, summary)
            msg.content = summary
            self._tool_hints[msg.chat_id] = summary
        else:
            self._tool_hints.pop(msg.chat_id, None)

        # Speak final messages through the robot speaker
        # if not msg.metadata.get("_progress", False) and not msg.metadata.get("_tool_hint"):
        #     clean_text = _strip_for_tts(msg.content)
        #     if clean_text:
        #         logger.debug("Sending text to TTS: {}", clean_text)
        #         asyncio.create_task(self._speak(clean_text))

        queue = self._response_queues.get(msg.chat_id)
        if queue is not None:
            await queue.put(msg)
        else:
            logger.warning("App channel: no listener for chat_id={}", msg.chat_id)

    def _get_hint_provider(self) -> tuple[LLMProvider, str]:
        """Lazily build a provider for tool-hint summarization."""
        if self._hint_provider is not None:
            return self._hint_provider, self._hint_model  # type: ignore[return-value]

        from nanobot.cli.commands import _make_provider
        from nanobot.config import load_config

        cfg = load_config()
        self._hint_provider = _make_provider(cfg)
        self._hint_model = cfg.agents.defaults.model
        return self._hint_provider, self._hint_model

    async def _summarize_tool_hint(self, raw_hint: str) -> str:
        """Call LLM to summarize a tool-call string into ≤10 chars."""
        if not raw_hint or not raw_hint.strip():
            return raw_hint
        try:
            provider, model = self._get_hint_provider()
            resp = await asyncio.wait_for(
                provider.chat_with_retry(
                    messages=[
                        {"role": "system", "content": _HINT_SUMMARY_PROMPT},
                        {"role": "user", "content": raw_hint},
                    ],
                    model=model,
                    reasoning_effort="none",
                ),
                timeout=_HINT_SUMMARY_TIMEOUT,
            )
            logger.debug("Tool hint summarization response: {}", resp.content)
            summary = (resp.content or "").strip()
            return summary if summary else random.choice(_DEFAULT_TOOL_HINTS)
        except Exception:
            logger.debug("Tool hint summarization failed, using default hint")
            return random.choice(_DEFAULT_TOOL_HINTS)

    async def _speak(self, text: str) -> None:
        """Send text to the robot speaker via unitree_g1."""
        try:
            from nanobot.gateway.unitree_g1 import loco
            await loco.speak(text)
        except Exception:
            logger.debug("TTS speak failed, ignoring")

    def get_response_queue(self, chat_id: str) -> asyncio.Queue[OutboundMessage]:
        """Get or create a response queue for a chat_id."""
        if chat_id not in self._response_queues:
            self._response_queues[chat_id] = asyncio.Queue()
        return self._response_queues[chat_id]

    def get_tool_hint(self, chat_id: str) -> str | None:
        """Get the current tool hint for a chat_id."""
        return self._tool_hints.get(chat_id)

    def remove_response_queue(self, chat_id: str) -> None:
        """Remove the response queue for a chat_id."""
        self._response_queues.pop(chat_id, None)

    async def handle_api_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Handle an incoming message from the HTTP API."""
        text = content.strip()

        # Enter config mode
        if text == "/config":
            session = _ConfigSession()
            session.provider_specs = _get_configurable_providers()
            session.state = "select_provider"
            self._config_sessions[chat_id] = session
            await self._config_reply(chat_id, _build_provider_list(session.provider_specs))
            return

        # Forget — clear memory files
        if text == "/forget":
            result = self._clear_memory()
            await self._config_reply(chat_id, result)
            return

        # If in config mode, route to the config state machine
        if chat_id in self._config_sessions:
            await self._handle_config_input(chat_id, text)
            return

        # Normal message — forward to agent
        await self._handle_message(
            sender_id=sender_id,
            chat_id=chat_id,
            content=content,
            media=media,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # /config state machine
    # ------------------------------------------------------------------

    async def _config_reply(self, chat_id: str, text: str) -> None:
        """Send a config-flow message directly to the response queue."""
        queue = self.get_response_queue(chat_id)
        await queue.put(OutboundMessage(channel=self.name, chat_id=chat_id, content=text))

    async def _handle_config_input(self, chat_id: str, text: str) -> None:
        """Process one round of user input in the /config flow."""
        session = self._config_sessions[chat_id]

        if session.state == "select_provider":
            await self._config_select_provider(chat_id, session, text)
        elif session.state == "input_api_key":
            await self._config_input_api_key(chat_id, session, text)
        elif session.state == "ask_continue":
            await self._config_ask_continue(chat_id, session, text)
        elif session.state == "input_model":
            await self._config_input_model(chat_id, session, text)

    async def _config_select_provider(
        self, chat_id: str, session: _ConfigSession, text: str
    ) -> None:
        """Handle provider selection by number."""
        try:
            idx = int(text)
        except ValueError:
            await self._config_reply(chat_id, "请输入有效的序号数字。")
            return

        if idx == 0:
            self._config_sessions.pop(chat_id, None)
            await self._config_reply(chat_id, "已取消配置。")
            return

        if idx < 1 or idx > len(session.provider_specs):
            await self._config_reply(
                chat_id, f"请输入 0 ~ {len(session.provider_specs)} 之间的数字。"
            )
            return

        spec = session.provider_specs[idx - 1]
        session.selected_provider_name = spec.name
        session.state = "input_api_key"
        await self._config_reply(chat_id, f"请输入 {spec.label} 的 API Key（输入 0 退出）：")

    async def _config_input_api_key(
        self, chat_id: str, session: _ConfigSession, text: str
    ) -> None:
        """Save the API key and ask whether to configure another provider."""
        api_key = text.strip()
        if api_key == "0":
            self._config_sessions.pop(chat_id, None)
            await self._config_reply(chat_id, "已取消配置。")
            return
        if not api_key:
            await self._config_reply(chat_id, "API Key 不能为空，请重新输入：")
            return

        # Save the key to config
        self._save_provider_api_key(session.selected_provider_name, api_key)

        spec = next(
            (s for s in session.provider_specs if s.name == session.selected_provider_name),
            None,
        )
        label = spec.label if spec else session.selected_provider_name
        session.state = "ask_continue"
        await self._config_reply(
            chat_id,
            f"{label} 的 API Key 已保存。\n\n"
            "是否继续配置其他 Provider？\n"
            "  1. 配置其他 Provider\n"
            "  2. 设置默认模型\n"
            "  0. 完成配置",
        )

    async def _config_ask_continue(
        self, chat_id: str, session: _ConfigSession, text: str
    ) -> None:
        """Handle the continue/model/done choice."""
        choice = text.strip()

        if choice == "1":
            session.state = "select_provider"
            await self._config_reply(chat_id, _build_provider_list(session.provider_specs))
        elif choice == "2":
            session.state = "input_model"
            # Show current default model
            from nanobot.config.loader import load_config
            cfg = load_config()
            current = cfg.agents.defaults.model
            await self._config_reply(
                chat_id,
                f"当前默认模型：{current}\n请输入新的默认模型名称（例如 anthropic/claude-sonnet-4-20250514，输入 0 放弃修改退出）：",
            )
        elif choice == "0":
            self._config_sessions.pop(chat_id, None)
            await self._config_reply(
                chat_id, "配置已保存，请使用 /restart 重新启动服务以使配置生效。"
            )
        else:
            await self._config_reply(chat_id, "请输入 0、1 或 2。")

    async def _config_input_model(
        self, chat_id: str, session: _ConfigSession, text: str
    ) -> None:
        """Save the default model name and finish."""
        model_name = text.strip()
        if model_name == "0":
            self._config_sessions.pop(chat_id, None)
            await self._config_reply(chat_id, "已取消配置，未保存。")
            return
        if not model_name:
            await self._config_reply(chat_id, "模型名称不能为空，请重新输入：")
            return

        self._save_default_model(model_name)
        self._config_sessions.pop(chat_id, None)
        await self._config_reply(
            chat_id,
            f"默认模型已设置为：{model_name}\n配置已保存，请使用 /restart 重新启动服务以使配置生效。",
        )

    @staticmethod
    def _save_provider_api_key(provider_name: str, api_key: str) -> None:
        """Persist a provider's API key to config.json."""
        from nanobot.config.loader import load_config, save_config

        cfg = load_config()
        provider_cfg = getattr(cfg.providers, provider_name, None)
        if provider_cfg is not None:
            provider_cfg.api_key = api_key
        save_config(cfg)
        logger.info("Saved API key for provider '{}'", provider_name)

    @staticmethod
    def _save_default_model(model: str) -> None:
        """Persist the default model to config.json."""
        from nanobot.config.loader import load_config, save_config

        cfg = load_config()
        cfg.agents.defaults.model = model
        save_config(cfg)
        logger.info("Saved default model '{}'", model)

    @staticmethod
    def _clear_memory() -> str:
        """Clear MEMORY.md and HISTORY.md, return a status message."""
        from pathlib import Path

        from nanobot.config.loader import load_config

        cfg = load_config()
        memory_dir = cfg.workspace_path / "memory"
        cleared = []
        for name in ("MEMORY.md", "HISTORY.md"):
            path = memory_dir / name
            if path.exists() and path.stat().st_size > 0:
                path.write_text("")
                cleared.append(name)
        if cleared:
            logger.info("Cleared memory files: {}", ", ".join(cleared))
            return f"已清除记忆文件：{', '.join(cleared)}"
        return "记忆文件已经是空的，无需清除。"
