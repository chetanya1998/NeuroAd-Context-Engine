from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="The MCP SDK requires Python 3.10+; production uses Python 3.11.")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from developer_platform import DeveloperServices
from mcp_runtime import create_mcp_runtime


def test_mcp_runtime_registers_expected_tools_and_oauth_tables(tmp_path):
    database = sqlite3.connect(tmp_path / "mcp.db", check_same_thread=False)
    database.row_factory = sqlite3.Row

    def execute(sql, params=()):
        database.execute(sql, params)
        database.commit()

    def query_one(sql, params=()):
        return database.execute(sql, params).fetchone()

    def query_all(sql, params=()):
        return database.execute(sql, params).fetchall()

    services = DeveloperServices(
        execute=execute,
        query_one=query_one,
        query_all=query_all,
        new_id=lambda prefix: f"{prefix}_test",
        utc_now=lambda: "2026-08-06T00:00:00",
        store_uploaded_video=lambda _: None,
        create_video_analysis_job=lambda *_args, **_kwargs: {},
        add_video_to_comparison=lambda *_: None,
        process_comparison_job=lambda *_: None,
        submit_comparison=lambda *_: None,
        build_analysis_payload=lambda row: dict(row),
        build_comparison_payload=lambda row: dict(row),
        storage_dir=tmp_path,
    )

    runtime = create_mcp_runtime(services, "http://localhost:8000")
    tools = asyncio.run(runtime.mcp.list_tools())
    tool_names = {tool.name for tool in tools}

    assert runtime.app is not None
    assert {
        "list_videos",
        "get_video_verdict",
        "create_improvement_plan",
        "get_comparison_verdict",
        "request_analysis_approval",
        "start_approved_analysis",
    } <= tool_names
    assert query_one("select name from sqlite_master where type = 'table' and name = 'mcp_oauth_tokens'")
