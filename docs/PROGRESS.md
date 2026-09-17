# Progress log

## 2026-09-17 — session 2 (fast-tier gate: verification, not deployment)

### Done this session
- Read the hackathon rules page directly. Confirmed: deadline 30 Oct 2026
  10:00 PDT, judging 1–15 Dec, four equally-weighted criteria, "runs on Nebius"
  = Token Factory inference API **or** Serverless Jobs/Endpoints/DevPods, at
  least one NVIDIA open model, demo video **under 3 minutes**. New facts not
  previously logged: Grand Prize $20k / 2nd $10k / 3rd $6k, per-track NVIDIA
  Jetson Orin Nano, a **$3,000 "Best Tavily Use"** prize, 20× $500 city prizes,
  and a **Stage One pass/fail viability screen before the scored round**.
- Resolved all four `TODO(verify)` items from primary sources:
  - **Token Factory base URL** — `https://api.tokenfactory.nebius.com/v1/` is
    correct. The guess held. Key env var in Nebius' own docs is `NEBIUS_API_KEY`.
  - **`reasoning_budget` wire format** — the scaffold was **wrong**. It is not a
    `chat_template_kwargs` key and never was; that dict carries `enable_thinking`
    only. The real per-request knob is vLLM's top-level `thinking_token_budget`
    sampling parameter. Fixed in `openai_compat.py`, with a test that fails if it
    regresses.
  - **Nano model IDs** — `nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16` exists and needs
    **vLLM ≥ 0.15.1** plus `--mamba_ssm_cache_dtype float32`. The 30B-A3B needs
    ≥ 0.12.0 and wants H100/A100, not an L40S.
  - **Serverless Endpoint flags** — preset is `1gpu-8vcpu-32gb` (the scaffold's
    `1gpu-16vcpu-200gb` does not exist), platform `gpu-l40s-a` was right. Needs
    `--container-command`, `--shm-size`, `--auth token --token`, and
    `--subnet-id` if the project has more than one subnet.
- Rewrote `scripts/deploy_vllm_endpoint.sh` against the verified flag set.
- Added `scripts/smoke_fast_tier.sh` — proves the endpoint before WARRANT is
  pointed at it. This matters more than it sounds: when the reasoning parser
  misfires, `content` comes back `null` and `classify.py` fails closed, so a
  dead fast tier is indistinguishable from a working one at the CLI.
- ADR-0006 written: the fast tier serves no tools and sets no `--reasoning-config`.
- Swept ARCHITECTURE.md, LEARNING.md, ADR-0002 and `.env.example` for the now-false
  `reasoning_budget` claim.
- **8 tests passing** (was 7).

### The 20 Sep gate — called, not quietly fought
**We will not hit the gate as originally written, and the gate was wrong.**

Two independent reasons:

1. **No Nebius CLI, credentials or account wired up on this machine.** No
   `nebius` binary, no `~/.nebius`, nothing in the environment. Nothing can be
   deployed until that exists. This is the actual blocker and it is a human step.
