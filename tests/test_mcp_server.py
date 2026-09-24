"""WARRANT over MCP, end to end: a real MCP client calling the MCP server,
which calls the real FastAPI plane through an ASGI transport, which runs the
deterministic engine. Nothing between the client and the grant table is stubbed
except the network socket.
"""
from __future__ import annotations

import importlib
import json

import httpx
import pytest
from mcp.client import Client

from warrant.config import load_config
from warrant.mcp_server import make_server
from warrant.service import WarrantService

ROSTER_OK = "which employees travelled in Q3, from the employee roster"
COMP = "verify allowance claims against employee compensation bands"


@pytest.fixture
def plane(tmp_path, monkeypatch):
    cfg = load_config("config/warrant.offline.yaml")
    cfg.audit_path = tmp_path / "warrant.jsonl"
    app_mod = importlib.import_module("warrant.api.app")
    monkeypatch.setattr(app_mod, "_svc", WarrantService(cfg))
    return app_mod.app, cfg


def _server(app, agent="expense-auditor", token=None):
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                             base_url="http://plane")
    return make_server(agent, "http://plane", token=token, http=http)


def _data(result) -> dict:
    """Structured tool output, whichever field this SDK version populates."""
    for attr in ("structured_content", "structuredContent"):
        v = getattr(result, attr, None)
        if v:
            return v
    return json.loads(result.content[0].text)


# ------------------------------------------------------------ the invariant

async def test_no_tool_lets_the_model_choose_who_it_is(plane):
    """If any tool took a caller argument, the model driving the MCP client
    could impersonate another agent - the self-asserted caller_agent hole the
    review closed on the HTTP API, reopened one layer up."""
    app, _ = plane
    async with Client(_server(app)) as c:
        tools = (await c.list_tools()).tools
    forbidden = {"caller", "caller_agent", "agent", "agent_id", "requested_by",
                 "capability", "as_agent"}
    for t in tools:
        params = set((t.input_schema or {}).get("properties", {}))
        assert not params & forbidden, (
            f"tool {t.name!r} accepts {params & forbidden}; identity must come "
            f"from server configuration, never from the model")


# ------------------------------------------------------------ outcomes

async def test_granted_call_returns_a_warrant(plane):
    app, _ = plane
    async with Client(_server(app)) as c:
        r = _data(await c.call_tool("request_warrant",
                                    {"callee": "roster-planner", "purpose": ROSTER_OK}))
    assert r["granted"] is True
    assert r["warrant_id"]
    assert r["entities"] == ["Employee.Roster"]


async def test_refusal_is_data_with_a_steward_and_a_next_step(plane):
    """Not a tool error: an agent can only replan around a refusal it can read."""
    app, _ = plane
    async with Client(_server(app)) as c:
        res = await c.call_tool("request_warrant",
                                {"callee": "roster-planner", "purpose": COMP})
    assert not getattr(res, "is_error", getattr(res, "isError", False))
    r = _data(res)
    assert r["granted"] is False
    assert r["refused"] == [{"data_entity": "Employee.Compensation",
                             "classification": "restricted",
                             "steward": "People & Culture"}]
    assert "raise_grant_request" in r["remediation"]


async def test_list_my_access_lets_an_agent_plan_before_it_calls(plane):
    app, _ = plane
    async with Client(_server(app)) as c:
        r = _data(await c.call_tool("list_my_access", {}))
    assert r["capability"] == "expense-management"
    comp = [e for e in r["entries"] if e["data_entity"] == "Employee.Compensation"]
    assert comp and comp[0]["granted"] is False
    assert comp[0]["steward"] == "People & Culture"


# ------------------------------------------------------------ the loop

async def test_grant_request_before_any_refusal_is_rejected(plane):
    app, _ = plane
    async with Client(_server(app)) as c:
        r = _data(await c.call_tool("raise_grant_request",
                                    {"data_entity": "Employee.Compensation",
                                     "reason": "please"}))
    assert r["accepted"] is False
    assert "no recorded refusal" in r["error"]


async def test_refuse_then_request_is_routed_to_the_steward(plane):
    app, _ = plane
    async with Client(_server(app)) as c:
        await c.call_tool("request_warrant",
                          {"callee": "roster-planner", "purpose": COMP})
        r = _data(await c.call_tool("raise_grant_request",
                                    {"data_entity": "Employee.Compensation",
                                     "reason": "close 6 Q3 claims", "blocking": 6}))
    assert r["accepted"] is True
    assert r["routed_to"] == "People & Culture"


# ------------------------------------------------------------ auth

async def test_plane_auth_applies_through_mcp(plane):
    """With agent_auth required, a server with no token gets nothing."""
    app, cfg = plane
    cfg.agent_auth = "required"
    cfg.agent_tokens = {"tok": "expense-auditor"}
    async with Client(_server(app, token=None)) as c:
        res = await c.call_tool("request_warrant",
                                {"callee": "roster-planner", "purpose": ROSTER_OK})
    assert getattr(res, "is_error", getattr(res, "isError", False))

    async with Client(_server(app, token="tok")) as c:
        r = _data(await c.call_tool("request_warrant",
                                    {"callee": "roster-planner", "purpose": ROSTER_OK}))
    assert r["granted"] is True
