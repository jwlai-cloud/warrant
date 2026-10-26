# Demo video — story, beats and pipeline

**Hard limit: under 3:00** (Devpost rule: "less than three (3) minutes").
Current cut: **2:55**.

## Story order

Written against the judges' own advice (the "Will It Ship?" judging session,
21 Oct 2026): show the real problem for a real audience first, reach the "aha"
fast, and make every claim visible on screen, not only spoken.

| Part | Time | On screen | What it establishes |
|---|---|---|---|
| A · The problem | 0:00–0:32 | Problem card | Agents' work crosses departments. Today: over-grant (a service account that reads every salary) or block (the overpayment goes through). Nobody asks the owner; nobody can say why. |
| B · The system | 0:32–1:11 | Topology | Four agents, three departments, WARRANT between them: who plans, who decides (no model), who re-checks, who reviews, who approves. Stack: Nemotron on Token Factory, MCP. |
| C · The rights | 1:11–1:22 | Grant Matrix | Rights are explicit per capability × data entity; salaries are restricted, no grant means no. |
| D · Live demo | 1:22–2:37 | Console, two live runs | Plan → granted → refused with reason → three findings → grant request → Steward Agent review → human approval → re-run finds the hidden £290 overpayment. |
| E · Proof | 2:37–2:46 | Proof card | 40 review findings fixed, 90 tests, a prompt injection found by our own eval and published. |
| F · Close | 2:46–2:55 | Close card | One-line claim, live demo and code links. |

Every line of narration is a **beat** in `demo/narration.json`: the line, where
the page goes (`go`), which elements a ring highlights while it is said
(`spot`) and the caption on the ring (`label`). The ring dims the rest of the
screen, so a viewer's eye is where the voice is. A muted viewer still gets the
story from the captions on the rings; subtitles are not burned in (they covered
the console) but ship as `demo-video/warrant-demo.srt` for YouTube captions.

## Pipeline

```
python3 scripts/narrate.py          # voice each beat (Google TTS, personal project)
python3 scripts/capture_demo.py     # film the beats against live Nemotron
python3 scripts/assemble_video.py   # lay the voice at each beat, burn subtitles
```

- `capture_demo.py` holds each beat on screen for exactly its voiced length and
  records when each line starts (`demo-video/beats.json`), so picture and voice
  cannot drift. The live runs are real Token Factory calls; only the waiting
  between trace events is cut, never sped up.
- The overlay (`demo/spotlight.js`) is injected by the capture script only; the
  product never loads it.
- A take is **rejected** if the live model lands anywhere the narration does not
  say: first run must end at £2,561.00, second at £2,851.00, and the Steward
  Agent must recommend approval. Classification varies run to run (ADR-0009);
  re-run the capture.
- Once the demo is hosted: `python3 scripts/capture_demo.py --demo-url <url>`
  puts the real link on the close card.

## Numbers that must match everywhere

Video, README, Devpost write-up and the running demo must state the same
figures. Before submitting, grep for each.

| Figure | Value |
|---|---|
| Claims | 47, £11,179.80 |
| Before approval | 38 verified · 3 flagged · 6 blocked · £2,561.00 under query |
| After approval | 43 verified · 4 flagged · 0 blocked · £2,851.00 under query |
| The hidden one | CLM-3606, £290 allowance vs £255 band cap |
| Tests | 90 |
| Review | 40 confirmed findings, all fixed |
