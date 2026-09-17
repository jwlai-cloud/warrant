# Progress log

## 2026-09-17 — session 3 (reframe: governed multi-agent system)

### What changed, and why it matters more than anything else this session
The project was a policy microservice with imaginary agents. `config/model/agents.yaml`
described four agents; zero existed. Every claim about agent-to-agent
authorization was asserted, never demonstrated — which fails **Potential Impact**
("based on what's demonstrated") and is precisely what **Design** screens out
("a complete, coherent product experience, not just a technical proof of concept").

**WARRANT is now a governed multi-agent system.** Agents are the product; the
authorization plane is a component they call. ADR-0008 records it and supersedes
ADR-0005's *framing* — ADR-0005's layering rule (no agent framework in
`warrant.engine` / `warrant.providers`) stands unchanged.

The novel claim is no longer "we decide from an EA model". It is:
**agents that treat an authorization boundary as a planning constraint rather
than an error.** Refused, an agent degrades (finishes what it can reach, states
the reduced scope), escalates (drafts a grant request naming the capability, the
entity and the human steward who can approve it), and records the refused path.
Competitive research found nobody doing this — and MCP's own Authorization
Interest Group lists *"structured denials, remediation hints"* as active and
unsolved.

### Done this session
- **Made classification load-bearing (ADR-0007, commit `76755c9`).** The scaffold
  shipped ADR-0004 in a way that left Nemotron inert: the demo callee declared an
  entity the caller could never reach, so every purpose denied and narrowing
  changed nothing; the mock echoed the declared set verbatim, so `classify.py`'s
  *failure* path and the mock's *success* path returned identical values. A dead
  fast tier was indistinguishable from a working one. Added the grant
  `expense-management -> Inventory.StockLevel`, leaving `Employee.Compensation`
  as the only unreachable entity, so the outcome turns on one real language
  question. `tests/test_ab_demo.py` pins that the purpose flips the outcome.
- **Resolved the four `TODO(verify)` items (commit `ae58050`)** — see session 2.
  Headline: `reasoning_budget` inside `chat_template_kwargs` was fiction; the real
  knob is vLLM's top-level `thinking_token_budget`.
- **Competitive research, adversarial.** Findings that changed the docs:
  - "OpenShell is the enforcement layer; WARRANT is the decision layer above it"
    was **deleted everywhere**. ServiceNow AI Control Tower claimed that exact
    slot on 2026-05-05.
  - LeanIX row now timestamped. SAP's own reference architecture dates an
    agent↔tool PEP to **H2/2026**; the "no runtime decision" claim has a shelf life.
  - **Open Agent Passport (arXiv 2603.20953, 2026-03-21)** added to the prior-art
    table. It publishes ADR-0004's deterministic-authz argument. Our remaining
    gap — ownership and stewardship as *decision inputs*, and a denial that names
    the steward — holds, but the framing is no longer ours alone.
  - A2A v1.0 §7.5 requires implementers to supply authorization scoping and
    defines no mechanism. Exact fit; deferred deliberately (see open questions).
- **Rewrote ARCHITECTURE.md** — `warrant.agents`, `governed_call`, `replan`
  components; data flow now starts with an agent being given a task, not an HTTP
  request arriving; deployment topology includes the three agent services.
- **Rewrote README.md** — new lead, the replan example, the A/B table, the
  timestamped prior-art table.
- **Put data entities with the org that stewards them (`329d008`).**
  `inventory-reconciler` declared `Employee.Compensation` - an inventory agent
  reading salaries, which does not survive "why does Operations hold payroll?".
  Compensation moved to `roster-planner`; Finance granted `Employee.Roster` but
  not `Employee.Compensation`. The A/B moved there and got better: *who
  travelled* is grantable, *what they earn* is not. Also caught a real bug - the
  mock matched every token of an entity id, so "employee" in a purpose selected
  both `Employee.Roster` and `Employee.Compensation`; a shared family prefix
  silently widened the set and denied a call that should have been granted.
