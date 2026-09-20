"""Measure the entity classifier against labelled cases, on a real tier.

Run:
    set -a && . ./.env && set +a
    python evals/run_classify.py --tier fast
    python evals/run_classify.py --tier deep --json evals/results-deep.json

Why this exists, and why recall is printed first:

`engine/classify.py` narrows the callee's declared entities to those a purpose
requires. Intersecting with the declared set stops the model reaching an entity
the callee does not hold - but it does NOT stop the model dropping one it does.
A dropped entity's grant is never checked, so over-narrowing can turn a call
that should be refused into one that is granted.

    MISSED entity  -> security failure (call may be wrongly granted)
    EXTRA entity   -> usability failure (call may be wrongly refused)

Returning the full declared set every time scores perfect recall and is useless,
so `narrowing rate` is reported alongside: the share of cases where the model
actually removed something. A classifier is only earning its place when recall
is high AND narrowing is non-trivial.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from warrant.config import load_config                      # noqa: E402
from warrant.engine.classify import classify_entities       # noqa: E402
from warrant.model import load_model                        # noqa: E402
from warrant.providers import get_router                    # noqa: E402

CASES = Path(__file__).parent / "classify_cases.yaml"


async def _one(router, model, case, tier):
    declared = set(model.agents[case["callee"]].reads)
    expected = set(case["expected"])
    assert expected <= declared, (
        f"{case['id']}: expected {expected - declared} not declared by "
        f"{case['callee']} - the case is wrong, not the model"
    )
    t0 = time.perf_counter()
    got, used_tier, kind, _ = await classify_entities(
        router, model, case["callee"], case["purpose"], tier=tier
    )
    ms = (time.perf_counter() - t0) * 1000
    got = set(got)
    return {
        "id": case["id"],
        "purpose": case["purpose"][:60],
        "expected": sorted(expected),
        "got": sorted(got),
        "missed": sorted(expected - got),      # security-relevant
        "extra": sorted(got - expected),       # usability-relevant
        "exact": got == expected,
        "narrowed": got != declared,
        "tier": used_tier or tier,
        "provider": kind,
        "ms": round(ms, 1),
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="fast")
    ap.add_argument("--config", default=None)
    ap.add_argument("--json", default=None, help="write full results here")
    args = ap.parse_args()

    cfg = load_config(args.config)
    model = load_model(cfg.model_dir)
    router = get_router(cfg)
    cases = yaml.safe_load(CASES.read_text())["cases"]

    tcfg = cfg.tiers[args.tier]
    print(f"tier={args.tier} kind={tcfg.kind} model={tcfg.model}  ({len(cases)} cases)\n")

    rows = []
    for c in cases:
        r = await _one(router, model, c, args.tier)
        rows.append(r)
        flag = "  " if r["exact"] else ("!!" if r["missed"] else " ~")
        print(f"{flag} {r['id']:<28} got={','.join(r['got']) or '-':<45} "
              f"{r['ms']:>7.0f}ms")
        if r["missed"]:
            print(f"     MISSED {','.join(r['missed'])}  <- would be granted, not refused")
    await router.aclose()

    n = len(rows)
    tp = sum(len(set(r["expected"]) & set(r["got"])) for r in rows)
    fn = sum(len(r["missed"]) for r in rows)
    fp = sum(len(r["extra"]) for r in rows)
    recall = tp / (tp + fn) if tp + fn else 1.0
    precision = tp / (tp + fp) if tp + fp else 1.0
    lat = sorted(r["ms"] for r in rows)

    print("\n" + "=" * 66)
    print(f"  RECALL     {recall:>6.1%}   <- safety. {fn} entities missed across {n} cases")
    print(f"  precision  {precision:>6.1%}   <- usability. {fp} extra entities")
    print(f"  exact set  {sum(r['exact'] for r in rows) / n:>6.1%}")
    print(f"  narrowing  {sum(r['narrowed'] for r in rows) / n:>6.1%}   "
          f"<- 0% means it always returns everything and is doing nothing")
    print(f"  latency    p50 {statistics.median(lat):.0f}ms   "
          f"p95 {lat[int(len(lat) * 0.95) - 1]:.0f}ms")
    print("=" * 66)

    unsafe = [r for r in rows if r["missed"]]
    if unsafe:
        print(f"\n  {len(unsafe)} case(s) would have granted a call that should be refused:")
        for r in unsafe:
            print(f"    - {r['id']}: missed {','.join(r['missed'])}")

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"tier": args.tier, "kind": tcfg.kind, "model": tcfg.model,
             "recall": recall, "precision": precision,
             "exact": sum(r["exact"] for r in rows) / n,
             "narrowing": sum(r["narrowed"] for r in rows) / n,
             "p50_ms": statistics.median(lat), "rows": rows}, indent=1))
        print(f"\n  wrote {args.json}")

    return 1 if unsafe else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
