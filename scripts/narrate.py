"""Generate the demo narration with Google Cloud Text-to-Speech.

    python3 scripts/narrate.py                 # -> demo-video/narration/<shot>.wav

Reads demo/narration.json. Uses the PERSONAL gcloud account and project, never
the active one - the active gcloud account on this machine is an employer
account, and a personal hackathon must not bill or log to it. Override with
NARRATE_ACCOUNT / NARRATE_PROJECT.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "demo-video" / "narration"
ACCOUNT = os.environ.get("NARRATE_ACCOUNT", "junwei.lai@gmail.com")
PROJECT = os.environ.get("NARRATE_PROJECT", "agent-era")


def main() -> None:
    spec = json.loads((ROOT / "demo" / "narration.json").read_text())
    voice = os.environ.get("NARRATE_VOICE", spec["voice"])
    token = subprocess.check_output(
        ["gcloud", "auth", "print-access-token", "--account", ACCOUNT]).decode().strip()
    OUT.mkdir(parents=True, exist_ok=True)
    durations = {}
    for shot in spec["beats"]:
        body = json.dumps({
            "input": {"text": shot["text"]},
            "voice": {"languageCode": voice[:5], "name": voice},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 48000,
                            "speakingRate": spec.get("rate", 1.0)},
        }).encode()
        req = urllib.request.Request(
            "https://texttospeech.googleapis.com/v1/text:synthesize", data=body,
            headers={"Authorization": f"Bearer {token}",
                     "x-goog-user-project": PROJECT,
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            audio = base64.b64decode(json.loads(r.read())["audioContent"])
        path = OUT / f"{shot['id']}.wav"
        path.write_bytes(audio)
        durations[shot["id"]] = float(subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)]).decode().strip())
    (OUT / "durations.json").write_text(json.dumps(durations, indent=1))
    total = sum(durations.values())
    for k, v in durations.items():
        print(f"  {k:<10} {v:5.1f}s")
    print(f"  {'total':<10} {total:5.1f}s   voice {voice}, project {PROJECT}")


if __name__ == "__main__":
    main()
