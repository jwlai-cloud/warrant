"""Deep-tier step: turn a decision's structured reasons into the sentence a
human reads. The narrative never changes the outcome - it explains it."""
from __future__ import annotations

from ..providers import TierRouter
from .decision import WarrantDecision

_SYSTEM = (
    "You are an enterprise architecture assistant. Given a completed "
    "authorization decision and its structured reasons, write ONE short "
    "paragraph (max 60 words) explaining the outcome to an engineer. Reference "
    "the capability, the data entity and the owning organisation by name. State "
    "the outcome exactly as given - never contradict, soften or reverse it. No "
    "preamble, no bullet points."
)


def _fallback(d: WarrantDecision) -> str:
    if d.granted:
        return (f"{d.headline()}. All data entities touched are covered by "
                f"existing grants.")
    missing = ", ".join(f"{e}" for _, e in d.missing_grants) or "unknown"
    return f"{d.headline()}. No grant covers: {missing}."


async def write_justification(router: TierRouter, d: WarrantDecision) -> WarrantDecision:
    reasons = "\n".join(f"[{r.code}] {r.detail}" for r in d.reasons)
    user = (
        f"Outcome: {'GRANTED' if d.granted else 'DENIED'}\n"
        f"Caller: {d.request.caller_agent}\n"
        f"Callee: {d.request.callee_agent}\n"
        f"Purpose: {d.request.purpose or '(not stated)'}\n"
        f"Data entities touched: {', '.join(d.entities_touched) or '(none)'}\n\n"
        f"Structured reasons:\n{reasons}"
    )
    try:
        c = await router.complete("deep", _SYSTEM, user)
        d.justification = c.text.strip() or _fallback(d)
        # Do NOT touch tier_used - that records which tier classified, and
        # classification is the only model step that can change the outcome.
        d.justify_tier = c.tier
        d.justify_provider = c.provider_kind
        d.justify_ms = c.latency_ms
    except Exception:
        d.justification = _fallback(d)
    return d
