"""The authorization decision.

DESIGN RULE (see ADR-0004): the model never decides. Grant resolution is
pure, deterministic graph traversal over the architecture model. Nemotron is
used for two things only:

  1. classifying which data entities a call actually touches (fast tier), and
  2. writing the human-readable justification (deep tier).

An LLM that *decides* authorization is not defensible. An LLM that classifies
and explains a decision made by a deterministic rule is.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..model import ArchitectureModel

# A warrant authorises one call, now. Without an expiry it is a bearer token
# valid forever, and a captured one replays indefinitely. Short, because the
# callee verifies against the plane anyway and nothing legitimately sits on a
# warrant for a minute.
WARRANT_TTL_S = 60


@dataclass(slots=True)
class WarrantRequest:
    caller_agent: str
    callee_agent: str
    purpose: str = ""
    payload: str = ""


@dataclass(slots=True)
class Reason:
    code: str
    detail: str


@dataclass(slots=True)
class WarrantDecision:
    id: str
    granted: bool
    request: WarrantRequest
    reasons: list[Reason] = field(default_factory=list)
    entities_touched: list[str] = field(default_factory=list)
    missing_grants: list[tuple[str, str]] = field(default_factory=list)
    justification: str = ""
    # Which tier CLASSIFIED. This is the one that can affect the outcome, so it
    # is the one the audit record and the UI mean by "served by".
    tier_used: str = ""
    provider_kind: str = ""
    # Which tier wrote the prose. Cosmetic - it cannot change the decision - but
    # recorded separately because it used to overwrite tier_used, which made
    # every record claim it was served by the deep tier.
    justify_tier: str = ""
    justify_provider: str = ""
    latency_ms: float = 0.0
    justify_ms: float = 0.0
    issued_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    expires_at: str = field(
        default_factory=lambda: (
            datetime.now(timezone.utc) + timedelta(seconds=WARRANT_TTL_S)
        ).isoformat()
    )

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(timezone.utc)) > datetime.fromisoformat(
            self.expires_at
        )

    def headline(self) -> str:
        verb = "Granted" if self.granted else "Denied"
        return f"{verb} - {self.request.caller_agent} -> {self.request.callee_agent}"


def decide(
    model: ArchitectureModel,
    req: WarrantRequest,
    entities_touched: list[str],
) -> WarrantDecision:
    """Pure function. No I/O, no model call, fully unit-testable."""
    did = uuid.uuid4().hex[:8]
    reasons: list[Reason] = []

    caller = model.agents.get(req.caller_agent)
    callee = model.agents.get(req.callee_agent)

    if caller is None:
        reasons.append(Reason("unknown_caller",
                              f"Agent '{req.caller_agent}' is not in the architecture model."))
    if callee is None:
        reasons.append(Reason("unknown_callee",
                              f"Agent '{req.callee_agent}' is not in the architecture model."))
    if caller is None or callee is None:
        # Fail closed: an unmodelled agent has no authority at all.
        return WarrantDecision(id=did, granted=False, request=req, reasons=reasons,
                               entities_touched=entities_touched)

    cap = model.capabilities.get(caller.serves)
    if cap is None:
        reasons.append(Reason("unknown_capability",
                              f"Caller serves unknown capability '{caller.serves}'."))
        return WarrantDecision(id=did, granted=False, request=req, reasons=reasons,
                               entities_touched=entities_touched)

    reasons.append(Reason(
        "caller_capability",
        f"Caller '{caller.name}' serves capability '{cap.name}', owned by "
        f"{model.org_units[cap.owner_org].name}.",
    ))

    missing: list[tuple[str, str]] = []
    for entity_id in entities_touched:
        entity = model.data_entities.get(entity_id)
        if entity is None:
            missing.append((cap.id, entity_id))
            reasons.append(Reason("unknown_entity",
                                  f"Data entity '{entity_id}' is not in the model."))
            continue
        steward = model.org_units[entity.owner_org]
        grant = model.has_grant(cap.id, entity_id)
        if grant:
            reasons.append(Reason(
                "grant_found",
                f"Capability '{cap.name}' holds a grant to '{entity.name}' "
                f"({entity.classification}), stewarded by {steward.name}, "
                f"granted by {grant.granted_by}.",
            ))
        else:
            missing.append((cap.id, entity_id))
            reasons.append(Reason(
                "grant_missing",
                f"Callee reads Data Entity '{entity.id}' ({entity.classification}), "
                f"stewarded by {steward.name}. Capability '{cap.name}' holds no "
                f"grant to that entity.",
            ))

    if callee.external:
        reasons.append(Reason(
            "external_callee",
            f"Callee '{callee.name}' is external to the organisation; "
            f"grants are evaluated strictly.",
        ))

    return WarrantDecision(
        id=did,
        granted=not missing,
        request=req,
        reasons=reasons,
        entities_touched=entities_touched,
        missing_grants=missing,
    )
