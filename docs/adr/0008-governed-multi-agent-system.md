# 0008. WARRANT is a governed multi-agent system, not an authorization gateway

Date: 2026-09-17
Status: Accepted — supersedes the product framing in ADR-0005 (its layering rule stands)

## Context

ADR-0005 stated that WARRANT's core takes no agent-framework dependency, with
LangGraph reserved for "demo agents". That layering rule is fine and stays. Its
framing was not: it let a narrow module-boundary decision stand in for a product
decision, and the product came out as a policy microservice with imaginary
agents described in `config/model/agents.yaml`.

A review raised this directly: the project contains zero agents. The criticism
is correct. Nothing runs, nothing calls anything, and every claim the project
makes about agent-to-agent authorization is asserted rather than demonstrated.

This matters against two judging criteria, not one:

- **Potential Impact** asks whether the solution addresses the problem "based on
  what's demonstrated". With no agents, nothing is demonstrated.
- **Design** asks for "a complete, coherent product experience not just a
  technical proof of concept". A CLI printing a refusal about agents that do not
  exist is the definition of what that criterion screens out.

It also misses the point of entering. The intent is to build enterprise-level
agents. A policy microservice is not that.

## Decision

**WARRANT is a governed multi-agent system.** Agents are the product; the
authorization plane is a component they call.

Concretely:

1. **Real agents, built with LangGraph**, one per organisation unit, doing work
   that genuinely requires data owned by another unit:
   - `expense-auditor` (Finance) — reconciles Q3 expense claims
   - `inventory-reconciler` (Operations) — stock levels and supplier terms
   - `roster-planner` (People & Culture) — roster data
2. **Every cross-boundary call is a governed call.** A shared
   `governed_call` graph node requests a warrant before any inter-agent
   invocation. There is no ungoverned path.
3. **A refusal is an input to the planning loop, not an error.** This is the
   decision that makes the system agentic rather than a proxy demo. On refusal
   the agent receives the structured reasons and replans:
   - **Degrade** — complete what it can with the entities it does hold grants
     for, and report the reduced scope explicitly.
   - **Escalate** — when the task cannot be completed, draft a grant request
     naming the capability, the data entity and the owning org unit, addressed
     to the steward who can approve it.
   - **Record** — write what it could not do and why, so the next run does not
     blindly retry the same refused path.

## Alternatives considered

- **Keep the gateway framing, add demo agents alongside** — rejected. That is
  what ADR-0005 already implied, and it produces agents that exist to exercise
  the gateway rather than to do work. A judge reads the seam immediately.
- **Make the authorization decision itself agentic** — rejected, and ADR-0004
  is the reason. A non-deterministic authorization decision cannot be audited or
  reproduced, and collapses under one follow-up question.
- **Drop the deterministic core and let an agent reason over the model** — same
  rejection, more emphatically. The deterministic core is the part that makes
  this defensible rather than a demo.
- **Speak A2A between the agents from the start** — deferred, not rejected. A2A
  v1.0 §7.5 requires implementers to provide authorization scoping and defines
  no mechanism for it, which is precisely WARRANT's shape; speaking it would
  make "agent-to-agent" literal rather than metaphorical, and an Agent Card
  extension declaring each agent's data entities would make the architecture
  model partly self-describing instead of hand-authored. But it is a transport
  concern, and a half-working protocol layer shows a judge nothing. The
  inter-agent call is therefore kept behind a single seam so the transport can
  be swapped once replanning works. See the open question in PROGRESS.md.

## Consequences

- **ADR-0004 is unaffected and gets sharper.** The model still never decides
  authorization. It decides what to *do about* a refusal. Two clearly different
  jobs, cleanly separated, and the split is easier to defend than before: the
  deterministic half is auditable, the agentic half cannot escalate its own
  privileges because it never holds the grant decision.
- **ADR-0005's layering rule survives**: `warrant.engine` and
  `warrant.providers` import no agent framework. The new `warrant.agents`
  package does. The authorization plane remains callable by any framework.
- **ADR-0007 becomes load-bearing for the demo.** The A/B it pins — same two
  agents, different purpose, opposite outcome — is exactly the branch point the
  replanning loop hangs off. Degrade is only demonstrable because a narrower
  purpose genuinely grants.
- **The work order inverts.** The deterministic core is built and tested; the
  agents are now the primary remaining build.
- **The demo changes shape.** It is no longer "watch a refusal print". It is an
  agent attempting a real task, being refused mid-task, and visibly doing
  something intelligent about it — finishing at reduced scope with the reason
  attached, or producing a grant request addressed to a named human.
- **A new test is required and is a hard gate**: no path from an agent to
  another org unit's data may bypass `governed_call`. Ungoverned reach is the
  one bug that would invalidate every claim the project makes, so it is asserted
  structurally rather than trusted to review.
- **The escalation branch is where this wins or turns into a gimmick.** A grant
  request naming the capability, the entity and the actual human owner is a
  product. A generic "access denied, contact your administrator" is not. If only
  one of the two branches ships, it is escalate.
