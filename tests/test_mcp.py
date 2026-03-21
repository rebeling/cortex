from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def _structured_payload(result) -> dict:
    if result.structuredContent:
        return result.structuredContent
    text_block = result.content[0]
    return json.loads(text_block.text)


async def _mcp_session(app):
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as http_client:
            async with streamable_http_client(
                "http://localhost/mcp/",
                http_client=http_client,
                terminate_on_close=False,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    yield session


@pytest.mark.anyio
async def test_mcp_register_returns_project_id(app, repo_dir: Path) -> None:
    async for session in _mcp_session(app):
            result = await session.call_tool("cortex_register", arguments={"repo_path": str(repo_dir)})
            payload = _structured_payload(result)
    assert payload["ok"] is True
    assert payload["project_id"]
    assert payload["stored_memory_count"] >= 0


@pytest.mark.anyio
async def test_mcp_push_and_query_round_trip(app, repo_dir: Path) -> None:
    async for session in _mcp_session(app):
            push_result = await session.call_tool(
                "cortex_push",
                arguments={
                    "repo_path": str(repo_dir),
                    "content": "The authentication module uses JWT tokens with RS256.",
                    "file_paths": ["app/auth.py"],
                },
            )
            push_payload = _structured_payload(push_result)
            query_result = await session.call_tool(
                "cortex_query",
                arguments={
                    "repo_path": str(repo_dir),
                    "question": "How does authentication work?",
                    "top_k": 3,
                },
            )
            query_payload = _structured_payload(query_result)
    assert push_payload["ok"] is True
    assert push_payload["stored_count"] >= 1
    assert query_payload["ok"] is True
    assert query_payload["memory_block"]
    assert len(query_payload["results"]) >= 1


@pytest.mark.anyio
async def test_mcp_push_auto_registers(app, repo_dir: Path) -> None:
    async for session in _mcp_session(app):
            result = await session.call_tool(
                "cortex_push",
                arguments={
                    "repo_path": str(repo_dir),
                    "content": "Testing auto-registration via push.",
                },
            )
            payload = _structured_payload(result)
    assert payload["ok"] is True
    assert payload["stored_count"] >= 1
    assert payload["session_id"]


@pytest.mark.anyio
async def test_mcp_query_auto_registers(app, repo_dir: Path) -> None:
    async for session in _mcp_session(app):
            result = await session.call_tool(
                "cortex_query",
                arguments={
                    "repo_path": str(repo_dir),
                    "question": "What is this project about?",
                },
            )
            payload = _structured_payload(result)
    assert payload["ok"] is True
    assert payload["memory_block"]
