"""Film the demo video against the real console and live Nemotron.

    python3 scripts/narrate.py                 # first: voices every beat
    python3 scripts/capture_demo.py [--demo-url URL]
        # -> demo-video/walkthrough.mp4, demo-video/beats.json

The video is a list of beats in demo/narration.json. Each beat is one line of
narration plus what is on screen while it is said: 'go' moves the page (a card,
the topology, a console view, a live run, the approval click), 'spot' rings the
elements the line is about and dims the rest (demo/spotlight.js, injected here
and never shipped in the product). Each beat stays on screen for exactly the
length of its voiced line, so picture and voice cannot drift apart; the start
time of every beat is written to beats.json for the assembler.

The two live runs call real Token Factory inference. A run spends most of its
time waiting on the model, so the wait between trace events is CUT from the
recording (an edit decision list), never sped up: every frame is a real frame,
and the log reports how much waiting was cut.
"""
from __future__ import annotations

import argparse
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
URL = f"http://127.0.0.1:{PORT}/#overview"   # the console; "/" alone is the landing page
# The console is zoomed 1.25x inside a 1920x1080 page, so its text reads 25%
# larger on video while staying sharp (Playwright's recorder ignores
# device_scale_factor). The cards and topology are drawn for 1920 and are not.
CONSOLE_ZOOM = 1.25
GAP = 0.3             # breath between beats
SETTLE = 0.35         # the ring starts moving before its line starts

# Seconds each trace event stays on screen while a run streams in. The run
# beats only need the trace to visibly fill; the beats after them walk it.
RUN1_DWELL = {"plan": 1.0, "refused": 1.0}
RUN2_DWELL: dict = {}
DEFAULT_DWELL = {1: 0.45, 2: 0.3}
BATCH_CAP = 1.8


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

    def length(self) -> float:
        """Length of the edited output so far."""
        return sum(b - a + f for a, b, f in self.segments)

    def out_now(self) -> float:
        """Edited time of this instant, if everything since the cursor is kept."""
        return self.length() + (self.now() - self.cursor)