- **Built the governed-call seam and the no-bypass gate (`584c566`).**
  `governed_call` returns structured reasons on refusal rather than raising;
  `verify_warrant` is the callee-side check that makes the seam real rather than
  honour-system. Warrants now carry a 60s `expires_at`, and `GET
  /v1/warrant/{id}` is what a callee verifies against.
- **Published the UI prototype** - grant matrix as the hero, cells lighting as
  each governed call is checked: https://claude.ai/artifact/GXkFQpNVjXmbLRGKYY5S5M
- **23 tests passing** (was 7 at end of session 1).

### Debt created this session — read before submitting
**The README's headline example shows behaviour that does not exist yet.** The
"41 of 47 claims reconciled / grant request drafted" block is the target, not
shipped output. That is normal for a README mid-build and *lethal* if it survives
to submission unbuilt. Either the replan loop ships, or that block comes out.
Re-check it in the pre-submission sweep.

### Next (priority order — agents first now)
1. ~~`governed_call` + no-bypass gate~~ — **done**, `584c566`.
2. **Three LangGraph agents, one per org unit, each its own small FastAPI
   service.** `expense-auditor` (Finance), `inventory-reconciler` (Operations),
   `roster-planner` (People & Culture). Separate processes, not subgraphs: the
   org boundary must be a real network hop for the no-bypass gate to mean
   anything, and one URL per agent is what an A2A Agent Card will later attach to.
   Each owns a **fixture dataset** matching its declared entities — a refusal has
   to withhold real rows, or the demo is abstract.
3. **`replan`** — degrade, escalate, record. **If only one branch ships, ship
   escalate.** A grant request naming the capability, the entity and the actual
   human owner is a product; "access denied, contact your administrator" is a
   gimmick. This is where the project wins or doesn't.
4. **Product surface** (Design, 25%, still at zero). Centrepiece is the grant
   matrix with its holes visible, plus live agent state and the audit log with a
   "served by tier X" indicator. One command locally (`warrant demo`), zero
   commands hosted — a judge must never orchestrate three processes.
5. **Fast tier** — demoted from item 1. Blocked on Nebius credentials regardless,
   and Token Factory already satisfies the compliance clause. One timeboxed
   session: deploy, `scripts/smoke_fast_tier.sh`, done or folded to
   `kind: token_factory`.
6. **Richer architecture model** — currently 3 capabilities × 5 entities = 15
   cells, 6 grants. A human reads that and correctly concludes they do not need a
   product for it. Target ~6 capabilities × 10 entities with 3–4 deliberate gaps,
   so the matrix stops fitting in a judge's head. Pure YAML, feeds item 4 directly.
7. Demo video (<3 min, hard rule). Benchmark table in the README.

**Cut, deliberately (decided this session):** NVIDIA OpenShell enforcement —
removed from scope *and* from the docs. Nebius Object Storage for the audit log —
a checkbox nobody scores. Transitive delegation (A→B→C) — named in the README as
a known limitation rather than half-built.

- **Wrote `docs/PRD.md` — the document that was missing.** Eight ADRs recorded
  decisions with no stated goal to judge them against, which is exactly how the
  framing drifted from "policy microservice" to "governed multi-agent system"
  partway through. The PRD states the problem, the two narrow claims, the
  personas (including the data steward, the one most agent-governance products
  forget), P0/P1/P2 requirements with current state, and a **§5 "explicitly not
  building"** list that is the defence against week-5 scope creep.
- **Published two artifacts:**
  - Console (v2) — six views, approvals inbox that writes a grant into the model,
    re-run closes at 47/47: https://claude.ai/artifact/GXkFQpNVjXmbLRGKYY5S5M
  - Blueprint — architecture, sequence, agent topology, the approval loop, and
    the service inventory: https://claude.ai/artifact/1FfN4oo7yyhpVweP7xsmhf

