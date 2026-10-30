"""Finance brings its own claims: a prepared scenario or a CSV in the fixed
format. Per browser, so one judge's upload never changes another's audit."""
from __future__ import annotations

import importlib
import json

import pytest
from fastapi.testclient import TestClient

from warrant.agents.claims import FIELDS, SCENARIOS, parse_claims_csv
from warrant.config import load_config
from warrant.service import WarrantService

HEADER = ",".join(FIELDS)
GOOD = HEADER + """
X-1,E-1042,2026-07-03,supplier,SUP-014,Northwind Logistics,freight,Pallet freight,128.50
X-2,E-1290,2026-09-22,allowance,,,allowance,Daily allowance,300
X-3,E-1042,2026-07-05,supplier,SUP-077,Nobody Ltd,supplies,Paper,20
"""


@pytest.fixture
def app_mod(tmp_path, monkeypatch):
    cfg = load_config("config/warrant.offline.yaml")
    cfg.audit_path = tmp_path / "warrant.jsonl"
    cfg.demo_mode = True
    mod = importlib.import_module("warrant.api.app")
    monkeypatch.setattr(mod, "_svc", WarrantService(cfg))
    monkeypatch.setattr(mod, "_live_runs", {})
    monkeypatch.setattr(mod, "_workspaces", type(mod._workspaces)())
    monkeypatch.delenv("WARRANT_JUDGE_KEY", raising=False)
    return mod


def _run(c: TestClient) -> dict:
    with c.stream("GET", "/v1/demo/stream") as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                e = json.loads(line[6:])
                if e["kind"] == "done":
                    return e["result"]
    raise AssertionError("no result")


def test_parser_accepts_the_fixed_format():
    claims = parse_claims_csv(GOOD)
    assert [c["id"] for c in claims] == ["X-1", "X-2", "X-3"]
    assert claims[1]["supplier_id"] is None and claims[1]["category"] == "allowance"


@pytest.mark.parametrize("bad, says", [
    ("id,amount\nX,1", "missing columns"),
    (HEADER + "\nX-1,E-1,2026-13-01,supplier,S-1,A,freight,d,10", "date"),
    (HEADER + "\nX-1,E-1,2026-07-01,refund,S-1,A,freight,d,10", "type"),
    (HEADER + "\nX-1,E-1,2026-07-01,supplier,S-1,A,freight,d,-5", "amount"),
    (HEADER + "\nX-1,E-1,2026-07-01,supplier,S-1,<script>,freight,d,5", "plain characters"),
    (HEADER + "\n", "no claims"),
])
def test_parser_rejects_with_a_reason(bad, says):
    with pytest.raises(ValueError, match=says):
        parse_claims_csv(bad)


def test_scenarios_are_listed_and_northwind_is_the_demo(app_mod):
    body = TestClient(app_mod.app).get("/v1/scenarios").json()
    ids = {s["id"]: s for s in body["scenarios"]}
    assert set(ids) == set(SCENARIOS) and ids["northwind-q3"]["demo"] is True
    assert ids["northwind-q3"]["count"] == 47 and body["fields"] == list(FIELDS)


def test_choosing_a_scenario_changes_what_this_browser_audits(app_mod):
    a, b = TestClient(app_mod.app), TestClient(app_mod.app)
    assert a.get("/v1/workspace").json()["chosen"] is False
    r = a.post("/v1/workspace", json={"scenario": "supplier-review"})
    assert r.status_code == 200 and r.json()["count"] == 12
    res = _run(a)
    assert res["total"] == 12
    assert {f["claim"] for f in res["flagged"]} == {"INV-503", "INV-505", "INV-507", "INV-510"}
    assert _run(b)["total"] == 47                   # the other browser is untouched


def test_an_uploaded_csv_is_audited_and_unknowns_are_queried(app_mod):
    c = TestClient(app_mod.app)
    r = c.post("/v1/workspace", json={"csv": GOOD, "name": "Team <b>Q3</b>"})
    assert r.status_code == 200 and r.json()["title"] == "Team bQ3b" and r.json()["count"] == 3
    res = _run(c)
    kinds = {f["claim"]: f["kind"] for f in res["flagged"]}
    assert kinds.get("X-3") == "no-contract"


def test_a_bad_upload_is_refused_with_the_rows(app_mod):
    c = TestClient(app_mod.app)
    r = c.post("/v1/workspace", json={"csv": HEADER + "\nX-1,E-1,nope,supplier,S,A,freight,d,1"})
    assert r.status_code == 400 and "row 2" in r.json()["error"]


def test_choosing_data_needs_the_judge_code(app_mod, monkeypatch):
    monkeypatch.setenv("WARRANT_JUDGE_KEY", "k")
    assert TestClient(app_mod.app).post("/v1/workspace", json={"scenario": "supplier-review"}).status_code == 401
