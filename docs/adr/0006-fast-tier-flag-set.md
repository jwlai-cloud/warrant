# 0006. The fast tier serves no tools and sets no reasoning-config

Date: 2026-09-17
Status: Accepted

## Context

Work item 1 set the gate as: confirm the `nano_v3` reasoning parser, the
`qwen3_coder` tool parser and `reasoning_budget` work **together** on a Nebius
GPU Serverless Endpoint. Checking the primary sources rather than trusting the
scaffold's guesses, that conjunction is currently not achievable:

- vLLM issue **#39103** is open. On Nemotron 3, combining `--reasoning-parser`
  with `--reasoning-config` (the server-side thinking budget) returns
  `content: null` and puts every token in `reasoning_content`. No workaround.
- The NVIDIA model card discussion reports `--enable-auto-tool-choice
  --tool-call-parser qwen3_coder --reasoning-parser nano_v3` broken on vLLM
  0.12.0, fixed only on a nightly (PR #30671).
- `reasoning_budget` was never a real wire parameter. vLLM's knob is the
  top-level sampling parameter `thinking_token_budget`; `chat_template_kwargs`
  carries `enable_thinking` only. The scaffold's shape was wrong.

The gate was written before any of this was known, and it over-specifies.

## Decision

The fast tier runs `--reasoning-parser nano_v3` with its downloaded plugin, and
nothing else. Specifically:

- **No tool-call parser.** `engine/classify.py` constrains output with
  `response_format: json_schema`. WARRANT issues no tool calls anywhere, so
  `--enable-auto-tool-choice --tool-call-parser qwen3_coder` buys nothing and
  costs us a known-broken interaction.
- **No `--reasoning-config`.** That flag is what triggers #39103. The budget is
  applied per-request as `thinking_token_budget` instead, which is the
  documented path and leaves the parser intact.
- `scripts/smoke_fast_tier.sh` asserts all three properties against the live
  endpoint before WARRANT is pointed at it.

The gate is therefore restated as: **the fast tier returns parseable
schema-constrained JSON with a bounded reasoning budget.** Tool calling is out
of scope, not deferred.

## Alternatives considered

- **Run a vLLM nightly to get both fixes** — rejected. An unpinned nightly under
  a hard deadline, for a capability WARRANT does not use.
- **Keep the tool parser configured but unused** — rejected. It is exactly the
  flag combination with an open bug, and nothing would exercise it until it
  broke something else.
- **Drop self-hosting and serve the fast tier from Token Factory** — not taken
  *yet*, but it is now cheap to take: Nemotron 3 Nano 30B A3B is already served
  on Token Factory at roughly $0.05/$0.20 per 1M tokens. Under ADR-0002 that is
  a config edit. This remains the fallback if the endpoint does not come up.

## Consequences

- One fewer moving part on the highest-risk work item, and both known upstream
  bugs are routed around rather than fought.
- The claim we can make is narrower and true: WARRANT self-hosts Nemotron for
  classification on Nebius compute. We do not claim tool-calling agents on the
  sovereign tier.
- `thinking_token_budget` is a no-op on Token Factory, which does not document
  it. Benchmarks must not present a deep-tier latency as evidence the budget
  applied.
