"""The seam every cross-boundary call passes through, and the check the
receiving end performs.

Two halves, and both are load-bearing:

`governed_call` is the *only* way an agent reaches another organisation unit.
It asks the plane for a warrant first. On refusal it does **not** raise - it
returns the structured reasons so the caller's planner can degrade, escalate or
record (ADR-0008). A refusal is an input, not an error.

`verify_warrant` is what the callee runs before handing anything over. Without
it the seam is honour-system: a caller could simply skip asking and the boundary
would enforce nothing, while every diagram still showed it enforcing something.
The callee therefore re-checks with the plane that the warrant is real, current,
issued for *this* caller and callee, and actually covers the entities in the
response it is about to send.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import httpx


class WarrantRejected(Exception):
    """Raised by a *callee* that was handed an unusable warrant.

    Deliberately an exception, unlike a refusal: a refusal is a normal
    authorization outcome the caller plans around, whereas reaching a callee
    with a bad warrant means something upstream is broken or hostile.
    """


@dataclass(slots=True)
class GovernedResult:
    granted: bool
    warrant_id: str = ""
    entities: list[str] = field(default_factory=list)
    reasons: list[dict] = field(default_factory=list)
    missing_grants: list[dict] = field(default_factory=list)
    justification: str = ""
    served_by: dict = field(default_factory=dict)
    data: object = None

    @property
    def refused_entities(self) -> list[str]:
        return [m["data_entity"] for m in self.missing_grants]

    def steward_of(self, model_json: dict, entity_id: str) -> str:
        """Which org unit stewards a refused entity - the human the escalation
        branch addresses its grant request to."""
        orgs = {o["id"]: o["name"] for o in model_json.get("org_units", [])}
        for e in model_json.get("data_entities", []):
            if e["id"] == entity_id:
                return orgs.get(e["owner_org"], e["owner_org"])
        return "unknown"


async def governed_call(
    client: httpx.AsyncClient,
    plane_url: str,
    *,
    caller: str,
    callee: str,
    purpose: str,
    callee_url: str | None = None,
    payload: str = "",
) -> GovernedResult:
    """Request a warrant, and only then make the call.

    Returns a `GovernedResult` either way. Never raises on a refusal.
    """
    r = await client.post(
        f"{plane_url.rstrip('/')}/v1/warrant",
        json={"caller_agent": caller, "callee_agent": callee,
              "purpose": purpose, "payload": payload},
    )
    body = r.json()

    if not body.get("granted"):
        return GovernedResult(
            granted=False,
            warrant_id=body.get("id", ""),
            entities=body.get("entities_touched", []),
            reasons=body.get("reasons", []),
            missing_grants=body.get("missing_grants", []),
            justification=body.get("justification", ""),
            served_by=body.get("served_by", {}),
        )

    result = GovernedResult(
        granted=True,
        warrant_id=body["id"],
        entities=body.get("entities_touched", []),
        reasons=body.get("reasons", []),
        justification=body.get("justification", ""),
        served_by=body.get("served_by", {}),
    )

    if callee_url:
        # The callee verifies this warrant itself before answering; we are not
        # trusted just because we present an id.
        resp = await client.post(
            f"{callee_url.rstrip('/')}/data",
            json={"warrant_id": result.warrant_id, "caller": caller,
                  "purpose": purpose},
        )
        if resp.status_code != 200:
            raise WarrantRejected(
                f"callee '{callee}' rejected warrant {result.warrant_id}: "
                f"{resp.status_code} {resp.text[:200]}"
            )
        result.data = resp.json()

    return result


async def verify_warrant(
    client: httpx.AsyncClient,
    plane_url: str,
    warrant_id: str,
    *,
    expect_caller: str,
    expect_callee: str,
    serving_entities: list[str],
) -> dict:
    """Callee-side check. Fails closed on every path.

    `serving_entities` are the entities in the response about to be sent. The
    warrant must cover all of them - a warrant for `Employee.Roster` does not
    authorise handing back `Employee.Compensation`, and checking only that the
    warrant *exists* would let exactly that through.
    """
    from datetime import datetime, timezone

    r = await client.get(f"{plane_url.rstrip('/')}/v1/warrant/{warrant_id}")
    if r.status_code != 200:
        raise WarrantRejected(f"warrant {warrant_id} not found at the plane")
    w = r.json()

    if not w.get("granted"):
        raise WarrantRejected(f"warrant {warrant_id} records a refusal")
    if w.get("caller") != expect_caller:
        raise WarrantRejected(
            f"warrant {warrant_id} was issued to '{w.get('caller')}', "
            f"not '{expect_caller}'"
        )
    if w.get("callee") != expect_callee:
        raise WarrantRejected(
            f"warrant {warrant_id} was issued for callee '{w.get('callee')}', "
            f"not '{expect_callee}'"
        )

    expires = w.get("expires_at")
    if not expires:
        raise WarrantRejected(f"warrant {warrant_id} carries no expiry")
    if datetime.now(timezone.utc) > datetime.fromisoformat(expires):
        raise WarrantRejected(f"warrant {warrant_id} expired at {expires}")

    covered = set(w.get("entities_touched", []))
    uncovered = [e for e in serving_entities if e not in covered]
    if uncovered:
        raise WarrantRejected(
            f"warrant {warrant_id} does not cover {', '.join(sorted(uncovered))}"
        )

    return w
