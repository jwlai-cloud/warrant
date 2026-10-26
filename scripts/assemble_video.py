"""Assemble the demo video: footage + narration + cards + burned-in subtitles.

    python3 scripts/assemble_video.py [--demo-url URL]   # -> demo-video/warrant-demo.mp4

Inputs, produced by the other two scripts:
  demo-video/walkthrough.mp4, demo-video/shots.json   scripts/capture_demo.py
  demo-video/narration/*.wav, durations.json          scripts/narrate.py

Each narrated shot is fitted to its line: footage longer than the line is played
faster (never more than 2x), footage shorter is held on its last frame. Nothing
is reordered or staged. The result must be under the 3:00 hard limit or the
script refuses to write it.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
V = ROOT / "demo-video"
WORK = V / "build"
LIMIT = 178.0          # hard cap is 180s; keep 2s margin
LEAD = 0.35            # silence before each line
TAIL = 0.6             # breath after each line
MAX_SPEED = 2.0

# (shot, footage from, footage to, narration lines, crop)
# The refusal and the three findings land in the same instant, so they are one
# shot carrying both lines - split, the refusal was on screen under the
# findings line and not under its own.
# Crop drops the nav rail and enlarges the run panel ~12% for legibility.
RUN_CROP = "crop=1706:960:214:56"
LIVE = [("overview", "overview", "plan", ["hook", "problem"], None),
        ("plan", "plan", "decisions", ["plan"], RUN_CROP),
        ("decisions", "decisions", "negotiate", ["decisions", "findings"], RUN_CROP),
        ("negotiate", "negotiate", "approve", ["negotiate"], RUN_CROP),
        ("approve", "approve", "run2", ["approve"], RUN_CROP),
        ("run2", "run2", "end", ["reveal"], RUN_CROP)]
CARDS = [("topology", "topology"), ("proof", "proof"), ("close", "close")]
# Shots that need longer on screen than their line takes to say: the approval
# card holds the Steward Agent's review, which a viewer has to be able to read.
MIN_TARGET = {"approve": 13.0}


def sh(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def dur(p: Path) -> float:
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(p)]).decode().strip())


async def render_cards(demo_url: str) -> None:
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", headless=True)
        pg = await b.new_page(viewport={"width": 1920, "height": 1080})
        for card in ("proof", "close"):
            url = (ROOT / "demo" / "cards.html").as_uri() + f"?card={card}"
            if demo_url:
                url += "&url=" + demo_url
            await pg.goto(url)
            await pg.evaluate("() => document.fonts.ready")
            await pg.wait_for_timeout(400)
            await pg.screenshot(path=str(WORK / f"{card}.png"))
        await b.close()
    shutil.copy(ROOT / "docs" / "topology.png", WORK / "topology.png")


def line_audio(ids: list[str], name: str) -> tuple[Path, float]:
    """Concatenate one or more narration lines with a short gap between."""
    srcs = [V / "narration" / f"{i}.wav" for i in ids]
    out = WORK / f"{name}.wav"
    if len(srcs) == 1:
        shutil.copy(srcs[0], out)
    else:
        inputs, labels = [], []
        for k, s in enumerate(srcs):
            inputs += ["-i", str(s)]
            labels.append(f"[{k}:a]" + ("apad=pad_dur=0.6[p%d];" % k if k < len(srcs) - 1 else "anull[p%d];" % k))
        graph = "".join(labels) + "".join(f"[p{k}]" for k in range(len(srcs))) + \
            f"concat=n={len(srcs)}:v=0:a=1[a]"
        sh(*inputs, "-filter_complex", graph, "-map", "[a]", str(out))
    return out, dur(out)


def live_clip(name: str, start: float, end: float, audio: Path, alen: float,
              idx: int, crop: str | None = None) -> tuple[Path, float]:
    slice_len = end - start
    target = max(alen + LEAD + TAIL, slice_len / MAX_SPEED, MIN_TARGET.get(name, 0.0))
    speed = max(1.0, slice_len / target)
    hold = max(0.0, target - slice_len / speed)
    out = WORK / f"{idx:02d}-{name}.mp4"
    framing = f"{crop},scale=1920:1080:flags=lanczos," if crop else ""
    vf = (f"[0:v]{framing}setpts=PTS/{speed:.4f},fps=30,"
          f"tpad=stop_mode=clone:stop_duration={hold:.3f}[v]")
    af = f"[1:a]adelay={int(LEAD*1000)}|{int(LEAD*1000)},apad,atrim=0:{target:.3f}[a]"
    sh("-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(V / "walkthrough.mp4"),
       "-i", str(audio), "-filter_complex", vf + ";" + af, "-map", "[v]", "-map", "[a]",
       "-t", f"{target:.3f}", "-r", "30", "-c:v", "libx264", "-crf", "19",
       "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", str(out))
    print(f"  {name:<10} footage {slice_len:5.1f}s  line {alen:5.1f}s  -> "
          f"{target:5.1f}s  (x{speed:.2f}, hold {hold:.1f}s)")
    return out, target


def card_clip(card: str, audio: Path, alen: float, idx: int, extra: float) -> tuple[Path, float]:
    target = alen + LEAD + TAIL + extra
    frames = int(target * 30)
    out = WORK / f"{idx:02d}-{card}.mp4"
    if card == "topology":     # gentle push-in; 1.12 cropped the Steward Agent
        vf = (f"[0:v]scale=3840:2160,zoompan=z='min(1+0.00005*on,1.035)':"
              f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1920x1080:fps=30[v]")
    else:
        vf = f"[0:v]scale=1920:1080,zoompan=z=1:d={frames}:s=1920x1080:fps=30[v]"
    af = f"[1:a]adelay={int(LEAD*1000)}|{int(LEAD*1000)},apad,atrim=0:{target:.3f}[a]"
    sh("-i", str(WORK / f"{card}.png"), "-i", str(audio), "-filter_complex", vf + ";" + af,
       "-map", "[v]", "-map", "[a]", "-t", f"{target:.3f}", "-r", "30", "-c:v", "libx264",
       "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", str(out))
    print(f"  {card:<10} card                  line {alen:5.1f}s  -> {target:5.1f}s")
    return out, target


def srt_time(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s % 1) * 1000)):03d}"


def chunks(text: str, limit: int = 78) -> list[str]:
    """Split a line into subtitle-sized pieces on sentence/clause boundaries."""
    parts = re.split(r"(?<=[.?!:])\s+|(?<=,)\s+", text)
    out, cur = [], ""
    for p in parts:
        if cur and len(cur) + 1 + len(p) > limit:
            out.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}".strip()
    if cur:
        out.append(cur)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo-url", default="")
    args = ap.parse_args()

    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    narr = json.loads((ROOT / "demo" / "narration.json").read_text())
    text = {s["id"]: s["text"] for s in narr["shots"]}
    durs = json.loads((V / "narration" / "durations.json").read_text())
    shots = json.loads((V / "shots.json").read_text())
    asyncio.run(render_cards(args.demo_url))

    clips, subs, t, idx = [], [], 0.0, 0
    for key, frm, to, ids, crop in LIVE:
        start, end = shots[frm], shots[to]
        audio, alen = line_audio(ids, key)
        clip, length = live_clip(key, start, end, audio, alen, idx, crop)
        line_start = t + LEAD
        for i in ids:
            pieces = chunks(text[i])
            total_chars = sum(len(p) for p in pieces)
            for p in pieces:
                d = durs[i] * len(p) / total_chars
                subs.append((line_start, line_start + d, p))
                line_start += d
            line_start += 0.6
        clips.append(clip)
        t += length
        idx += 1
    for card, nid in CARDS:
        audio, alen = line_audio([nid], card)
        clip, length = card_clip(card, audio, alen, idx, extra=3.0 if card == "close" else 0.0)
        line_start = t + LEAD
        pieces = chunks(text[nid])
        total_chars = sum(len(p) for p in pieces)
        for p in pieces:
            d = durs[nid] * len(p) / total_chars
            subs.append((line_start, line_start + d, p))
            line_start += d
        clips.append(clip)
        t += length
        idx += 1

    if t > LIMIT:
        raise SystemExit(f"too long: {t:.1f}s > {LIMIT}s. Shorten narration in "
                         f"demo/narration.json and re-run narrate.py.")

    (WORK / "list.txt").write_text("".join(f"file '{c}'\n" for c in clips))
    raw = WORK / "joined.mp4"
    sh("-f", "concat", "-safe", "0", "-i", str(WORK / "list.txt"), "-c", "copy", str(raw))

    srt = WORK / "subs.srt"
    srt.write_text("".join(f"{n+1}\n{srt_time(a)} --> {srt_time(b)}\n{s}\n\n"
                           for n, (a, b, s) in enumerate(subs)))
    final = V / "warrant-demo.mp4"
    style = ("FontName=IBM Plex Sans,Fontsize=17,PrimaryColour=&H00FFFFFF,"
             "BackColour=&HB4161A23,BorderStyle=3,Outline=6,Shadow=0,MarginV=26")
    sh("-i", str(raw), "-vf", f"subtitles={srt}:force_style='{style}'",
       "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac",
       "-b:a", "160k", "-movflags", "+faststart", str(final))
    shutil.copy(srt, V / "warrant-demo.srt")
    length = dur(final)
    print(f"\n  final {length:.1f}s ({int(length // 60)}:{length % 60:04.1f})  "
          f"limit 180s  -> {final}")


if __name__ == "__main__":
    main()
