# Architecture

## One-paragraph summary

WARRANT is a **governed multi-agent system**. Three agents, one per
organisation unit, do work that genuinely requires data owned by another unit.
No agent can reach across an organisational boundary without a warrant. When
one asks for one, the authorization plane looks the call up in a model of the
organisation — which business capability the caller serves, who owns it, which
data entities the callee touches, who stewards those — and issues either a
warrant or a refusal **with the architectural reason**, then writes an audit
record. The decision itself is deterministic graph traversal.

The part that makes this a multi-agent system rather than a proxy demo: **a
refusal is an input to the agent's planning loop, not an error.** A refused
agent replans — it finishes what it can reach and reports the reduced scope, or
it drafts a grant request naming the capability, the entity and the human who
can approve it. NVIDIA Nemotron works out which data entities a call touches,
writes the explanation a human reads, and drives that replanning. It never
makes the authorization decision (ADR-0004).

## Components

**`warrant.agents`** *(the product; ADR-0008)* — three LangGraph agents, one per
organisation unit, each running as its own small FastAPI service on its own
port. Each owns a fixture dataset matching the data entities the architecture
model attributes to it, so a refusal withholds real rows rather than an
abstraction.

| Agent | Org unit | Owns |
|---|---|---|
| `expense-auditor` | Finance | `Expense.Claim` |
| `inventory-reconciler` | Operations | `Inventory.StockLevel`, `Supplier.Contract` |
| `roster-planner` | People & Culture | `Employee.Roster`, `Employee.Compensation` |

Separate processes rather than subgraphs in one app, because the organisational
boundary has to be a real network hop for the no-bypass guarantee below to mean
anything, and because one URL per agent is what an A2A Agent Card will later
attach to. `warrant serve-agent <id>` starts one; `scripts/run_demo.sh` starts
the whole topology and `scripts/smoke_topology.sh` proves the seam across it.

Only `expense-auditor` uses LangGraph — it is the one agent with a planning
loop. The other two are request handlers. The console's **Run** button takes a
shortcut for convenience: `POST /v1/demo/run` executes the real graph against
the real plane but reaches it in-process, so the console works without the
agent services running. The cross-process path is the one `smoke_topology.sh`
exercises.

**`warrant.agents.governed_call`** — the single seam every cross-boundary call
passes through. Requests a warrant, and on refusal hands the structured reasons
back to the planner rather than raising. **There is no ungoverned path**, and a
test asserts it structurally: no agent may reach another org unit's data except
through this node. It is also the seam the transport swaps at — direct HTTP
today, A2A later, with nothing above it changing.

**`warrant.agents.replan`** — the branch that makes a refusal productive:
*degrade* (complete the task with the entities the caller does hold grants for,
and state the reduced scope), *escalate* (draft a grant request naming the
capability, the data entity and the owning steward), *record* (log what was
refused and why, so the next run does not retry the same path). Nemotron chooses
the branch and writes the request; it cannot change the authorization outcome.

**`warrant.mcp_server`** *(ADR-0010)* — the plane exposed as three MCP tools
(`request_warrant`, `list_my_access`, `raise_grant_request`). An adapter like
`warrant.agents`: it imports the MCP SDK so the core never does, and it proxies
to the HTTP plane rather than embedding a service, so there is one source of
truth. Identity comes from server configuration, never from a tool argument.
Refusals are returned as structured results with the steward and a remediation
hint, not as tool errors. Complements A2A (agent-to-agent transport, deferred);
MCP is agent-to-tool.

**`warrant.model`** — the architecture model: a deliberately small subset of the
TOGAF content metamodel (Organization Unit, Business Capability, Data Entity,
Application Component/Agent, and Grant), loaded from YAML into an in-memory
graph and validated on load. *Not* responsible for any decision logic, and not
a general-purpose EA repository — it holds only what an authorization decision
needs.

**`warrant.engine.decision`** — pure, deterministic grant resolution. Given a
model, a request and a list of data entities, returns a decision with
structured reasons. No I/O, no model call. *Not* responsible for deciding which
entities are touched, or for phrasing anything for humans.

**`warrant.engine.classify`** — fast-tier Nemotron call that narrows the callee's
declared data entities to those a specific call requires. Intersecting with the
declared set means the model can never reach an entity the callee does not hold.
It *can* drop one the callee does hold, and that is the one path by which model
output changes an outcome (ADR-0009): a dropped entity's grant is never checked.
Such exclusions are recorded as `decisive_exclusions` and can be refused
entirely with `strict_narrowing`. Fails closed to the full declared set on any
error.

**`warrant.engine.justify`** — deep-tier Nemotron call that turns structured
reasons into one paragraph of prose. *Not* responsible for the outcome; it
explains a decision already made, and has a deterministic fallback.

**`warrant.providers`** — one OpenAI-compatible HTTP client serving both
self-hosted vLLM and Nebius Token Factory, plus a `mock` provider for offline
work. `TierRouter` resolves a logical tier (`fast`, `deep`) to a provider and
falls back when a tier is unreachable.

**`warrant.engine.audit`** — append-only JSONL log of every decision, granted or
refused. Append-only in the sense that nothing rewrites a record; the file is
still deletable by `POST /v1/demo/reset`, which is why that route 404s unless
`demo_mode` is on. It is also the warrant store that callees verify against, so
deleting it revokes every live warrant.

