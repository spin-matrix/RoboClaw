"""Home API routes — current task and recent tasks."""
from __future__ import annotations

import asyncio
from datetime import datetime
import json
import shutil
import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query
import httpx
from loguru import logger
from sqlmodel import col, select

from nanobot.gateway.database import SessionDep
from nanobot.gateway.models import BaseResponse, CurrentTask, RecentTask, StatusResponse, Task
from nanobot.gateway.unitree_g1 import loco

if TYPE_CHECKING:
    from nanobot.channels.app import AppChannel

router = APIRouter(prefix="/api/home", tags=["home"])

# Populated by GatewayServer after channel init.
_app_channel: AppChannel | None = None
_motion_ready = False
_CACHE_TTL = 60  # seconds

# Cached values: (value, timestamp)
_weather_cache: tuple[str, float] | None = None
_mail_cache: tuple[str, float] | None = None
_calendar_cache: tuple[str, float] | None = None


def configure(app_channel: AppChannel | None) -> None:
    """Wire the app channel into the router at startup."""
    global _app_channel
    _app_channel = app_channel


def _get_app_channel() -> AppChannel:
    if _app_channel is None:
        raise HTTPException(status_code=503, detail="App channel not enabled")
    return _app_channel


def _cache_valid(cache: tuple[str, float] | None) -> bool:
    return cache is not None and (time.monotonic() - cache[1]) < _CACHE_TTL


async def _get_weather() -> str:
    global _weather_cache
    if _cache_valid(_weather_cache):
        return _weather_cache[0]
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                "https://wttr.in/Beijing?format=%c+%t+%h"
            )
            response.raise_for_status()
            result = response.text.strip()
        except httpx.HTTPError as e:
            logger.debug("HTTP error while fetching weather data: {}", e)
            result = "天气获取失败"
    _weather_cache = (result, time.monotonic())
    return result


async def _get_mail_summary() -> str:
    """Get mail summary via gws gmail."""
    global _mail_cache
    if _cache_valid(_mail_cache):
        return _mail_cache[0]
    if shutil.which("gws") is None:
        return "邮件技能尚未配置"
    try:
        proc = await asyncio.create_subprocess_exec(
            "gws", "gmail", "+triage", "--format", "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        output = stdout.decode().strip()
        if not output:
            result = "没有未读邮件"
        else:
            data = json.loads(output)
            unread = data.get("resultSizeEstimate", 0)
            result = f"{unread}封未读邮件" if unread > 0 else "没有未读邮件"
    except Exception as e:
        logger.debug("Failed to get mail summary: {}", e)
        result = "邮件获取失败"
    _mail_cache = (result, time.monotonic())
    return result


async def _get_calendar_summary() -> str:
    """Get calendar summary via gws calendar."""
    global _calendar_cache
    if _cache_valid(_calendar_cache):
        return _calendar_cache[0]
    if shutil.which("gws") is None:
        return "日历技能尚未配置"
    try:
        proc = await asyncio.create_subprocess_exec(
            "gws", "calendar", "+agenda", "--today", "--format", "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        data = json.loads(stdout.decode())
        events = data.get("events", [])
        count = data.get("count", len(events))
        if count == 0:
            result = "今日暂无安排"
        elif count == 1:
            event = events[0]
            start = event.get("start", "")
            time_part = datetime.fromisoformat(start).strftime("%H:%M")
            summary = event.get("summary", "")
            result = f"{time_part} {summary}"
        else:
            result = f"今日有{count}个安排"
    except Exception as e:
        logger.debug("Failed to get calendar summary: {}", e)
        result = "日历获取失败"
    _calendar_cache = (result, time.monotonic())
    return result


@router.get("/status", response_model=BaseResponse[StatusResponse])
async def status() -> BaseResponse[StatusResponse]:
    """Return device status: battery level, available and unavailable features."""
    # TODO: replace with real battery/feature detection
    if not _motion_ready:
        available = ["对话", "视觉识别"]
        unavailable = ["运动"]
    else:
        available = ["对话", "视觉识别", "运动"]
        unavailable = []
    weather_str, calendar_summary, mail_summary = await asyncio.gather(
        _get_weather(),
        _get_calendar_summary(),
        _get_mail_summary(),
    )
    weather_strs = weather_str.split()
    if len(weather_strs) < 3:
        air_quality_str = "空气质量未知"
    else:
        weather_str = " ".join(weather_strs[:-1])
        air_quality_str = "相对湿度: " + weather_strs[-1]

    return BaseResponse(
        data=StatusResponse(
            battery=98,
            available=available,
            unavailable=unavailable,
            weather=weather_str,
            air_quality=air_quality_str,
            calendar_summary=calendar_summary,
            mail_summary=mail_summary,
        )
    )


@router.post("/enable_motion", response_model=BaseResponse[None])
async def motion_ready() -> BaseResponse[None]:
    """Mark the motion system as ready."""
    await loco.initialize()
    global _motion_ready
    _motion_ready = True
    return BaseResponse(message="运动控制已启用")


@router.get("/current_task", response_model=BaseResponse[CurrentTask])
async def current_task() -> BaseResponse[CurrentTask]:
    """Return the currently executing task."""
    ch = _get_app_channel()
    tool_hint = ch.get_tool_hint("main")
    if tool_hint:
        return BaseResponse(data=CurrentTask(name=tool_hint, progress=50))
    return BaseResponse(data=CurrentTask(name="空闲", progress=0))


@router.get("/recent_tasks", response_model=BaseResponse[list[RecentTask]])
async def recent_tasks(
    session: SessionDep,
    limit: int = Query(default=10, ge=1, le=100),
) -> BaseResponse[list[RecentTask]]:
    """Return the most recent tasks."""
    tasks = session.exec(
        select(Task)
        .order_by(col(Task.created_at).desc())
        .limit(limit)
    ).all()

    return BaseResponse(
        data=[
            RecentTask(
                id=t.id,
                name=t.name,
                created_at=t.created_at,
            )
            for t in tasks
        ]
    )
