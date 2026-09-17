# Claude Code kickoff prompt

Paste everything below the line into Claude Code from the repo root.

---

You are helping me build **WARRANT** for the Nebius × NVIDIA Global AI Hackathon.
Submissions close **30 Oct 2026 10:00 PDT (31 Oct 01:00 AWST)**. Judging runs
1–15 Dec. I am solo, employed full-time, with roughly six weekends.

## Read these first, in this order

1. `docs/PROGRESS.md` — current state and what's next. Do not re-derive state
   from the diff or from the code.
2. `docs/ARCHITECTURE.md` — what the system is now.
3. `docs/adr/` — five ADRs. **0004 is load-bearing: the language model never
   makes the authorization decision.** Do not propose designs that violate it.
4. `README.md` — the positioning, including the prior-art table.

## What WARRANT is

An authorization plane for agent-to-agent calls that computes the decision from a
modelled enterprise architecture — capability ownership, data-entity stewardship,
explicit grants — and returns a refusal with its architectural reason plus an
audit record. Track: Best Apps and Agents.

The one-sentence differentiation: *SAP LeanIX knows who owns the capability but
makes no runtime decision; Okta makes the runtime decision but has no idea what a
capability is — WARRANT is the join, and it returns the architectural reason.*

## Non-negotiable constraints

- **The model never decides.** Grant resolution stays pure and deterministic
  (`src/warrant/engine/decision.py`, no I/O). Nemotron classifies which entities a
  call touches and writes the justification. The classifier can only *narrow* the
  callee's declared entity set, never widen it. Fail closed everywhere.
- **One code path for inference.** vLLM and Token Factory both go through
  `OpenAICompatProvider`. Never add a second client or a framework abstraction in
  core. Switching tiers is a config edit.
- **No agent framework in core.** LangGraph is for the demo agents only (ADR-0005).
- **Don't rebuild prior art.** Not an agent builder, not an EA repository, not a
  sandbox. If a change drifts toward any of those, say so and stop.
- **TOGAF is rigour, never the pitch.** The demo leads with the refusal.
- **Design is 25% of the score.** The product surface is not an optional extra;
  it is the criterion most likely to be cut under pressure, so it ships early.

## Hackathon compliance (verified from the rules)

"Runs on Nebius" means *a runtime call to the Token Factory inference API* **or**
*deployed/run using Nebius AI Cloud compute (Serverless Jobs, Serverless
Endpoints, or DevPods)*. A bare GPU VM is **not** on that list — self-hosted vLLM
must run on a **GPU-backed Serverless Endpoint**. Plus at least one NVIDIA open
model; the judging criteria name **Nemotron** specifically.

Judged on four equally weighted criteria: Technological Implementation, Design,
Potential Impact, Quality of the Idea.

## Cost discipline

Serverless Endpoints do **not** scale to zero. The GPU endpoint is started
manually and stopped when I stop working (`nebius ai endpoint stop --id <id>`).
Target total spend is under $150. Never leave a GPU endpoint running overnight or
during the judging window — the tier fallback exists precisely so that's safe.

## Working practice

- Read `docs/PROGRESS.md` at the start of every session; update it at the end of
  every session, even sessions that produce no code.
- Write the ADR when the decision is made, not retroactively.
- Update `docs/ARCHITECTURE.md` in the same session as the change that made it stale.
- Small commits with messages that make sense to someone reading `git log` later.
- **Check current SDK docs before writing integration code.** Nemotron, vLLM and
  Nebius all move faster than training data. Several things in this repo are
  marked `TODO(verify)` precisely because they are unverified guesses — resolve
  them from primary sources, not from memory.

## Today's task

Work item 1 from `docs/PROGRESS.md`: stand up the fast tier. Deploy
`vllm/vllm-openai` to a Nebius GPU Serverless Endpoint serving Nemotron 3 Nano,
confirm the reasoning parser, tool parser and `reasoning_budget` work *together*,
point `WARRANT_VLLM_BASE_URL` at it, and get `warrant ask` returning a real
decision from real inference.

**This is a hard gate — 20 Sep.** If it is not working by then, we move the fast
tier to Token Factory that day and self-hosting becomes a benchmark appendix.
Tell me plainly if we're going to miss it; do not quietly keep fighting it.

Before writing code, tell me what you found in PROGRESS.md and what you plan to
do. Then start.
