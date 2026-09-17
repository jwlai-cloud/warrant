# WARRANT — Product Requirements

**Status:** accepted · **Date:** 2026-09-17 · **Owner:** solo
**Submission:** Nebius × NVIDIA Global AI Hackathon, 30 Oct 2026 10:00 PDT · Track: Best Apps and Agents

This document exists because it was missing. Eight ADRs recorded *decisions*
with no stated goal to judge them against, and the product framing drifted from
"policy microservice" to "governed multi-agent system" partway through the
build. Decisions without a product statement are internally consistent and
collectively wrong. This is the statement.

---

## 1. Problem

An enterprise now runs agents from several teams. A Finance agent needs data
Operations holds; an Operations agent needs something People & Culture stewards.
The moment those agents call each other, one question has no owner:

> **Is this agent allowed to reach that data — and on whose authority?**

Today the answer is split across two categories of tool, and neither can answer it:

- **Enterprise architecture tools** (SAP LeanIX AI Agent Hub, Ardoq) know who
  owns the *Accounts Payable* capability and who stewards *Customer PII*. They
  make **no runtime decision**. LeanIX is a registry: it watches agents, it does
  not gate them. *(SAP's own reference architecture dates an agent↔tool
  enforcement point to H2/2026 — this gap has a shelf life.)*
- **Identity and access tools** (Okta Agent-to-Agent Connections, Auth0 for AI
  Agents, OpenFGA, Cerbos, Permit.io) make the runtime decision. They have **no
  concept of a business capability or a data steward**. Every denial they can
  produce is technical: invalid token, missing scope, no matching tuple.

So when an agent is refused, the refusal says `403 insufficient_scope`. Nobody
can tell which human could fix it, and the agent that hit the wall simply fails.

Protocols do not close this either. **A2A v1.0 §7.5** requires implementers to
provide "appropriate authorization scoping" and defines **no mechanism**. The
**MCP Authorization Interest Group** lists as *active and unsolved*:
"authorization granularity beyond scope strings — Rich Authorization Requests,
**structured denials, remediation hints**." The gap is named by the spec
community; nothing has filled it.

## 2. What WARRANT is

**A governed multi-agent system.** Agents are the product; the authorization
plane is a component they call.

Two claims, and they are deliberately narrow:

1. **The decision inputs are capability ownership and data-entity stewardship**,
   and a refusal names the steward and the missing grant. Nothing shipped does
   this — verified against LeanIX, Okta/Auth0, ServiceNow AI Control Tower,
   Immuta, Veza, Collibra, OpenShell and the A2A/MCP specs, Sept 2026.
2. **A refusal is an input to the agent's planning loop, not an error.** The
   refused agent degrades to what it can reach, escalates a grant request naming
   the capability, the entity and the human who can approve it, and records the
   refused path. Nobody has built this.

**The one-sentence version:** *LeanIX knows who owns the capability but makes no
runtime decision; Okta makes the runtime decision but has no idea what a
capability is — WARRANT is the join, and the agents on top of it replan when
refused.*

## 3. Who it is for

| Persona | Cares about | Sees in the product |
|---|---|---|
| **Platform / security engineer** | Can an agent reach data it shouldn't? Is it provable? | Grant matrix, audit log, no-bypass guarantee |
| **Enterprise architect** | Is the runtime consistent with the modelled architecture? | The model as the source of the decision |
| **Data steward** (People & Culture, Finance) | Who is asking for my data, why, and what breaks if I say no? | **Approvals inbox** — request, justification, blocked work |
| **Agent developer** | My agent got refused. Now what? | Structured reasons the planner can act on |

The steward is the persona most products forget, and the approvals inbox is the
part of this product that closes the loop rather than reporting a problem.

## 4. Requirements

### P0 — without these there is no submission

| # | Requirement | State |
|---|---|---|
| P0-1 | Authorization decision computed deterministically from the architecture model. No model call. | **done** |
| P0-2 | Refusal carries the architectural reason: capability, entity, classification, steward. | **done** |
| P0-3 | Fail closed everywhere — unmodelled agent, unknown entity, unreachable tier, unclassifiable purpose. | **done** |
| P0-4 | Nemotron narrows which entities a purpose touches, and can only narrow, never widen. | **done** |
| P0-5 | A runtime call to Nebius (Token Factory inference **or** Serverless Endpoint compute). *Hackathon eligibility.* | **not started** |
| P0-6 | At least one NVIDIA open model. *Hackathon eligibility.* | **not started** |
| P0-7 | Three agents that actually run and call each other across org boundaries. | **done** |
| P0-8 | No path to another org's data bypasses `governed_call`. Asserted by test. | **done** |
| P0-9 | Refused agent replans: degrade, escalate, record. | **done** |
| P0-10 | Hosted demo URL a judge can open. *Submission requirement.* | **not started** |
| P0-11 | Demo video under 3 minutes. *Submission requirement.* | **not started** |
| P0-12 | Public repo, open-source licence, README with setup. | **done** |

### P1 — this is what makes it score rather than merely qualify

| # | Requirement | State |
|---|---|---|
| P1-1 | **Approvals workflow.** A steward approves a grant request; the grant is written to the model; the next run resolves. | prototyped in UI |
| P1-2 | Console with grant matrix, agent fleet, runs, approvals, filterable audit. | prototyped |
| P1-3 | Audit shows which inference tier served each decision. | **done** |
| P1-4 | Two-tier inference with fallback — stopping the GPU degrades, never breaks. | **done** |
| P1-5 | Classifier eval with precision/recall per tier, run against real inference. | not started |
| P1-6 | Architecture model large enough that the grant matrix does not fit in a reader's head (~6 capabilities × 10 entities). | not started |

