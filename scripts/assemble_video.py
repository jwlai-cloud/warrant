"""Assemble the demo video: filmed beats + narration + burned-in subtitles.

    python3 scripts/assemble_video.py          # -> demo-video/warrant-demo.mp4

Inputs, produced by the other two scripts:
  demo-video/narration/*.wav, durations.json     scripts/narrate.py
  demo-video/walkthrough.mp4, beats.json         scripts/capture_demo.py

The capture already held every beat on screen for exactly the length of its
line, and recorded when each line starts. So assembly only lays each line of
narration at its beat's start and burns in subtitles: nothing is sped up,
reordered or re-timed here. The result must be under the 3:00 hard limit or the
script refuses to write it.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V = ROOT / "demo-video"
WORK = V / "build"
LIMIT = 178.0          # hard cap is 180s; keep 2s margin


def sh(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def dur(p: Path) -> float:
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(p)]).decode().strip())


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
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    text = {b["id"]: b["text"] for b in
            json.loads((ROOT / "demo" / "narration.json").read_text())["beats"]}
    durs = json.loads((V / "narration" / "durations.json").read_text())
    beats = json.loads((V / "beats.json").read_text())
    video = V / "walkthrough.mp4"
    length = dur(video)
    if length > LIMIT:
        raise SystemExit(f"too long: {length:.1f}s > {LIMIT}s. Shorten narration in "
                         f"demo/narration.json, re-run narrate.py and capture_demo.py.")

    inputs, mix, subs = [], [], []
    for k, b in enumerate(beats):
        inputs += ["-i", str(V / "narration" / f"{b['id']}.wav")]
        ms = int(b["start"] * 1000)
        mix.append(f"[{k + 1}:a]adelay={ms}|{ms}[a{k}]")
        pieces = chunks(text[b["id"]])
        total = sum(len(p) for p in pieces)
        t = b["start"]
        for p in pieces:
            d = durs[b["id"]] * len(p) / total
            subs.append((t, t + d, p))
            t += d
    graph = ";".join(mix) + ";" + "".join(f"[a{k}]" for k in range(len(beats))) + \
        f"amix=inputs={len(beats)}:normalize=0,apad,atrim=0:{length:.3f}[a]"

    srt = WORK / "subs.srt"
    srt.write_text("".join(f"{n+1}\n{srt_time(a)} --> {srt_time(b)}\n{s}\n\n"
                           for n, (a, b, s) in enumerate(subs)))
    final = V / "warrant-demo.mp4"
    style = ("FontName=IBM Plex Sans,Fontsize=17,PrimaryColour=&H00FFFFFF,"
             "BackColour=&HB4161A23,BorderStyle=3,Outline=6,Shadow=0,MarginV=26")
    sh("-i", str(video), *inputs, "-filter_complex", graph,
       "-map", "0:v", "-map", "[a]", "-vf", f"subtitles={srt}:force_style='{style}'",
       "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac",
       "-b:a", "160k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(final))
    shutil.copy(srt, V / "warrant-demo.srt")
    length = dur(final)
    print(f"  final {length:.1f}s ({int(length // 60)}:{length % 60:04.1f})  "
          f"limit 180s  -> {final}")


if __name__ == "__main__":
    main()