### Decided this session, after checking rather than recalling
- **Eval: DeepEval, in `[dev]` extras. Not Opik, not LangSmith.** LangGraph
  ships no evaluator; its eval lives in LangSmith, which is hosted and an
  account dependency. DeepEval runs fully local with no Confident AI account, so
  a judge can clone and run it; it supports deterministic `BaseMetric` subclasses
  with no LLM at all, which is what the exact-set classifier eval needs; and it
  takes a custom model, so the judge model points at **our own Nebius endpoint** -
  Nemotron evaluating Nemotron, entirely on Nebius. Opik is good and cheap
  (Apache 2.0 self-host, ~$19/mo cloud) but its value is tracing, and the audit
  log already carries tier, provider, latency and tokens per decision. It also
  means a service running during judging, against a "nothing runs overnight"
  cost strategy. Wire DeepEval *after* the agents exist - eval needs something to
  evaluate.
- **TOGAF ADM: no.** The content metamodel stays (ADR-0003); the Architecture
  Development Method does not. Nothing in the four judging criteria scores
  process, and `KICKOFF.md` already says TOGAF is rigour, never the pitch. One
  cheap adjacent win taken instead: ArchiMate conventions for the archify
  diagrams, which costs nothing and reads as fluent to an EA-literate judge.
- **A2A: deferred, not rejected.** §7.5 requires implementers to supply
  authorization scoping and defines no mechanism, so the fit is exact. It is a
  transport swap at `governed_call`. Revisit once replanning works.

### Open questions / blocked on
- **Nebius profile still not created.** `~/.nebius/bin/nebius profile create`
  needs a browser and is the human step blocking item 5. CLI 0.12.277 is
  installed; `jq` present. Credits unverified.
- **A2A: when to swap the transport.** The seam is `governed_call`. Doing it
  makes "agent-to-agent" literal, and an Agent Card extension declaring each
  agent's data entities would make the architecture model partly
  *self-describing* rather than hand-authored — which is the direct answer to
  "you wrote the YAML that produces the refusal". Deferred until replanning
  works; revisit once item 3 is green.
- **Where does the architecture model come from in reality?** Agreed direction is
  one narrow ingestion path — Nemotron extracts capabilities/entities/stewards
  from plain-language service descriptions, human reviews and commits. Not
  scheduled yet; it competes with item 4 for the same weekend.
- **Exact Token Factory model ID for Nemotron 3 Nano 30B.** In the catalogue;
  string unverified. Super is `nvidia/nemotron-3-super-120b-a12b`.
- **`--subnet-id`** required if the project has multiple subnets. Unknown until
  the account exists.
- **Oktane 2026 is 22–24 Sept.** Okta already ships agent-to-agent connection
  policies. Re-check the prior-art table once after it, before submission.
- **Atlan + Immuta** is the closest thing found to WARRANT's claim. Unverified
  whether steward metadata is a *runtime* decision input or only an approval
  workflow. Worth a docs-level read before publishing the differentiation.

### Changed since last entry
- Product framing: authorization gateway → governed multi-agent system (ADR-0008).
- Work order inverted: agents are now item 1, fast tier item 5.
- LangGraph is back in, for the agents. Earlier in this session the
  recommendation was plain `httpx`; that was right for dumb demo agents and wrong
  for a replanning loop, where a state graph with conditional edges is the job.
- OpenShell removed from README, ARCHITECTURE and scope.

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

- **Wrote `docs/PRD.md` — the document that was missing.** Eight ADRs recorded
  decisions with no stated goal to judge them against, which is exactly how the
  framing drifted from "policy microservice" to "governed multi-agent system"
  partway through. The PRD states the problem, the two narrow claims, the
  personas (including the data steward, the one most agent-governance products
  forget), P0/P1/P2 requirements with current state, and a **§5 "explicitly not
  building"** list that is the defence against week-5 scope creep.
- **Published two artifacts:**
  - Console (v2) — six views, approvals inbox that writes a grant into the model,
    re-run closes at 47/47: https://claude.ai/artifact/GXkFQpNVjXmbLRGKYY5S5M
  - Blueprint — architecture, sequence, agent topology, the approval loop, and
    the service inventory: https://claude.ai/artifact/1FfN4oo7yyhpVweP7xsmhf