**`warrant.api`** — FastAPI surface: `POST /v1/warrant`, `GET /v1/audit`,
`GET /v1/model`, `GET /healthz`.

**`warrant.cli`** — `ask`, `log`, `validate`, `serve`.

## Data flow

The flow starts with an agent being given a task, not with an HTTP request
arriving.

1. **Expense Auditor** (Finance) is asked to reconcile Q3 expense claims. It
   plans, and finds it needs data held by Operations.
2. The plan reaches `governed_call` — the only way out of the agent's own org
   unit.
3. `governed_call` → authorization plane: `POST /v1/warrant {caller, callee, purpose, payload}`
4. Plane → architecture model: look up the caller's capability and the callee's declared `reads`
5. Plane → **fast tier** (Nemotron Nano on vLLM): narrow the declared entities to those this purpose requires
6. Fast tier → plane: subset of data entity ids, JSON-schema constrained, intersected with the declared set so it can only narrow
7. Plane → decision engine: deterministic grant check, capability × each entity. **No model call.**
8. Decision engine → plane: granted/denied plus structured reasons
9. Plane → **deep tier** (Nemotron Super on Token Factory): write the justification from reasons already computed
10. Plane → audit log: append the record
11. Plane → `governed_call`: `200` with the warrant, or `403` with the refusal and its reasons

Granted, the call proceeds to the Inventory Reconciler and returns rows. Refused,
the flow continues instead of stopping:

12. `governed_call` → `replan`: hands back the structured reasons, not an exception
13. **Degrade** — reissue against the entities the caller does hold grants for,
    complete the reconciliation on `Supplier.Contract` alone, and report the
    reduced scope; or
14. **Escalate** — when the task cannot be completed at all, draft a grant
    request naming `expense-management → Employee.Compensation` (the *caller's*
    capability, which is the one lacking the grant) and the People & Culture
    steward who can approve it
15. **Record** — write the refused path to the run log so the next run does not
    retry it blindly

Steps 12–15 are why this is an agentic system. Steps 4–8 are why the
authorization decision is still auditable.

## External dependencies

- **Nebius Token Factory inference API** — `POST /v1/chat/completions` against
  `nvidia/nemotron-3-super-120b-a12b` (deep tier). Satisfies the hackathon's
  "runtime call to the Token Factory inference API" clause.
- **Nebius AI Cloud Serverless Endpoints** *(development and benchmarking)* — a
  GPU endpoint running `vllm/vllm-openai` with Nemotron 3 Nano, plus a CPU-only
  endpoint hosting the plane and console. **Both tiers currently run on Token
  Factory**, which is what satisfies the hackathon's "runtime call to the Token
  Factory inference API" clause on its own; self-hosting is the sovereign-tier
  comparison, not the compliance route, and is kept off during judging so no GPU
  burns unattended.
- **NVIDIA Nemotron 3** — Nano (fast) and Super/Ultra (deep). The per-tier
  cost/latency dial is vLLM's top-level `thinking_token_budget` sampling
  parameter; Token Factory does not document it, so it binds on the sovereign
  tier only. The fast tier runs the `nano_v3` reasoning parser and no tool-call
  parser (ADR-0006).
- **LangGraph** — the three org agents and the replanning loop only. Never
  imported by `warrant.engine` or `warrant.providers` (ADR-0005's layering rule,
  which ADR-0008 keeps).

## Deployment topology

| Component | Runs on | Always on? | Cost note |
|---|---|---|---|
| Three org agents | Nebius Serverless Endpoint, CPU-only | Yes, through judging | One service each, or one container running all three |
| Authorization plane + UI | Nebius Serverless Endpoint, CPU-only | Yes, through judging | Small continuous bill; endpoints do NOT scale to zero |
| Fast tier (vLLM + Nemotron Nano) | Nebius Serverless Endpoint, 1× **H100** | **No — started manually** | Serverless L40S quota is zero on this tenant; `msp.cloudapps.gpu.h100` is 16. H100 also matches NVIDIA's support matrix for Nano 30B, so self-hosting serves the same model Token Factory does |
| Deep tier | Nebius Token Factory | Managed | Per token, inside the $50 of hackathon credits |
| Audit log | JSONL on the API container | — | Move to Object Storage before submission |

When the fast tier is stopped, `TierRouter` falls through to the deep tier, the
request still succeeds, and the audit record says which tier served it.

## Known limitations / non-goals

- **Not an agent builder.** WARRANT does not help you build agents; it governs
  the ones you have. The three agents here are the demonstration, not the
  product's output. The plane stays callable from any framework.
- **Single hop only.** WARRANT authorizes A→B. Whether A's authority flows
  transitively through B to C is unsolved here, and unsolved generally.
- **Not A2A, yet.** Inter-agent calls are direct HTTP behind one seam.
  A2A v1.0 §7.5 requires implementers to supply authorization scoping and
  defines no mechanism, so the protocol is a natural fit; it is a transport
  swap at `governed_call`, deliberately deferred until replanning works.
- **Not an EA repository.** SAP LeanIX AI Agent Hub (GA Nov 2025) models agents against capability maps; WARRANT deliberately does not compete there. It consumes a model and makes a runtime decision.
- **The model is hand-authored.** Discovery/ingestion from a real EA tool is out of scope for the hackathon window.
- **Grants are coarse** — capability × data entity. No row-level, purpose-limited or time-boxed grants yet.
