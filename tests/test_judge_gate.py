"""The public deployment must not spend Token Factory credit for strangers.

With WARRANT_JUDGE_KEY set, everything that can reach a model - every POST
under /v1/ and the live stream - needs the key (header, ?key= once, then a
cookie); reads stay open and the console falls back to the recorded replay.
Unset, nothing changes.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from warrant.config import load_config
from warrant.service import WarrantService

KEY = "judge-code-for-tests"
WARRANT = {"caller_agent": "expense-auditor", "callee_agent": "roster-planner",
           "purpose": "check rostered trips"}


@pytest.fixture
def app_mod(tmp_path, monkeypatch):
    cfg = load_config("config/warrant.offline.yaml")
    cfg.audit_path = tmp_path / "warrant.jsonl"
    cfg.demo_mode = True
    mod = importlib.import_module("warrant.api.app")
    monkeypatch.setattr(mod, "_svc", WarrantService(cfg))
    monkeypatch.setattr(mod, "_live_runs", {})
    return mod


def test_no_key_configured_means_open(app_mod, monkeypatch):
    monkeypatch.delenv("WARRANT_JUDGE_KEY", raising=False)
    c = TestClient(app_mod.app)
    assert c.post("/v1/warrant", json=WARRANT).status_code in (200, 403)
    assert c.get("/v1/access").json()["live"] is True


def test_key_configured_blocks_spending_routes(app_mod, monkeypatch):
    monkeypatch.setenv("WARRANT_JUDGE_KEY", KEY)
    c = TestClient(app_mod.app)
    for r in (c.post("/v1/warrant", json=WARRANT),
              c.post("/v1/grant-requests", json={}),
              c.post("/v1/demo/run"),
              c.post("/v1/demo/reset"),
              c.get("/v1/demo/stream"),
              c.post("/v1/warrant", json=WARRANT, headers={"X-Warrant-Key": "wrong"})):
        assert r.status_code == 401, r.text
        assert r.json()["replay"] == "/static/replay.json"
    assert c.get("/v1/access").json() == {"live": False, "key_required": True,
                                          "runs_left_today": 40,
                                          "replay": "/static/replay.json"}
    # a stranger still gets the whole console, in replay
    assert c.get("/v1/model").status_code == 200
    assert c.get("/").status_code == 200
    assert c.get("/static/replay.json").status_code == 200


def test_first_visit_sets_a_cookie(app_mod, monkeypatch):
    monkeypatch.setenv("WARRANT_JUDGE_KEY", KEY)
    c = TestClient(app_mod.app)
    assert c.get(f"/?key={KEY}").status_code == 200
    assert c.get("/v1/access").json()["live"] is True      # cookie, no key
    assert c.post("/v1/demo/reset").status_code != 401
    bad = TestClient(app_mod.app)
    bad.get("/?key=wrong")
    assert "warrant_key" not in bad.cookies
    assert bad.get("/v1/access").json()["live"] is False


def test_key_by_header_or_query(app_mod, monkeypatch):
    monkeypatch.setenv("WARRANT_JUDGE_KEY", KEY)
    c = TestClient(app_mod.app)
    assert c.post("/v1/warrant", json=WARRANT,
                  headers={"X-Warrant-Key": KEY}).status_code in (200, 403)
    assert c.get(f"/v1/access?key={KEY}").json()["live"] is True


def test_daily_cap(app_mod, monkeypatch):
    monkeypatch.setenv("WARRANT_JUDGE_KEY", KEY)
    monkeypatch.setenv("WARRANT_LIVE_DAILY_CAP", "2")
    assert app_mod._take_live_run() and app_mod._take_live_run()
    assert not app_mod._take_live_run()
    c = TestClient(app_mod.app)
    r = c.post("/v1/demo/run", headers={"X-Warrant-Key": KEY})
    assert r.status_code == 429 and "used up" in r.json()["error"]
    assert c.get(f"/v1/access?key={KEY}").json()["runs_left_today"] == 0
