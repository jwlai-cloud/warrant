"""End-to-end test of the console in a real browser (Playwright + Chrome).

    python scripts/e2e_console.py          # needs `pip install playwright` and Chrome

Starts its own servers on the offline profile (stub models, no credits) and
drives every section the way a judge or a stranger would:

  judge (access code)   landing, "choose data first", each prepared scenario,
                        an uploaded CSV (good and bad), refusal -> owner ->
                        approval -> re-run, the guided demo and its tour,
                        Ask WARRANT, Grant Matrix, Agent Fleet, Runs,
                        Approvals, Audit, the "?" help, phone width
  stranger (no code)    recorded replay only: no live call is ever sent
  no code configured    local dev / video capture: the demo works as before
  daily cap reached     falls back to the replay with the notice

Exits non-zero if any check fails. Live behaviour (real Nemotron) is checked
separately against the hosted app; this run proves the console's wiring.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / ".venv/bin/python")
TEMPLATE = ROOT / "src/warrant/api/static/claims-template.csv"
FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ok    " if ok else "  FAIL  ") + name + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILS.append(name)


def server(port: int, **env) -> subprocess.Popen:
    e = dict(os.environ, WARRANT_CONFIG="config/warrant.offline.yaml", PYTHONPATH="src",
             WARRANT_AUDIT_PATH=tempfile.mkdtemp() + "/audit.jsonl", **env)
    e.pop("WARRANT_JUDGE_KEY", None) if "WARRANT_JUDGE_KEY" not in env else None
    return subprocess.Popen([PY, "-m", "uvicorn", "warrant.api.app:app", "--port", str(port)],
                            cwd=ROOT, env=e, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def idle(pg) -> None:
    await pg.wait_for_function("() => window.__warrant && !window.__warrant.state().running",
                               timeout=120_000)


async def run_audit(pg) -> None:
    before = await pg.evaluate("() => window.__warrant.state().runsDone")
    await pg.click('[data-view="overview"]')
    await pg.click("#ovRun")
    await pg.wait_for_function(f"() => window.__warrant.state().runsDone > {before}", timeout=120_000)
    await idle(pg)
    await asyncio.sleep(0.6)


def card(pg, title: str):
    """A scenario card by its exact title (descriptions mention other titles)."""
    return pg.locator(f"#scenList .scen:has(h3:text-is('{title}'))")


async def flagged(pg) -> set[str]:
    return set(await pg.locator("#findings .finding").evaluate_all(
        "els => els.map(e => e.getAttribute('data-claim'))"))


async def no_overflow(pg, label: str) -> None:
    wide = await pg.evaluate("() => document.documentElement.scrollWidth > innerWidth + 1")
    check(f"no sideways scroll at phone width: {label}", not wide)


async def judge(b, url: str) -> None:
    print("\njudge, with the access code")
    pg = await b.new_page(viewport={"width": 1440, "height": 900})
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.goto(url + "/?key=k"); await asyncio.sleep(1.5)
    check("landing offers data, Ask WARRANT and the guided demo",
          all([await pg.is_visible("#homeData"), await pg.is_visible("#homeAsk"), await pg.is_visible("#tourStart")]))
    await pg.click('#homeData'); await asyncio.sleep(0.8)
    check("no demo step bar outside the guided demo", not await pg.is_visible("#stepBar"))
    check("three prepared scenarios", await pg.locator("#scenList .scen").count() == 3)

    await pg.click('[data-view="overview"]'); await pg.click("#ovRun"); await asyncio.sleep(0.6)
    check("running before choosing data asks for data first",
          await pg.is_visible("#v-data") and "Choose the claims" in await pg.inner_text("#dataBanner"))

    # supplier review: no restricted data, no refusal
    await card(pg, "Supplier spend review").locator("button.btn.primary").click()
    await asyncio.sleep(1)
    check("supplier review loads on the Overview", "Supplier spend review" in await pg.inner_text("#ovTitle"))
    check("12 claim cells", await pg.locator("#ovCells i").count() == 12)
    await run_audit(pg)
    got = await flagged(pg)
    check("supplier review flags 2 over contract, a duplicate, an unknown supplier",
          got == {"INV-503", "INV-505", "INV-507", "INV-510"}, str(sorted(got)))
    check("no refusal in the supplier review", await pg.locator("#timeline li[data-kind='refused']").count() == 0)

    # travel and allowances: refusal -> owner -> approval -> re-run
    await pg.click('[data-view="data"]')
    await card(pg, "Travel and allowances").locator("button.btn.primary").click()
    await asyncio.sleep(1)
    await run_audit(pg)
    check("travel: salaries refused", await pg.locator("#timeline li[data-kind='refused']").count() >= 1)
    await pg.click('[data-view="approvals"]'); await asyncio.sleep(0.8)
    check("travel: a grant request is waiting for People & Culture", await pg.locator("#reqList button.ok").count() == 1)
    await pg.click("#reqList button.ok"); await asyncio.sleep(1.2)
    await run_audit(pg)
    got = await flagged(pg)
    check("travel after approval: over-band and unknown employee found",
          {"ALW-803", "ALW-805"} <= got, str(sorted(got)))

    # upload: bad, then the template
    await pg.click('[data-view="data"]')
    bad = Path(tempfile.mkdtemp()) / "bad.csv"
    bad.write_text("id,amount\nX,1\n")
    await pg.set_input_files("#csvFile", str(bad)); await pg.click("#csvBtn"); await asyncio.sleep(1)
    check("a bad file is refused with the reason", "missing columns" in await pg.inner_text("#csvMsg"))
    await pg.set_input_files("#csvFile", str(TEMPLATE)); await pg.fill("#csvName", "Template claims")
    await pg.click("#csvBtn"); await asyncio.sleep(1.2)
    check("the template uploads and opens the Overview", "Template claims" in await pg.inner_text("#ovTitle"))
    await run_audit(pg)
    got = await flagged(pg)
    check("uploaded claims are audited (unknown supplier queried)", "EX-006" in got, str(sorted(got)))

    # Ask WARRANT
    await pg.click('[data-view="ask"]'); await asyncio.sleep(0.6)
    await pg.fill("#askPurpose", ""); await pg.click("#askBtn")
    check("Ask WARRANT wants a purpose", "purpose" in await pg.inner_text("#askState"))
    await pg.click("#askPresets button:nth-child(2)"); await pg.click("#askBtn")
    await pg.wait_for_selector(".verdict", timeout=30_000); await asyncio.sleep(0.4)
    check("Ask WARRANT refuses salaries", (await pg.inner_text(".verdict b")) == "Refused")
    await pg.click(".owner button"); await pg.wait_for_selector(".owner .btn.primary", timeout=30_000)
    check("asking the owner gets a Steward Agent review", "recommends" in await pg.inner_text(".owner p"))
    await pg.click(".owner .btn.primary"); await asyncio.sleep(0.8)
    await pg.locator("#reqList button.ok").last.click(); await asyncio.sleep(1.2)
    await pg.click('[data-view="ask"]'); await pg.click("#askBtn"); await asyncio.sleep(1.5)
    check("after approval the same request is granted", (await pg.inner_text(".verdict b")) == "Granted")

    # the other sections
    await pg.click('[data-view="matrix"]'); await asyncio.sleep(0.6)
    check("Grant Matrix renders", await pg.locator("#matrix tbody tr").count() >= 3)
    await pg.click('[data-view="fleet"]'); await asyncio.sleep(0.6)
    check("Agent Fleet renders", await pg.locator("#fleet > *").count() >= 4)
    await pg.click('[data-view="audit"]'); await asyncio.sleep(0.8)
    check("Audit log has decisions", await pg.locator("#v-audit tbody tr").count() >= 3)
    await pg.click('[data-view="runs"]'); await asyncio.sleep(0.6)
    check("Runs shows the last trace", await pg.locator("#timeline li[data-kind]").count() >= 3)
    tip = "() => getComputedStyle(document.querySelector('#v-runs button.help'), '::after').display"
    await pg.hover("#v-runs button.help")
    check("the '?' help opens on hover", await pg.evaluate(tip) == "block")
    await pg.mouse.move(5, 5)
    await pg.evaluate("() => document.querySelector('#v-runs h1').setAttribute('tabindex', '-1')")
    await pg.focus("#v-runs h1"); await pg.keyboard.press("Tab")
    check("the '?' help opens on keyboard focus", await pg.evaluate(tip) == "block")

    # the guided demo: Northwind data, step bar, tour to the end
    await pg.click('[data-view="data"]')
    await card(pg, "Northwind Q3 audit").locator("button", has_text="Guided demo").click()
    await asyncio.sleep(1.5)
    check("guided demo shows the step bar", await pg.evaluate("() => document.body.classList.contains('is-demo')"))
    for _ in range(10):
        title = await pg.inner_text(".tour-card h3")
        if title.startswith(("Run the audit", "Run it again")):
            await pg.click("#ovRun"); await asyncio.sleep(1); await idle(pg); await asyncio.sleep(1.8)
        elif title.startswith("You are the steward"):
            await pg.click("#reqList button.ok"); await asyncio.sleep(2)
        else:
            await pg.click(".tour-card .btn.primary"); await asyncio.sleep(0.9)
    check("the tour ends on the £2,851 audit", "2,851" in await pg.inner_text("#riskChip"))

    await pg.set_viewport_size({"width": 390, "height": 844})
    for v in ("data", "overview", "ask", "runs", "approvals", "audit"):
        await pg.goto(f"{url}/#{v}"); await asyncio.sleep(0.8)
        await no_overflow(pg, v)
    check("judge: no page errors", not errs, "; ".join(errs)[:200])
    await pg.close()


async def stranger(b, url: str) -> None:
    print("\nstranger, no access code")
    pg = await b.new_page(viewport={"width": 1440, "height": 900})
    spend: list[str] = []
    pg.on("request", lambda r: spend.append(r.method + " " + r.url)
          if (r.method == "POST" or "/demo/stream" in r.url) else None)
    await pg.goto(url + "/#data"); await asyncio.sleep(1.5)
    locked = await pg.locator("#scenList .scen button.btn.primary:disabled").count()
    check("only the demo data is usable without the code", locked == 2)
    check("upload is locked without the code", await pg.is_disabled("#csvBtn"))
    await pg.click('[data-view="ask"]'); await asyncio.sleep(0.5)
    check("Ask WARRANT is locked without the code", await pg.is_disabled("#askBtn"))
    await run_audit(pg)
    r1 = await pg.inner_text("#riskChip")
    await pg.click('[data-view="approvals"]'); await pg.click("#reqList button.ok"); await asyncio.sleep(1)
    await run_audit(pg)
    check("the replay plays £2,561 then £2,851", "2,561" in r1 and "2,851" in await pg.inner_text("#riskChip"))
    check("a stranger never sends a live request", not spend, "; ".join(spend)[:200])
    await pg.close()


async def dev(b, url: str) -> None:
    print("\nno access code configured (local dev, video capture)")
    pg = await b.new_page(viewport={"width": 1440, "height": 900})
    await pg.goto(url + "/#overview"); await asyncio.sleep(1.5)
    await run_audit(pg)
    check("runs the Northwind demo without choosing data", "2,561" in await pg.inner_text("#riskChip"))
    check("demo step bar shown", await pg.is_visible("#stepBar"))
    await pg.close()


async def cap(b, url: str) -> None:
    print("\ndaily cap reached")
    pg = await b.new_page(viewport={"width": 1440, "height": 900})
    await pg.goto(url + "/?key=k"); await pg.goto(url + "/#data"); await asyncio.sleep(1.5)
    await card(pg, "Northwind Q3 audit").locator("button.btn.primary").click()
    await asyncio.sleep(1)
    await run_audit(pg)
    await pg.click('[data-view="overview"]'); await pg.click("#ovRun"); await asyncio.sleep(3); await idle(pg)
    check("after the cap: replay with the notice",
          "replay" in await pg.inner_text("#modePill") and await pg.is_visible("#capBanner"))
    await pg.close()


async def main() -> None:
    procs = [server(8051, WARRANT_JUDGE_KEY="k"), server(8052),
             server(8053, WARRANT_JUDGE_KEY="k", WARRANT_LIVE_DAILY_CAP="1")]
    time.sleep(4)
    try:
        async with async_playwright() as p:
            b = await p.chromium.launch(channel="chrome")
            await judge(b, "http://127.0.0.1:8051")
            await stranger(b, "http://127.0.0.1:8051")
            await dev(b, "http://127.0.0.1:8052")
            await cap(b, "http://127.0.0.1:8053")
            await b.close()
    finally:
        for pr in procs:
            pr.terminate()
    print(f"\n{'ALL PASSED' if not FAILS else str(len(FAILS)) + ' FAILED: ' + ', '.join(FAILS)}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    asyncio.run(main())