### P2 — only if the first two tiers are complete

| # | Requirement |
|---|---|
| P2-1 | A2A transport at the `governed_call` seam; Agent Card extension declaring each agent's data entities. |
| P2-2 | Model ingestion — Nemotron extracts capabilities/entities/stewards from plain-language service descriptions. |
| P2-3 | Benchmark: self-hosted vs Token Factory — TTFT, p95, cost per 1M tokens, break-even volume. |

## 5. Explicitly **not** building

Every line here was considered and cut on purpose. Re-opening one requires a reason.

- **Not an agent builder.** WARRANT governs agents; it does not help you write them.
- **Not an EA repository.** It consumes a model. LeanIX and Ardoq own that space.
- **Not an enforcement sandbox.** NVIDIA OpenShell is a PEP; ServiceNow AI Control
  Tower already claimed "decides above OpenShell" (May 2026). Cut from scope **and**
  from the docs.
- **Not transitive.** WARRANT authorises A→B. Whether A's authority flows through
  B to C is unsolved here and unsolved generally. Named in the README, not half-built.
- **Not row-level or time-boxed grants.** Grants are capability × data entity.
- **No Object Storage for the audit log.** JSONL on the container. Nobody scores it.
- **No TOGAF ADM.** The content metamodel stays (ADR-0003); the process does not.
- **No Opik, no LangSmith.** DeepEval, local, judge model pointed at our own Nebius endpoint.

## 6. Key flows

### 6.1 The demo — Q3 expense reconciliation

The Expense Auditor (Finance) must close 47 Q3 claims. 41 are supplier-rate
claims; 6 are travel allowances.

```
expense-auditor ──▶ inventory-reconciler   "supplier contract rates"     GRANTED
                ──▶ roster-planner         "who travelled in Q3"         GRANTED
                ──▶ roster-planner         "allowance vs salary bands"   REFUSED
                                            Employee.Compensation (restricted)
                                            stewarded by People & Culture
                                            Expense Management holds no grant
   replan ──▶ degrade   41 of 47 closed
          ──▶ escalate  grant request → People & Culture, blocking 6 claims
          ──▶ record    refused path logged; next run does not retry blind
```

### 6.2 The loop that makes it a product

```
refusal ▶ grant request ▶ steward approves ▶ grant written to model ▶ re-run ▶ 47 of 47
```

Without the approval step this is a reporting tool. With it, it is a workflow.

### 6.3 The A/B that proves the model is load-bearing

Same two agents, same grant table. Only the purpose differs.

| Purpose | Narrows to | Outcome |
|---|---|---|
| "which staff travelled in Q3, from the roster" | `Employee.Roster` | granted |
| "verify allowance claims against compensation bands" | `Employee.Compensation` | refused |

Pinned by `tests/test_ab_demo.py`. If that passes with classification disabled,
Nemotron has stopped being load-bearing (ADR-0007).

## 7. Success criteria

**Hackathon** — judged on four equally weighted criteria:

| Criterion | What we are betting on | Current risk |
|---|---|---|
| Technological Implementation | Deterministic core + two-tier Nemotron + no-bypass gate, 29 tests | low |
| **Design** | The console and the approvals workflow | **highest — 25% of score, not yet in the repo** |
| Potential Impact | A real unsolved gap, named by the MCP spec community | medium |
| Quality of the Idea | Refusal-as-planning-constraint. Nobody has built it. | low |

**Product** — the demo is successful if a viewer who knows nothing about TOGAF
watches three minutes and can state: *the agent was refused, here is exactly why,
here is who can fix it, and here is it finishing the job once they did.*

## 8. Constraints

- **Solo, employed full-time, ~5 weekends left** as of 17 Sep 2026.
- **Under $150 total spend.** Nebius GPU Serverless Endpoints do **not** scale to
  zero — started manually, stopped when not working, never left running
  overnight or during judging (1–15 Dec).
- **The model never decides authorization** (ADR-0004). Non-negotiable; it is
  the difference between a demo and something an enterprise could run.
- **One inference code path** (ADR-0002). vLLM and Token Factory both go through
  `OpenAICompatProvider`. Switching tiers is a config edit.
- **No agent framework in core** (ADR-0005, kept by ADR-0008). LangGraph lives in
  `warrant.agents` and nowhere else.

## 9. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| **Design stays at zero and costs 25%** | high | Console is P1-2 and next in the build order |
| Nebius never gets set up → P0-5/P0-6 fail → **ineligible** | medium | Token Factory alone satisfies both; it is one config edit and no GPU |
| README describes replan output that ships late | **resolved** | Agents built; numbers now fall out of the fixtures |
| Nano 4B classifies badly on camera | medium | P1-5 eval measures it before the video; 30B on Token Factory is the fallback |
| Okta ships the missing half at Oktane (22–24 Sept) | low | Prior-art table is timestamped; re-check once before submission |
| Scope creep from a good idea in week 5 | high | §5 is the defence. Re-opening a cut needs a reason |

## 10. Open questions

- Nebius account/credits unverified — blocks P0-5, P0-6, P0-10.
- Exact Token Factory model ID for Nemotron 3 Nano 30B.
- Does Atlan + Immuta use steward metadata as a *runtime* input, or only in an
  approval workflow? Closest thing found to claim §2.1; needs a docs-level read
  before that claim is published.
