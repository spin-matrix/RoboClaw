"""Tests for the App channel and its gateway HTTP API endpoints."""

import asyncio

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.app import AppChannel, AppConfig


def _make_channel(**overrides) -> tuple[AppChannel, MessageBus]:
    bus = MessageBus()
    cfg = AppConfig(**{"enabled": True, "allow_from": ["*"], **overrides})
    ch = AppChannel(cfg, bus)
    return ch, bus


async def test_start_stop():
    ch, _ = _make_channel()
    await ch.start()
    assert ch.is_running
    await ch.stop()
    assert not ch.is_running


@pytest.mark.asyncio
async def test_handle_api_message_publishes_to_bus():
    ch, bus = _make_channel()
    await ch.start()
    await ch.handle_api_message(sender_id="u1", chat_id="c1", content="hello")
    msg = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)
    assert msg.channel == "app"
    assert msg.sender_id == "u1"
    assert msg.chat_id == "c1"
    assert msg.content == "hello"


@pytest.mark.asyncio
async def test_send_delivers_to_response_queue():
    ch, _ = _make_channel()
    await ch.start()
    queue = ch.get_response_queue("c1")
    out = OutboundMessage(channel="app", chat_id="c1", content="reply")
    await ch.send(out)
    msg = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert msg.content == "reply"


@pytest.mark.asyncio
async def test_send_without_listener_does_not_raise():
    ch, _ = _make_channel()
    await ch.start()
    out = OutboundMessage(channel="app", chat_id="unknown", content="lost")
    await ch.send(out)  # should not raise


@pytest.mark.asyncio
async def test_access_denied():
    ch, bus = _make_channel(allow_from=["admin"])
    await ch.start()
    await ch.handle_api_message(sender_id="intruder", chat_id="c1", content="hi")
    assert bus.inbound_size == 0


@pytest.mark.asyncio
async def test_remove_response_queue():
    ch, _ = _make_channel()
    queue = ch.get_response_queue("c1")
    assert queue is not None
    ch.remove_response_queue("c1")
    assert ch._response_queues.get("c1") is None
