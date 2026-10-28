"""The Steward Agent: People & Culture's agent, reviewing requests for its data.

When another agent asks for a grant, the request does not go straight to a
person. This agent reads it first, on the data owner's behalf, and writes a
recommendation the human steward sees alongside the request.

It is a second, independent agent - it works for a different department than
the requester, has different evidence, and can disagree. That is what makes the
system multi-agent rather than one agent with helpers: the Expense Auditor
argues for access, the Steward Agent weighs it for the owner, and a person
decides.

What it checks is code (facts it can verify, not ones it is told):

  - is there a real refusal of exactly this capability -> entity in the audit
    log, or is the request unprompted?
  - who is asking, what capability do they serve, which department owns it?
  - how sensitive is the entity?
  - has this pair been requested and declined before?
  - the blocking count is the REQUESTER's claim; the steward cannot see
    Finance's claims, so it says so rather than repeating the number as fact.

Nemotron weighs those facts and writes the recommendation and conditions. It
recommends; it never grants. Only a person's decision writes a grant
(ADR-0004 holds: no model output changes an authorization outcome).

With no model, a deterministic recommendation is produced from the same facts.
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from ..model import ArchitectureModel

AGENT_ID = "steward-agent"
LLM = Callable[[str, str, "dict | None"], Awaitable[str]]

RECOMMENDATIONS = ("approve", "approve_with_conditions", "decline")

_REVIEWER = (
    "You are the Steward Agent for the organisation unit that owns the data "
    "entity named. Another department's agent has requested read access. Review "
    "the request on the data owner's behalf, using ONLY the verified facts given.\n\n"
    "How to read the facts:\n"
    "- 'automatic_denials_for_missing_grant' counts times WARRANT automatically "
    "denied this access because no grant exists yet. That is NOT a decision "
    "against the request - it is the evidence that the requester's work is "
    "genuinely blocked, and the normal reason a grant request exists. Zero means "
    "the request is unprompted.\n"
    "- 'previously_declined_by_human_steward' lists earlier requests for the same "
    "access that a person explicitly declined. Only these are prior decisions "
    "against it.\n"
    "- 'blocking_claimed_by_requester' is the requester's own claim; you cannot "
    "verify it.\n\n"
    "Favour data minimisation: if access is justified, prefer approval with "
    "conditions that limit it to what the stated work needs. Recommend 'decline' "
    "when the request is unprompted, was declined by a person before with nothing "
    "new since, or the requester's capability has no plausible need for this data. "
    "Your recommendation goes to a human steward who decides; you grant nothing."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "recommendation": {"type": "string", "enum": list(RECOMMENDATIONS)},
        "conditions": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "reasoning": {"type": "string"},
    },
    "required": ["recommendation", "conditions", "reasoning"],
    "additionalProperties": False,
}


def facts_for(request: dict, model: ArchitectureModel, audit: list[dict],
              history: list[dict]) -> dict[str, Any]:
    cap, ent = request["capability"], request["data_entity"]
    entity = model.data_entities.get(ent)
    capability = model.capabilities.get(cap)
    requester = model.agents.get(request["requested_by"])
    orgs = {o.id: o.name for o in model.org_units.values()}
    refusals = [e for e in audit if not e.get("granted")
                and any(m.get("capability") == cap and m.get("data_entity") == ent
                        for m in e.get("missing_grants", []))]
    declined_before = [h["id"] for h in history
                       if h.get("capability") == cap and h.get("data_entity") == ent
                       and h.get("state") == "declined"]
    return {
        "request_id": request.get("id"),
        "requested_by": request["requested_by"],
        "requester_department": orgs.get(requester.org, requester.org) if requester else "unknown",
        "capability": cap,
        "capability_owner": orgs.get(capability.owner_org) if capability else "unknown",
        "data_entity": ent,
        "classification": entity.classification if entity else "unknown",
        "steward": orgs.get(entity.owner_org) if entity else "unknown",
        "automatic_denials_for_missing_grant": len(refusals),
        "purposes_that_were_denied": [e.get("purpose", "")[:200] for e in refusals[-3:]],
        "previously_declined_by_human_steward": declined_before,
        "blocking_claimed_by_requester": request.get("blocking", 0),
        "requester_reason": request.get("reason", "")[:1500],
    }


def _clip(text, limit: int) -> str:
    """Bound model text for the UI at a word, never mid-word."""
    text = str(text).strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _fallback(f: dict) -> dict:
    if not f["automatic_denials_for_missing_grant"]:
        return {"recommendation": "decline", "conditions": [],
                "reasoning": "No recorded refusal of this access exists, so the "
                             "request is not a response to blocked work."}
    if f["previously_declined_by_human_steward"]:
        return {"recommendation": "decline", "conditions": [],
                "reasoning": "The same access was declined before "
                             f"({', '.join(f['previously_declined_by_human_steward'])}); nothing new "
                             "has been recorded since."}
    conds = ["Read access limited to the records needed for the work described"]
    if f["classification"] == "restricted":
        conds.append("Review the grant once the blocked work is complete")
    return {"recommendation": "approve_with_conditions", "conditions": conds,
            "reasoning": f"WARRANT denied this access {f['automatic_denials_for_missing_grant']} time(s) for want of a grant, so the work is genuinely blocked; "
                         f"the {f['classification']} classification argues for "
                         f"limiting it."}


async def review_request(request: dict, model: ArchitectureModel, audit: list[dict],
                         history: list[dict], llm: LLM | None = None) -> dict:
    f = facts_for(request, model, audit, history)
    out, by_model = None, False
    if llm is not None:
        try:
            raw = await llm(_REVIEWER, json.dumps(f), _SCHEMA)
            parsed = json.loads(raw) if raw else None
            if (isinstance(parsed, dict)
                    and parsed.get("recommendation") in RECOMMENDATIONS
                    and parsed.get("reasoning")):
                out = {"recommendation": parsed["recommendation"],
                       "conditions": [_clip(c, 320) for c in parsed.get("conditions", [])][:4],
                       "reasoning": _clip(parsed["reasoning"], 1200)}
                by_model = True
        except Exception:
            out = None
    if out is None:
        out = _fallback(f)
    # A request with no recorded refusal behind it is never recommended for
    # approval, whatever the model wrote - that one is a fact, not a judgement.
    if not f["automatic_denials_for_missing_grant"] and out["recommendation"] != "decline":
        out = {**_fallback(f)}
        by_model = False
    return {**out, "by_model": by_model, "agent": AGENT_ID, "facts": f}
