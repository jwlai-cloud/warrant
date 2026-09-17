# Progress log

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
