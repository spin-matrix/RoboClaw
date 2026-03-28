import asyncio
import json

import pytest

from nanobot.agent.knowledge import connect_db, dataset_display_name, import_file_to_db, knowledge_db_path, list_datasets
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse


class DummyProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]):
        super().__init__()
        self._responses = list(responses)

    async def chat(self, *args, **kwargs) -> LLMResponse:
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content="")

    def get_default_model(self) -> str:
        return "test-model"


def test_dataset_display_name_strips_upload_prefix() -> None:
    assert (
        dataset_display_name("20260313_124735_8818a94e233b_products_cat6.json", "kb_x")
        == "products_cat6"
    )


def test_process_direct_auto_imports_structured_attachments(tmp_path) -> None:
    csv_path = tmp_path / "prices.csv"
    csv_path.write_text("name,price\napple,3\nbanana,5\n", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(content="chat"),
        LLMResponse(content="普通回复"),
    ])
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )

    reply = asyncio.run(
        loop.process_direct(
            "帮我记住这个表",
            session_key="cli:test",
            media=[str(csv_path)],
        )
    )

    assert reply == "普通回复"

    conn = connect_db(knowledge_db_path(tmp_path))
    try:
        datasets = list_datasets(conn)
    finally:
        conn.close()

    assert len(datasets) == 1
    assert datasets[0]["source_file"].endswith(".csv")

    session = loop.sessions.get_or_create("cli:test")
    assert "[Imported Knowledge Datasets This Turn]" in session.messages[0]["content"]


def test_handle_knowledge_manage_inspect_returns_schema_context(tmp_path) -> None:
    json_path = tmp_path / "items.json"
    json_path.write_text(
        json.dumps(
            [
                {"name": "alpha", "price": "10"},
                {"name": "beta", "price": "20"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    provider = DummyProvider([])
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )

    imported = import_file_to_db(
        db_path=knowledge_db_path(tmp_path),
        input_path=json_path,
        session_key="cli:test",
    )
    datasets = [{
        "table_name": imported["table_name"],
        "source_file": imported["source_file"],
        "row_count": imported["row_count"],
    }]

    async def _fake_chat_plain(messages):
        content = messages[-1]["content"]
        if "User request:" in content:
            return json.dumps({"action": "inspect", "index": 1}, ensure_ascii=False)
        return "存储商品名称和价格等信息，可用于价格查询。"

    loop._chat_plain = _fake_chat_plain  # type: ignore[method-assign]

    result = asyncio.run(loop._handle_knowledge_manage("看看第一个表有哪些字段", datasets))

    assert "表名: items" in result
    assert "描述: 存储商品名称和价格等信息，可用于价格查询。" in result
    assert "主要字段:" in result
    assert "- price" in result


def test_handle_knowledge_manage_list_returns_user_facing_catalog(tmp_path) -> None:
    json_path = tmp_path / "classmate.json"
    json_path.write_text(
        json.dumps([{"name": "alice", "phone": "123"}], ensure_ascii=False),
        encoding="utf-8",
    )

    provider = DummyProvider([])
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )

    imported = import_file_to_db(
        db_path=knowledge_db_path(tmp_path),
        input_path=json_path,
        session_key="cli:test",
    )
    datasets = [{
        "table_name": imported["table_name"],
        "source_file": imported["source_file"],
        "row_count": imported["row_count"],
    }]

    async def _fake_chat_plain(messages):
        content = messages[-1]["content"]
        if "User request:" in content:
            return json.dumps({"action": "list"}, ensure_ascii=False)
        return "存储同学姓名和电话等联系信息。"

    loop._chat_plain = _fake_chat_plain  # type: ignore[method-assign]

    result = asyncio.run(loop._handle_knowledge_manage("我现在有多少张表", datasets))

    assert "当前知识库共有 1 张表" in result
    assert "索引 | 表名 | 描述" in result
    assert "1 | classmate | 存储同学姓名和电话等联系信息。" in result


def test_handle_knowledge_manage_remove_by_index(tmp_path) -> None:
    json_path = tmp_path / "items.json"
    json_path.write_text(
        json.dumps([{"name": "alpha"}, {"name": "beta"}], ensure_ascii=False),
        encoding="utf-8",
    )

    provider = DummyProvider([])
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )

    imported = import_file_to_db(
        db_path=knowledge_db_path(tmp_path),
        input_path=json_path,
        session_key="cli:test",
    )
    datasets = [{
        "table_name": imported["table_name"],
        "source_file": imported["source_file"],
        "row_count": imported["row_count"],
    }]

    async def _fake_chat_plain(messages):
        return json.dumps({"action": "remove", "index": 1}, ensure_ascii=False)

    loop._chat_plain = _fake_chat_plain  # type: ignore[method-assign]

    result = asyncio.run(loop._handle_knowledge_manage("删除第一个表", datasets))

    assert "已删除第 1 张表：items" in result

    conn = connect_db(knowledge_db_path(tmp_path))
    try:
        assert list_datasets(conn) == []
    finally:
        conn.close()