### Decided this session, after checking rather than recalling
- **Eval: DeepEval, in `[dev]` extras. Not Opik, not LangSmith.** LangGraph
  ships no evaluator; its eval lives in LangSmith, which is hosted and an
  account dependency. DeepEval runs fully local with no Confident AI account, so
  a judge can clone and run it; it supports deterministic `BaseMetric` subclasses
  with no LLM at all, which is what the exact-set classifier eval needs; and it
  takes a custom model, so the judge model points at **our own Nebius endpoint** -
  Nemotron evaluating Nemotron, entirely on Nebius. Opik is good and cheap
  (Apache 2.0 self-host, ~$19/mo cloud) but its value is tracing, and the audit
  log already carries tier, provider, latency and tokens per decision. It also
  means a service running during judging, against a "nothing runs overnight"
  cost strategy. Wire DeepEval *after* the agents exist - eval needs something to
  evaluate.
- **TOGAF ADM: no.** The content metamodel stays (ADR-0003); the Architecture
  Development Method does not. Nothing in the four judging criteria scores
  process, and `KICKOFF.md` already says TOGAF is rigour, never the pitch. One
  cheap adjacent win taken instead: ArchiMate conventions for the archify
  diagrams, which costs nothing and reads as fluent to an EA-literate judge.
- **A2A: deferred, not rejected.** §7.5 requires implementers to supply
  authorization scoping and defines no mechanism, so the fit is exact. It is a
  transport swap at `governed_call`. Revisit once replanning works.

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

- **Wrote `docs/PRD.md` — the document that was missing.** Eight ADRs recorded
  decisions with no stated goal to judge them against, which is exactly how the
  framing drifted from "policy microservice" to "governed multi-agent system"
  partway through. The PRD states the problem, the two narrow claims, the
  personas (including the data steward, the one most agent-governance products
  forget), P0/P1/P2 requirements with current state, and a **§5 "explicitly not
  building"** list that is the defence against week-5 scope creep.
- **Published two artifacts:**
  - Console (v2) — six views, approvals inbox that writes a grant into the model,
    re-run closes at 47/47: https://claude.ai/artifact/GXkFQpNVjXmbLRGKYY5S5M
  - Blueprint — architecture, sequence, agent topology, the approval loop, and
    the service inventory: https://claude.ai/artifact/1FfN4oo7yyhpVweP7xsmhf

### Decided this session, after checking rather than recalling
- **Eval: DeepEval, in `[dev]` extras. Not Opik, not LangSmith.** LangGraph
  ships no evaluator; its eval lives in LangSmith, which is hosted and an
  account dependency. DeepEval runs fully local with no Confident AI account, so
  a judge can clone and run it; it supports deterministic `BaseMetric` subclasses
  with no LLM at all, which is what the exact-set classifier eval needs; and it
  takes a custom model, so the judge model points at **our own Nebius endpoint** -
  Nemotron evaluating Nemotron, entirely on Nebius. Opik is good and cheap
  (Apache 2.0 self-host, ~$19/mo cloud) but its value is tracing, and the audit
  log already carries tier, provider, latency and tokens per decision. It also
  means a service running during judging, against a "nothing runs overnight"
  cost strategy. Wire DeepEval *after* the agents exist - eval needs something to
  evaluate.
- **TOGAF ADM: no.** The content metamodel stays (ADR-0003); the Architecture
  Development Method does not. Nothing in the four judging criteria scores
  process, and `KICKOFF.md` already says TOGAF is rigour, never the pitch. One
  cheap adjacent win taken instead: ArchiMate conventions for the archify
  diagrams, which costs nothing and reads as fluent to an EA-literate judge.
- **A2A: deferred, not rejected.** §7.5 requires implementers to supply
  authorization scoping and defines no mechanism, so the fit is exact. It is a
  transport swap at `governed_call`. Revisit once replanning works.

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
