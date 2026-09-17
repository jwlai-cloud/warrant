"""The gate: no agent reaches another org unit's data except through a warrant.

Ungoverned reach would invalidate every claim the project makes, and it is the
kind of bug that looks fine in review - the architecture diagram still shows a
seam, the code just doesn't go through it. So it is asserted two ways:

  * structurally - no module under `warrant.agents` may open its own HTTP
    connection except `base.py`, which is the seam itself; and
  * behaviourally - a callee handed a warrant that is missing, expired, issued
    to someone else, or that does not cover the entity being served, refuses.

The behavioural half is the one that matters most. Checking only that a warrant
*exists* would let a caller present a valid warrant for `Employee.Roster` and
receive `Employee.Compensation` back.
"""
from __future__ import annotations

import pathlib
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from warrant.agents import WarrantRejected, governed_call, verify_warrant

PLANE = "http://plane.test"
AGENTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "src" / "warrant" / "agents"


# --------------------------------------------------------------------------
# structural
# --------------------------------------------------------------------------

# The seam is two modules: base.py holds the primitives, serving.py is the
# callee half that applies them. Everything else is agent business logic and
# must reach peers only through governed_call.
SEAM = {"base.py", "serving.py", "__init__.py"}


NET_LIBS = {"httpx", "requests", "aiohttp", "urllib", "http"}


def _imported_modules(src: str) -> set[str]:
    """Top-level package of every import. Parsed, not substring-matched - an
    earlier version of this test flagged `grant_requests` as the `requests`
    library."""
    import ast
    mods: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module.split(".")[0])
    return mods


def test_business_agents_do_not_speak_http():
    """An agent module opening its own connection is a path around the seam."""
    offenders = {}
    for path in AGENTS_DIR.rglob("*.py"):
        if path.name in SEAM:
            continue
        hits = _imported_modules(path.read_text(encoding="utf-8")) & NET_LIBS
        if hits:
            offenders[path.name] = sorted(hits)
    assert not offenders, (
        f"{offenders} open their own HTTP connections; cross-boundary calls "
        f"must go through governed_call in base.py"
    )


def test_serving_agents_only_ever_talk_to_the_plane():
    """serving.py legitimately speaks HTTP - to verify a warrant. It must not
    also be able to call a peer, or a callee could chain onward ungoverned."""
    src = (AGENTS_DIR / "serving.py").read_text(encoding="utf-8")
    assert "plane_url" in src
    for forbidden in ("callee_url", "governed_call", "AGENT_URLS", "peer_url"):
        assert forbidden not in src, (
            f"serving.py references {forbidden}; a serving agent must only "
            f"reach the authorization plane, never another agent"
        )


# --------------------------------------------------------------------------
# behavioural - callee-side verification
# --------------------------------------------------------------------------

def _warrant(**over) -> dict:
    w = {
        "id": "w1",
        "granted": True,
        "caller": "expense-auditor",
        "callee": "roster-planner",
        "entities_touched": ["Employee.Roster"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
    }
    w.update(over)
    return w


def _plane(warrant: dict | None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if warrant is None:
            return httpx.Response(404, json={"error": "unknown warrant"})
        return httpx.Response(200, json=warrant)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _verify(warrant: dict | None, serving: list[str]):
    async with _plane(warrant) as c:
        return await verify_warrant(
            c, PLANE, "w1",
            expect_caller="expense-auditor",
            expect_callee="roster-planner",
            serving_entities=serving,
        )


async def test_valid_warrant_passes():
    w = await _verify(_warrant(), ["Employee.Roster"])
    assert w["granted"] is True


async def test_unknown_warrant_is_rejected():
    with pytest.raises(WarrantRejected, match="not found"):
        await _verify(None, ["Employee.Roster"])


async def test_warrant_recording_a_refusal_is_rejected():
    with pytest.raises(WarrantRejected, match="refusal"):
        await _verify(_warrant(granted=False), ["Employee.Roster"])


async def test_warrant_issued_to_another_caller_is_rejected():
    with pytest.raises(WarrantRejected, match="issued to"):
        await _verify(_warrant(caller="vendor-scout"), ["Employee.Roster"])


async def test_warrant_issued_for_another_callee_is_rejected():
    with pytest.raises(WarrantRejected, match="issued for callee"):
        await _verify(_warrant(callee="inventory-reconciler"), ["Employee.Roster"])


async def test_expired_warrant_is_rejected():
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with pytest.raises(WarrantRejected, match="expired"):
        await _verify(_warrant(expires_at=past), ["Employee.Roster"])


async def test_warrant_without_an_expiry_is_rejected():
    w = _warrant()
    del w["expires_at"]
    with pytest.raises(WarrantRejected, match="no expiry"):
        await _verify(w, ["Employee.Roster"])


async def test_warrant_does_not_cover_the_entity_being_served():
    """The one that matters: a valid warrant for the roster must not be usable
    to hand back compensation."""
    with pytest.raises(WarrantRejected, match="does not cover Employee.Compensation"):
        await _verify(_warrant(), ["Employee.Roster", "Employee.Compensation"])


# --------------------------------------------------------------------------
# behavioural - caller side
# --------------------------------------------------------------------------

async def test_refusal_returns_reasons_and_does_not_raise():
    """A refusal is an input to the planner, not an error (ADR-0008)."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={
            "id": "w2", "granted": False,
            "entities_touched": ["Employee.Compensation"],
            "missing_grants": [{"capability": "expense-management",
                                "data_entity": "Employee.Compensation"}],
            "reasons": [{"code": "grant_missing", "detail": "..."}],
            "justification": "no grant",
            "served_by": {"tier": "fast", "provider": "mock"},
        })
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        r = await governed_call(c, PLANE, caller="expense-auditor",
                                callee="roster-planner", purpose="salary bands")
    assert r.granted is False
    assert r.refused_entities == ["Employee.Compensation"]


async def test_callee_rejection_does_raise():
    """A refusal is planned around; a callee rejecting our warrant is a bug or
    an attack, and must not be swallowed as if it were a refusal."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/warrant"):
            return httpx.Response(200, json={
                "id": "w3", "granted": True,
                "entities_touched": ["Employee.Roster"],
                "reasons": [], "justification": "", "served_by": {},
            })
        return httpx.Response(403, text="warrant does not cover that")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(WarrantRejected):
            await governed_call(c, PLANE, caller="expense-auditor",
                                callee="roster-planner", purpose="roster",
                                callee_url="http://roster.test")