async def run_live(page, edl: EDL, button: str, done_text: str, dwell: dict, run: int):
    """Press a run button and film the trace arriving, cutting the waits
    between events down to each event's dwell."""
    await page.click(button)
    click_t = edl.now()
    edl.keep_until(click_t)
    arrivals: list[tuple[float, list[str]]] = []
    seen = 0
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        kinds = await page.eval_on_selector_all(
            "#timeline > li[data-kind]", "els => els.map(e => e.dataset.kind)")
        if len(kinds) > seen:
            arrivals.append((edl.now(), kinds[seen:]))
            seen = len(kinds)
        if done_text in await page.inner_text("#runState"):
            break
        await asyncio.sleep(0.12)
    await asyncio.sleep(1.0)
    end_t = edl.now()
    if not arrivals:
        edl.keep_until(end_t)
        return
    edl.keep_until(min(click_t + 1.2, arrivals[0][0]))
    edl.skip_until(arrivals[0][0])
    for i, (t, kinds) in enumerate(arrivals):
        want = min(BATCH_CAP, sum(dwell.get(k, DEFAULT_DWELL[run]) for k in kinds))
        nxt = arrivals[i + 1][0] if i + 1 < len(arrivals) else end_t
        if nxt - t >= want:
            edl.keep_until(t + want)
            edl.skip_until(nxt)
        else:
            # Freeze well before the next batch lands: rows fade in over 0.35s,
            # and a later poll can catch the next row half-painted.
            stop = max(t + 0.1, nxt - 0.7)
            edl.keep_until(stop)
            edl.freeze(want - (stop - t))
            edl.skip_until(nxt)
    edl.keep_until(end_t)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo-url", default="")
    args = ap.parse_args()

    spec = json.loads((ROOT / "demo" / "narration.json").read_text())
    durs = json.loads((OUT / "narration" / "durations.json").read_text())
    missing = [b["id"] for b in spec["beats"] if b["id"] not in durs]
    if missing:
        raise SystemExit(f"no narration for {missing}: run scripts/narrate.py first")

    OUT.mkdir(exist_ok=True)
    for d in ("audit", "raw"):          # cleared at the START of a take, not the end
        shutil.rmtree(OUT / d, ignore_errors=True)
    server = subprocess.Popen(
        [str(ROOT / ".venv/bin/python"), "-m", "uvicorn", "warrant.api.app:app",
         "--port", str(PORT)], cwd=ROOT, env=_env(),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cards = (ROOT / "demo" / "cards.html").as_uri()
    topo = (ROOT / "docs" / "architecture.html").as_uri()
    beats: list[dict] = []
    errors: list[str] = []
    result: dict = {}
    try:
        await asyncio.sleep(4)
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="chrome", headless=True)
            ctx = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                record_video_dir=str(OUT / "raw"),
                record_video_size={"width": 1920, "height": 1080})
            await ctx.add_init_script(path=str(ROOT / "demo" / "spotlight.js"))
            page = await ctx.new_page()
            edl = EDL()
            page.on("pageerror", lambda e: errors.append(str(e)))

            async def load(url: str):
                """Navigate without filming the load."""
                edl.keep_until(edl.now())
                await page.goto(url)
                await page.evaluate("() => document.fonts.ready")
                if url.startswith("http"):
                    await page.evaluate(f"() => {{ document.body.style.zoom = {CONSOLE_ZOOM} }}")
                await asyncio.sleep(0.6)
                edl.skip_until(edl.now())

            async def view(name: str):
                await page.click(f'[data-view="{name}"]')
                await asyncio.sleep(0.5)

            async def ring(targets, label=None):
                first = next((t for t in targets or [] if isinstance(t, str)), None)
                if first and await page.evaluate("s => __reveal(s)", first):
                    await asyncio.sleep(0.15)
                if not await page.evaluate("([t, l]) => __spot(t, l)", [targets, label]) and targets:
                    raise SystemExit(f"spotlight target not on the page: {targets}")

            # A clean slate: no grants approved, no audit history.
            await load(URL)
            await page.evaluate("() => fetch('/v1/demo/reset', {method: 'POST'})")

            for b in spec["beats"]:
                go = b.get("go", "")
                start = None
                if go.startswith("card:"):
                    q = f"?card={go[5:]}" + (f"&url={args.demo_url}" if args.demo_url else "")
                    await load(cards + q)
                elif go == "topology":
                    await load(topo)
                elif go.startswith("app:"):
                    await load(URL)
                    await view(go[4:])
                elif go.startswith("view:"):
                    await page.evaluate("() => __spot(null)")
                    await view(go[5:])
                elif go in ("run", "rerun"):
                    # The line starts as the button is ringed; the run plays under it.
                    first = go == "run"
                    if not first:
                        await page.evaluate("() => __spot(null)")
                        await view("runs")
                    start = edl.out_now()
                    btn = "#ovRun" if first else "#runBtn"
                    await ring([btn], "Run audit" if first else "Run again")
                    await asyncio.sleep(0.9)
                    await page.evaluate("() => __spot(null)")
                    await run_live(page, edl, btn, "verified" if first else "complete",
                                   RUN1_DWELL if first else RUN2_DWELL, 1 if first else 2)
                    result["run1_risk" if first else "run2_risk"] = await page.inner_text("#riskChip")
                elif go == "approve":
                    start = edl.out_now()
                    result["steward"] = await page.inner_text("#reqList .review-head")
                    ok = page.locator("#reqList .req button.ok").first
                    await ok.scroll_into_view_if_needed()
                    await ring(["#reqList .req button.ok"], "Approve as People & Culture")
                    await asyncio.sleep(1.4)
                    await ok.click()
                    await asyncio.sleep(0.8)

                lead = 0.25          # an action beat's line starts with its button
                if start is None:
                    edl.keep_until(edl.now())
                    start, lead = edl.length(), SETTLE
                await ring(b.get("spot"), b.get("label"))
                await asyncio.sleep(SETTLE)
                edl.keep_until(edl.now())
                # Hold until the line has been said, in EDITED time: a run beat
                # has already used some of its line while the trace filled.
                remaining = durs[b["id"]] + GAP + lead - (edl.length() - start)
                if remaining > 0:
                    await asyncio.sleep(remaining)
                    edl.keep_until(edl.now())
                beats.append({"id": b["id"], "start": round(start + lead, 3),
                              "end": round(edl.length(), 3)})

            await asyncio.sleep(2.5)                # let the close card breathe
            edl.keep_until(edl.now())
            raw_path = await page.video.path()
            await ctx.close()
            await browser.close()
    finally:
        server.terminate()
        # The audit log is KEPT: when a take comes out wrong it is the only
        # record of what the agent actually asked for and what WARRANT decided.

    # The narration states these. A take where the live model did something
    # else would put a wrong claim on screen under a voice saying the right
    # one, so it is rejected; classification varies run to run (ADR-0009).
    problems = []
    if result.get("run1_risk") != "£2,561.00":
        problems.append(f"first run ended at {result.get('run1_risk')}, narration says £2,561.00")
    if result.get("run2_risk") != "£2,851.00":
        problems.append(f"second run ended at {result.get('run2_risk')}, narration implies £2,851.00")
    if "approve" not in result.get("steward", "").lower():
        problems.append(f"Steward Agent said {result.get('steward')!r}, narration says it recommends approval")
    if problems:
        raise SystemExit("take rejected: " + "; ".join(problems) + f". See {OUT / 'audit'}.")

    filters, labels = [], []
    for i, (a, b, frz) in enumerate(edl.segments):
        # fps=30 BEFORE tpad: Playwright records variable frame rate, and on a
        # VFR stream tpad's clone silently adds nothing.
        f = f"[0:v]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS,fps=30"
        if frz > 0:
            f += f",tpad=stop_mode=clone:stop_duration={frz:.3f}"
        filters.append(f + f"[v{i}]")
        labels.append(f"[v{i}]")
    (OUT / "edl.json").write_text(json.dumps({"raw": str(raw_path),
                                               "segments": edl.segments}, indent=1))
    (OUT / "beats.json").write_text(json.dumps(beats, indent=1))
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

    expected = edl.length()
    got = dur(final)
    if abs(got - expected) > 1.0:
        raise SystemExit(f"assembly wrong: expected {expected:.1f}s, got {got:.1f}s")
    print(json.dumps({
        "final_seconds": round(got, 1),
        "raw_seconds": round(dur(raw_path), 1),
        "waiting_cut_seconds": round(edl.cut_total, 1),
        "frames_held_seconds": round(edl.held_total, 1),
        "final_state": result,
        "page_errors": errors or "none",
        "output": str(final),
    }, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
