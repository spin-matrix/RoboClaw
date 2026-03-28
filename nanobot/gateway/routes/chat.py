"""Chat API routes for the App channel."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from loguru import logger
from sqlmodel import Session, func, select, delete

from nanobot.config.paths import get_media_dir
from nanobot.gateway.database import SessionDep
from nanobot.gateway.models import BaseResponse, ChatCommand, ChatRequest, ChatResponse, Message, MessageStore, PageResponse

if TYPE_CHECKING:
    from nanobot.channels.app import AppChannel

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Populated by GatewayServer after channel init.
_app_channel: AppChannel | None = None


def configure(app_channel: AppChannel | None) -> None:
    """Wire the app channel into the router at startup."""
    global _app_channel
    _app_channel = app_channel


def _get_app_channel() -> AppChannel:
    if _app_channel is None:
        raise HTTPException(status_code=503, detail="App channel not enabled")
    return _app_channel


def _save_message(
    session: Session,
    chat_id: str,
    role: str,
    content: str,
    channel: str = "app",
    label: str = "text",
    media: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Persist a message to the database."""
    session.add(MessageStore(
        channel=channel,
        chat_id=chat_id,
        role=role,
        content=content,
        label=label,
        media=media or [],
        meta=metadata or {},
    ))
    session.commit()


CHAT_COMMANDS: list[ChatCommand] = [
    ChatCommand(name="/new", description="Start a new conversation"),
    ChatCommand(name="/stop", description="Stop the current task"),
    ChatCommand(name="/restart", description="Restart the system"),
    ChatCommand(name="/config", description="Configure system settings"),
    ChatCommand(name="/forget", description="Clear memory"),
    ChatCommand(name="/help", description="Show help information"),
]


@router.get("/options", response_model=BaseResponse[list[ChatCommand]])
async def chat_options() -> BaseResponse[list[ChatCommand]]:
    """Return the list of available chat commands."""
    return BaseResponse(data=CHAT_COMMANDS)


@router.post("/text", response_model=BaseResponse[None])
async def chat_text(session: SessionDep, body: ChatRequest) -> BaseResponse[None]:
    """发送文本信息，立即返回"""
    ch = _get_app_channel()
    ch.get_response_queue(body.chat_id)

    _save_message(session, body.chat_id, "user", body.content, label="text")

    await ch.handle_api_message(
        sender_id=body.sender_id,
        chat_id=body.chat_id,
        content=body.content,
    )

    return BaseResponse(message="消息已发送")


_IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "tiff", "svg"}
_AUDIO_EXTS = {"mp3", "m4a", "wav", "aac", "ogg", "flac"}