2. **The gate's success condition is currently unachievable upstream.** It asked
   to confirm the `nano_v3` reasoning parser, the `qwen3_coder` tool parser and
   the reasoning budget all work *together*. vLLM issue **#39103 is open**: on
   Nemotron 3, `--reasoning-parser` combined with `--reasoning-config` returns
   `content: null` with every token in `reasoning_content`, and no workaround is
   posted. Separately, the tool parser + `nano_v3` combination was reported
   broken on vLLM 0.12.0 and fixed only on a nightly (PR #30671).

**But the gate over-specified the requirement.** WARRANT issues no tool calls
anywhere — `classify.py` constrains output with `response_format: json_schema`.
So the tool parser is unnecessary, and the budget can be applied per-request
instead of via the flag that triggers #39103. With both dropped, self-hosting is
still viable and routes around both known bugs. The gate is restated in ADR-0006
as: *the fast tier returns parseable schema-constrained JSON with a bounded
reasoning budget.*

**The fallback got cheaper than it was when the gate was set.** Nemotron 3 Nano
30B A3B is **already served on Token Factory** at roughly $0.05/$0.20 per 1M
tokens. Under ADR-0002 moving the fast tier there is a config edit. So the cost
of abandoning self-hosting is now close to zero, which means the deadline should
be enforced harder, not softer: it is no longer a risk worth days.

### Next (priority order)
1. **Install and authenticate the Nebius CLI** (human step, ~15 min, blocks
   everything on this work item):
   `curl -sSL https://storage.eu-north1.nebius.cloud/cli/install.sh | bash`
   then `exec -l $SHELL` and `nebius profile create`. Confirm credits exist.
2. **Deploy and smoke the fast tier**: `AUTH_TOKEN=$(openssl rand -hex 16)
   scripts/deploy_vllm_endpoint.sh`, then `scripts/smoke_fast_tier.sh`, then
   `warrant ask`. **Timebox: one session.** If the smoke script does not pass in
   that session, set `tiers.fast.kind: token_factory` and move on — self-hosting
   becomes the benchmark appendix, exactly as planned.
3. **Build the product surface.** Design is 25% and is still at zero. This is now
   the largest unaddressed scoring risk in the project, larger than the fast tier
   ever was.
4. Two LangGraph demo agents that visibly change behaviour on a refusal (ADR-0005).
5. OpenShell integration — emit the computed grant as an enforced policy.
6. Move the audit log to Nebius Object Storage.
7. Benchmark self-hosted vs Token Factory. Note when writing this up: the
   thinking budget binds on vLLM only, so a deep-tier latency is not evidence
   the budget applied.

### Open questions / blocked on
- **Does a Nebius account with credits exist yet?** Everything in item 1 assumes
  yes. Unverified.
- **Exact Token Factory model ID for Nemotron 3 Nano 30B.** The Nano is confirmed
  in the catalogue; the ID string is not. Super is `nvidia/nemotron-3-super-120b-a12b`.
  Read it off the console rather than guessing the pattern.
- **`--subnet-id`** is required if the project has multiple subnets. Unknown until
  the account exists; the deploy script omits it and will need it if create fails.
- **CPU-only endpoint preset and hourly rate** for the always-on API/UI tier.
  Still not published in the docs we could read. Ask in the hackathon Discord.
- **Does Nano 4B classify well enough?** Unchanged and unanswerable until item 2
  runs. The 30B alternative needs an H100/A100, which changes the cost model.
- **$3,000 "Best Tavily Use" prize** — WARRANT has no web-search surface and
  should probably not grow one just to chase it. Noted, not pursued.

### Changed since last entry
- `reasoning_budget` as a wire field is gone; it was never real. The config key
  survives as a logical dial mapped to `thinking_token_budget`.
- Fast tier scope narrowed: no tool calling on the sovereign tier (ADR-0006).
- Token Factory fallback for the fast tier is now a cheap, verified option rather
  than a hypothetical one.

## 2026-09-17 — session 1 (scaffold)

### Done this session
- Idea selection completed with a competitive audit; three earlier candidates
  dropped on evidence (see ADR-0001).
- Repo scaffolded: `src/warrant/` with config, model, providers, engine, api, cli.
- Architecture model implemented as a TOGAF metamodel subset (ADR-0003), loaded
  from five YAML files in `config/model/`, validated on load with hard failure
  on dangling references.
- Deterministic decision engine implemented (ADR-0004) — pure function, no I/O.
- Pluggable provider layer implemented (ADR-0002): one OpenAI-compatible client
  for both vLLM and Token Factory, plus a `mock` provider and a `TierRouter`
  with fallback.
- FastAPI surface: `POST /v1/warrant`, `GET /v1/audit`, `GET /v1/model`, `GET /healthz`.
- CLI: `warrant ask | log | validate | serve`.
- Append-only JSONL audit log.
- **7 tests passing** in <1s with zero network, including the fallback test that
  proves stopping the GPU endpoint degrades rather than breaks.
- Demo scenario works end to end offline: `expense-auditor -> inventory-reconciler`
  is refused because Expense Management holds no grant to `Employee.Compensation`.
- Five ADRs written.

### In progress (not done, don't claim it is)
- Nothing. The scaffold is complete and green; no partial work is checked in.

### Next (priority order)
1. **Stand up the fast tier — this is the 20 Sep gate.** Deploy the
   `vllm/vllm-openai` container to a Nebius GPU Serverless Endpoint serving
   Nemotron 3 Nano. Confirm the `nano_v3` reasoning-parser plugin, the
   `qwen3_coder` tool parser and `reasoning_budget` all work *together*. Point
   `WARRANT_VLLM_BASE_URL` at it and run `warrant ask` against real inference.
   First because everything downstream assumes it, and because the fallback
   decision depends on the answer.
2. **Verify the Token Factory base URL and `reasoning_budget` request shape**
   against the console and API reference. Both are currently unverified guesses
   in `.env.example` and `openai_compat.py`.
3. **Build the product surface.** This is the Design criterion, 25% of the score,
   and the first thing that gets cut under pressure — so it starts early.
   Minimum: architecture model view, a request form, the decision with its
   reasons, the audit log, and a visible "served by tier X" indicator.
4. **Two LangGraph demo agents** that actually call `POST /v1/warrant` and
   visibly change behaviour on a refusal (ADR-0005).
5. **OpenShell integration** — emit the computed grant as an OpenShell policy so
   the decision is enforced, not merely reported.
6. Move the audit log from local JSONL to Nebius Object Storage.
7. Benchmark self-hosted vs Token Factory: throughput, TTFT, p95, cost per 1M
   tokens, break-even volume. Feeds the README and the video.

### Open questions / blocked on
- **Token Factory base URL** — `api.tokenfactory.nebius.com/v1` is a guess. The
  pre-rebrand AI Studio URL was `api.studio.nebius.com/v1`. Decide by reading the
  console, not by trying URLs.
- **`reasoning_budget` wire format** — passed as `chat_template_kwargs` today.
  Confirm whether Token Factory accepts the same shape as vLLM.
- **Exact Token Factory model IDs for the Nano variants** — Super is confirmed as
  `nvidia/nemotron-3-super-120b-a12b`; the Nano IDs are unverified.
- **CPU-only Serverless Endpoint preset and hourly rate** — needed to cost the
  always-on tier. Not published in the docs we could read.
- **Which Nemotron for the fast tier** — Nano 4B on an L40S ($0.74/hr preemptible)
  vs Nano 30B, which NVIDIA's own card supports only on H100/A100 ($2.15/hr
  preemptible). Decide at the gate on whether 4B classifies well enough.

### Changed since last entry
- First entry. Direction changed twice before this scaffold: governed personal
  memory → guardrail gateway → egress routing → WARRANT. All three prior
  candidates were dropped against shipped competitors; the reasoning is in
  ADR-0001 rather than lost in chat history.
