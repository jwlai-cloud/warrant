"""Film the demo walkthrough against the real console and live Nemotron.

    python3 scripts/capture_demo.py            # -> demo-video/walkthrough.mp4

Starts the plane on a private port with config/warrant.yaml (real Token Factory
inference), resets the demo, then drives headless Chrome through the story in
docs/VIDEO.md: overview -> run -> refusal -> findings -> approve -> re-run ->
the hidden finding. Every frame is a real call; nothing is a preset.

Pacing is an edit decision list over the raw recording, not a slowed-down video.
A live run spends most of its ~35s waiting on the model, and sometimes delivers
several events at once (the three findings land together). So each trace event
gets a dwell time matched to its line of narration:

  - if the next event arrives later than that, the dead wait is CUT;
  - if it arrives sooner, the frame is HELD for the shortfall.

Everything on screen is real; only time between real frames is edited, and the
log reports exactly how much was cut and how much was held.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "demo-video"
PORT = 8020
URL = f"http://127.0.0.1:{PORT}/"
W, H = 1920, 1080

# Seconds each event stays on screen, matched to docs/VIDEO.md narration.
RUN1_DWELL = {"task": 3, "plan": 12, "granted": 7, "refused": 10, "replan": 6,
              "finding": 4.5, "audit": 2, "escalate": 7, "report": 3, "steward": 11}
RUN2_DWELL = {"task": 1, "plan": 2.5, "granted": 1.5, "refused": 1.5, "replan": 1.5,
              "finding": 2.5, "audit": 1.5, "escalate": 1.5, "report": 1.5,
              "steward": 1.5}
BATCH_CAP = 14       # a burst of simultaneous events never holds longer than this


def _env() -> dict:
    env = dict(os.environ, WARRANT_CONFIG="config/warrant.yaml", PYTHONPATH="src",
               WARRANT_AUDIT_PATH=str(OUT / "audit" / "warrant.jsonl"))
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith(("WARRANT_TF_API_KEY=", "WARRANT_TF_BASE_URL=")):
            k, v = line.split("=", 1)
            env[k] = v.strip().strip('"').strip("'")
    return env


class EDL:
    """Edit decision list over the raw recording: kept segments, each with an
    optional freeze-frame extension at its end."""

    def __init__(self):
        self.t0 = time.monotonic()
        self.cursor = 0.0
        self.segments: list[list[float]] = []      # [start, end, freeze]
        self.cut_total = 0.0
        self.held_total = 0.0

    def now(self) -> float:
        return time.monotonic() - self.t0

    def keep_until(self, t: float):
        if t > self.cursor + 0.05:
            self.segments.append([self.cursor, t, 0.0])
        self.cursor = max(self.cursor, t)

    def skip_until(self, t: float):
        if t > self.cursor:
            self.cut_total += t - self.cursor
            self.cursor = t

    def freeze(self, seconds: float):
        if self.segments and seconds > 0.05:
            self.segments[-1][2] += seconds
            self.held_total += seconds

    def out_time(self, t: float) -> float:
        """Map a raw-recording time to its time in the edited output. A time
        inside a cut maps to where the next kept segment starts."""
        acc = 0.0
        for a, b, frz in self.segments:
            if t < a:
                return acc
            if t <= b:
                return acc + (t - a)
            acc += (b - a) + frz
        return acc


async def run_live(page, edl: EDL, button: str, done_text: str, dwell: dict,
                   firsts: dict | None = None):
    """Press a run button, film the trace arriving, then pace it. `firsts`
    receives the raw time each kind of event first appeared."""
    await page.click(button)
    click_t = edl.now()
    edl.keep_until(click_t)
    arrivals: list[tuple[float, list[str]]] = []
    seen = 0
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        tags = await page.locator("#timeline > li:not(.tl-empty) .tl-k .tag").all_inner_texts()
        if len(tags) > seen:
            arrivals.append((edl.now(), [t.strip().lower() for t in tags[seen:]]))
            seen = len(tags)
        if done_text in await page.inner_text("#runState"):
            break
        await asyncio.sleep(0.12)
    await asyncio.sleep(1.0)
    end_t = edl.now()
    if firsts is not None:
        for t, kinds in arrivals:
            for k in kinds:
                firsts.setdefault(k, t)

    if not arrivals:
        edl.keep_until(end_t)
        return
    edl.keep_until(min(click_t + 1.2, arrivals[0][0]))
    edl.skip_until(arrivals[0][0])
    for i, (t, kinds) in enumerate(arrivals):
        want = min(BATCH_CAP, sum(dwell.get(k, 2) for k in kinds))
        nxt = arrivals[i + 1][0] if i + 1 < len(arrivals) else end_t
        if nxt - t >= want:
            edl.keep_until(t + want)
            edl.skip_until(nxt)
        else:
            # Freeze well before the next batch: polling notices a batch ~0.1-0.3s
            # after it starts painting, and rows fade in over 0.35s. Freezing at
            # nxt - 0.25 caught the refusal half-faded, held under the line
            # "Salaries, refused".
            stop = max(t + 0.1, nxt - 0.7)
            edl.keep_until(stop)
            edl.freeze(want - (stop - t))
            edl.skip_until(nxt)
    edl.keep_until(end_t)


async def main() -> None:
    OUT.mkdir(exist_ok=True)
    for d in ("audit", "raw"):          # cleared at the START of a take, not the end
        shutil.rmtree(OUT / d, ignore_errors=True)
    server = subprocess.Popen(
        [str(ROOT / ".venv/bin/python"), "-m", "uvicorn", "warrant.api.app:app",
         "--port", str(PORT)], cwd=ROOT, env=_env(),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    marks: dict[str, float] = {}
    errors: list[str] = []
    try:
        await asyncio.sleep(4)
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="chrome", headless=True)
            ctx = await browser.new_context(
                viewport={"width": W, "height": H}, device_scale_factor=1,
                record_video_dir=str(OUT / "raw"), record_video_size={"width": W, "height": H})
            page = await ctx.new_page()
            edl = EDL()
            page.on("pageerror", lambda e: errors.append(str(e)))

            async def hold(seconds: float):
                await asyncio.sleep(seconds)
                edl.keep_until(edl.now())

            await page.goto(URL)
            await page.evaluate("() => document.fonts.ready")
            await page.evaluate("() => fetch('/v1/demo/reset', {method: 'POST'})")
            await page.reload()
            await page.evaluate("() => document.fonts.ready")
            await asyncio.sleep(0.8)
            edl.skip_until(edl.now())                  # page load is not story

            # shots 1-2 (0:00-0:30): the problem
            marks["overview"] = edl.now()
            await hold(28)

            # shots 3-7 (0:30-1:35): the first run, live
            marks["run1"] = edl.now()
            firsts: dict[str, float] = {}
            await run_live(page, edl, "#ovRun", "verified", RUN1_DWELL, firsts)
            run1_risk = await page.inner_text("#riskChip")
            await page.evaluate("() => document.querySelector('#summaryBox').scrollIntoView({behavior: 'smooth', block: 'center'})")
            await hold(4)

            # shot 8 (1:35-1:55): the human approves
            marks["approve"] = edl.now()
            await page.click('[data-view="approvals"]')
            await hold(7)
            await page.hover("text=Approve as People & Culture")
            await hold(1.5)
            await page.click("text=Approve as People & Culture")
            await hold(3)
            await page.click('[data-view="matrix"]')
            await hold(6)

            # shot 9 (1:55-2:15): run again, the hidden finding
            marks["run2"] = edl.now()
            await page.click('[data-view="overview"]')
            await hold(1.5)
            await run_live(page, edl, "#ovRun", "complete", RUN2_DWELL)
            await page.evaluate("() => { const f = [...document.querySelectorAll('#findings .finding')].find(x => x.textContent.includes('CLM-3606')); if (f) f.scrollIntoView({behavior: 'smooth', block: 'center'}); }")
            await hold(6)
            await page.click('[data-view="overview"]')
            await hold(4)
            marks["end"] = edl.now()

            result = {"run1_risk": run1_risk,
                      "risk": await page.inner_text("#kRisk"),
                      "checks": [await page.inner_text(f"#ovC{i}") for i in range(1, 5)]}
            raw_path = await page.video.path()
            await ctx.close()
            await browser.close()
    finally:
        server.terminate()
        # The audit log is KEPT: when a take comes out wrong it is the only
        # record of what the agent actually asked for and what WARRANT decided.

    # The narration states these figures. A take that ends anywhere else would
    # put a wrong number on screen under a voice saying the right one, so it is
    # rejected rather than assembled. Classification varies run to run (see
    # ADR-0009), so an occasional take differs; re-run the capture.
    expected_risk = "£2,851.00"
    if result["run1_risk"] != "£2,561.00":
        raise SystemExit(f"take rejected: first run ended at {result['run1_risk']}, "
                         f"narration expects £2,561.00. See {OUT / 'audit'}.")
    if result["risk"] != expected_risk or any("FLAGGED" not in c.upper()
                                               for c in result["checks"]):
        raise SystemExit(
            f"take rejected: ended at {result['risk']} with checks {result['checks']}, "
            f"narration expects {expected_risk} and all four checks flagged. "
            f"See {OUT / 'audit'} for what happened; re-run to take again.")

    filters, labels = [], []
    for i, (a, b, frz) in enumerate(edl.segments):
        # fps=30 BEFORE tpad: Playwright records variable frame rate, and on a
        # VFR stream tpad's clone silently adds nothing (measured: a 2s slice
        # with a 3s hold came out 2.0s long without it, 5.0s with it).
        f = f"[0:v]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS,fps=30"
        if frz > 0:
            f += f",tpad=stop_mode=clone:stop_duration={frz:.3f}"
        filters.append(f + f"[v{i}]")
        labels.append(f"[v{i}]")
    (OUT / "edl.json").write_text(json.dumps({"raw": str(raw_path),
                                               "segments": edl.segments}, indent=1))

    # Where each narrated shot starts in the EDITED footage, for the assembler.
    decisions = min(firsts.get(k, 1e9) for k in ("granted", "refused"))
    raw_bounds = [
        ("overview", marks["overview"]),
        ("plan", firsts.get("plan", marks["run1"])),
        ("decisions", decisions),
        ("findings", firsts.get("finding", decisions)),
        ("negotiate", firsts.get("escalate", firsts.get("finding", decisions))),
        ("approve", marks["approve"]),
        ("run2", marks["run2"]),
        ("end", marks["end"]),
    ]
    shots = {name: round(edl.out_time(t), 3) for name, t in raw_bounds}
    (OUT / "shots.json").write_text(json.dumps(shots, indent=1))
    graph = ";".join(filters) + ";" + "".join(labels) + f"concat=n={len(labels)}:v=1:a=0[out]"
    final = OUT / "walkthrough.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw_path,
                    "-filter_complex", graph, "-map", "[out]", "-r", "30",
                    "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(final)],
                   check=True)

    def dur(path) -> float:
        return float(subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)]).decode().strip())

    expected = sum(b - a + f for a, b, f in edl.segments)
    got = dur(final)
    if abs(got - expected) > 1.0:
        raise SystemExit(f"assembly wrong: expected {expected:.1f}s, got {got:.1f}s")
    print(json.dumps({
        "expected_seconds": round(expected, 1),
        "raw_seconds": round(dur(raw_path), 1),
        "final_seconds": round(dur(final), 1),
        "waiting_cut_seconds": round(edl.cut_total, 1),
        "frames_held_seconds": round(edl.held_total, 1),
        "segments": len(edl.segments),
        "marks_raw": {k: round(v, 1) for k, v in marks.items()},
        "final_state": result,
        "page_errors": errors or "none",
        "output": str(final),
    }, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
