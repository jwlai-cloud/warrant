# 0001. Build WARRANT: runtime agent-to-agent authorization computed from an architecture model

Date: 2026-09-17
Status: Accepted

## Context

Entry to the Nebius × NVIDIA Global AI Hackathon (submissions close 30 Oct 2026
10:00 PDT / 31 Oct 01:00 AWST; judging 1–15 Dec). Four equally weighted
criteria: Technological Implementation, Design, Potential Impact, Quality of
the Idea. Rules require a runtime call to the Token Factory inference API *or*
deployment on Nebius AI Cloud compute (Serverless Jobs, Serverless Endpoints or
DevPods), plus at least one NVIDIA open source model, Nemotron preferred.

A separate objective: produce credible self-hosted-vLLM evidence, because
resources-sector employers increasingly want self-hosted LLMs.

Three candidate directions were audited against shipped products, and two were
dropped on evidence:

- **Governed personal memory** — the model was incidental to the idea, costing
  two of four criteria (Technological Implementation and Quality of the Idea)
  with no fix available by building harder.
- **Guardrail gateway** — NVIDIA ships **NeMo Guardrails** and the Nebius Agents
  Blueprint includes a Guardrails recipe; the guardrail-proxy space is among the
  most-built in AI safety.
- **Egress-policy routing (HEADFRAME)** — **LLMKube ModelRouter** (Apache-2.0,
  May 2026) already routes local-vs-cloud on `dataClassification` with
  fail-closed enforcement, and NVIDIA **OpenShell** already ships declarative
  network-egress and inference-routing policy.

An audit of the enterprise agent-governance space found the registry-plus-
capability-map design **shipped**: SAP LeanIX AI Agent Hub (GA 4 Nov 2025) makes
AI Agent a first-class Application subtype linked to business capabilities, with
a capability-filtered approved-agent portal; Ardoq shipped agent discovery into
the architecture graph in Mar 2026. Okta Agent-to-Agent Connections (early
access) makes runtime "may agent A call agent B" decisions with per-agent
policies. **Neither side does the other's half.**

## Decision

We will build **WARRANT**: an authorization plane for agent-to-agent calls that
computes the decision from a modelled enterprise architecture — capability
ownership, data-entity stewardship, explicit grants — and returns a refusal with
its architectural reason plus an audit record.

Track: **Best Apps and Agents**.

## Alternatives considered

- **Rowboat-style agent builder** — rejected. The current Rowboat repo is a
  local-first personal AI coworker, and the adjacent builder space (Langflow,
  Flowise, Dify, n8n, Sim, Copilot Studio) is saturated; none of it does
  multi-team governance, so it is competition for attention with no upside.
- **Registry + capability map** — rejected. Shipped by SAP LeanIX ten months ago
  and by Ardoq six months ago. Rebuilding it scores near zero on Quality of the Idea.
- **An EA modelling/diagramming tool** — rejected. A judge cannot distinguish a
  good diagram from a mock-up, and Design rewards a working product experience.

## Consequences

- Makes easier: a legible demo (a refusal with a reason is visible in three
  seconds); a clean two-tier Nemotron story; simultaneous satisfaction of both
  hackathon compliance clauses.
- Makes harder: we must maintain the positioning against LeanIX and OpenShell
  explicitly in the README, or a knowledgeable judge assumes overlap.
- Follow-up: the architecture model must stay small and hand-authored. Discovery
  and ingestion are explicitly out of scope (see ARCHITECTURE.md non-goals).
- Risk accepted: SAP owns LeanIX *and* the identity stack. If they connect
  AI Agent Hub to BTP authorization, the gap closes from the design-time side.
