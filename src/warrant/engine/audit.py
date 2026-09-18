"""Append-only audit log. Every decision is recorded, granted or not -
the refusals are the point."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .decision import WarrantDecision


def record(path: str | Path, d: WarrantDecision) -> dict:
    entry = {
        "id": d.id,
        "issued_at": d.issued_at,
        "expires_at": d.expires_at,
        "granted": d.granted,
        "caller": d.request.caller_agent,
        "callee": d.request.callee_agent,
        "purpose": d.request.purpose,
        "entities_touched": d.entities_touched,
        "missing_grants": [{"capability": c, "data_entity": e}
                           for c, e in d.missing_grants],
        "reasons": [asdict(r) for r in d.reasons],
        "justification": d.justification,
        "tier_used": d.tier_used,
        "provider_kind": d.provider_kind,
        "latency_ms": round(d.latency_ms, 2),
        "justify_tier": d.justify_tier,
        "justify_provider": d.justify_provider,
        "justify_ms": round(d.justify_ms, 2),
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry


def read_all(path: str | Path, limit: int = 100) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(ln) for ln in lines[-limit:]][::-1]