def _media_label(filename: str, mime_type: str | None) -> str:
    """Return a bracketed label for the file, matching Telegram's convention."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in _IMAGE_EXTS or (mime_type and mime_type.startswith("image/")):
        return "image"
    if ext in _AUDIO_EXTS or (mime_type and mime_type.startswith("audio/")):
        return "audio"
    return "file"


@router.post("/file", response_model=BaseResponse[dict])
async def chat_file(
    session: SessionDep,
    file: UploadFile = File(...),
    caption: str = Form(default=""),
    chat_id: str = Form(default="main"),
    sender_id: str = Form(default="user"),
) -> BaseResponse[dict]:
    """上传文件（图片、PDF等），附带可选文字说明"""
    ch = _get_app_channel()

    # Save uploaded file
    media_dir = get_media_dir("app")
    filename = file.filename or "upload"
    suffix = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    file_path = media_dir / f"{uuid.uuid4().hex[:12]}.{suffix}"
    data = await file.read()
    file_path.write_bytes(data)

    label = _media_label(filename, file.content_type)
    content_parts = []
    if caption:
        content_parts.append(caption)
    content_parts.append(f"[{label}: {file_path}]")
    content = "\n".join(content_parts)

    ch.get_response_queue(chat_id)
    _save_message(session, chat_id, "user", content, label="file", media=[str(file_path)])

    await ch.handle_api_message(
        sender_id=sender_id,
        chat_id=chat_id,
        content=content,
        media=[str(file_path)],
    )

    return BaseResponse(data={"label": label, "path": str(file_path)})


@router.post("/voice", response_model=BaseResponse[dict])
async def chat_voice(
    session: SessionDep,
    file: UploadFile = File(...),
    duration: float = Form(default=0.0),
    chat_id: str = Form(default="main"),
    sender_id: str = Form(default="user"),
) -> BaseResponse[dict]:
    """发送语音信息，返回转录文本"""
    ch = _get_app_channel()

    # Save uploaded file
    media_dir = get_media_dir("app")
    suffix = file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else "ogg"
    file_path = media_dir / f"{uuid.uuid4().hex[:12]}.{suffix}"
    data = await file.read()
    file_path.write_bytes(data)

    # Transcribe
    transcription = await ch.transcribe_audio(file_path)
    if not transcription:
        raise HTTPException(status_code=422, detail="Failed to transcribe audio")

    logger.info("App voice transcribed: {}...", transcription[:60])

    metadata = {"duration": duration, "voice_transcription": transcription}

    _save_message(session, chat_id, "user", transcription, label="audio", media=[str(file_path)], metadata=metadata)

    ch.get_response_queue(chat_id)

    await ch.handle_api_message(
        sender_id=sender_id,
        chat_id=chat_id,
        content=transcription,
        media=[str(file_path)],
        metadata=metadata,
    )

    return BaseResponse(data={"transcription": transcription})


@router.get("/response/{chat_id}", response_model=BaseResponse[ChatResponse])
async def chat_response(
    chat_id: str,
    session: SessionDep,
) -> BaseResponse[ChatResponse]:
    """轮询式获取回复

    在message的metadata中，以下字段具有特殊含义：
    - metadata._tool_hint=True表示该信息是工具调用提示，
    - metadata._progress=True表示该信息是进度更新（非最终回复）"""
    ch = _get_app_channel()
    queue = ch.get_response_queue(chat_id)
    messages = []
    is_final = False
    while not queue.empty():
        try:
            msg = queue.get_nowait()
        except asyncio.QueueEmpty:
            break

        # Copy media files to the app media dir so they can be served statically
        media_urls: list[str] = []
        if msg.media:
            media_dir = get_media_dir("app")
            for path_str in msg.media:
                src = Path(path_str)
                if src.is_file():
                    dest = media_dir / f"{uuid.uuid4().hex[:12]}_{src.name}"
                    shutil.copy2(src, dest)
                    media_urls.append(str(dest))
                else:
                    media_urls.append(path_str)

        _save_message(session, chat_id, "assistant", msg.content, label="text", media=media_urls or msg.media, metadata=msg.metadata)

        if not msg.metadata.get("_progress", False):
            is_final = True

        messages.append(Message(
            role="assistant",
            content=msg.content,
            media=_handle_media_url(media_urls) if media_urls else [],
            metadata=msg.metadata,
            created_at=msg.timestamp,
        ))

    return BaseResponse(
        data=ChatResponse(
            channel=ch.name,
            chat_id=chat_id,
            messages=messages,
            is_final=is_final,
        )
    )


def _handle_media_url(media: list[str]) -> list[str]:
    """Convert media file paths to accessible URLs."""
    # In a real deployment, this would likely involve generating signed URLs or similar.
    # For simplicity, we assume the media files are served statically at /media/.
    return [f"/media/{Path(path).name}" for path in media]


@router.get("/history/{chat_id}", response_model=BaseResponse[PageResponse])
async def chat_history(
    chat_id: str,
    session: SessionDep,
    query: Annotated[str | None, Query(description="搜索关键词，可选")] = None,
    label: Annotated[str | None, Query(description="消息类型过滤，可选，text、audio、file")] = None,
    page: Annotated[int, Query(ge=1, description="页码")] = 1,
    size: Annotated[int, Query(ge=1, le=1000, description="每页条数")] = 100,
) -> BaseResponse[PageResponse]:
    """Load message history for a conversation."""
    stmt = select(MessageStore).where(MessageStore.chat_id == chat_id)
    if query:
        stmt = stmt.where(MessageStore.content.contains(query))
    if label:
        stmt = stmt.where(MessageStore.label == label)

    total = session.exec(
        select(func.count()).select_from(stmt.subquery())
    ).one()
    messages = session.exec(
        stmt.order_by(MessageStore.created_at.desc()).offset((page - 1) * size).limit(size)
    ).all()

    return  BaseResponse(
        data=PageResponse(
            messages=[
                Message(
                    role=m.role,
                    content=m.content,
                    label=m.label,
                    media=_handle_media_url(m.media),
                    metadata=m.meta,
                    created_at=m.created_at,
                )
                for m in messages
            ],
            page=page,
            size=size,
            total=total,
        )
    )


@router.delete("/history/{chat_id}", response_model=BaseResponse[dict])
async def chat_history_clear(chat_id: str, session: SessionDep) -> BaseResponse[dict]:
    """Clear all message history for a conversation."""
    count = session.exec(
        delete(MessageStore)
        .where(MessageStore.chat_id == chat_id)
    ).rowcount
    session.commit()

    return BaseResponse(data={"ok": True, "deleted": count})
