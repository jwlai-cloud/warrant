# WARRANT

**An authorization plane for agent-to-agent calls that decides from your
enterprise architecture model — and returns the reason.**

Built for the Nebius × NVIDIA Global AI Hackathon 2026 · Track: Best Apps and Agents

---

## The problem

Every enterprise agent platform can now tell you *which* agents exist and who
owns them. None of them can answer the question that actually matters when one
team's agent calls another team's agent:

> *Is this agent allowed to reach that data — and on whose authority?*

SAP LeanIX knows who owns the *Accounts Payable* capability and the *Customer
PII* data entity, but makes no runtime decision. Okta's Agent-to-Agent
Connections makes the runtime decision, but has no idea what a business
capability is. Google's own agent-platform docs leave cross-boundary
authorization "for customers to implement." A2A delegates authentication to
OAuth and leaves authorization to each organisation. NIST was still framing
delegation-of-authority as an open question in February 2026.

**WARRANT is the join.**

## What it does

```
$ warrant ask expense-auditor inventory-reconciler \
    -p "Reconcile Q3 expense claims against supplier stock movements"

╭────────── Denied — expense-auditor → inventory-reconciler ──────────╮
│ Denied. The Inventory Reconciler reads Employee Compensation,       │
│ stewarded by People & Culture. The Expense Management capability    │
│ holds no grant to that entity.                                      │
╰──────────── warrant 02c5fcad — served by fast/vllm ─────────────────╯

  caller_capability  Caller 'Expense Auditor' serves capability 'Expense
                     Management', owned by Finance.
  grant_found        Capability 'Expense Management' holds a grant to
                     'Supplier Contract' (confidential), stewarded by
                     Operations, granted by coo@example.com.
  grant_missing      Callee reads Data Entity 'Employee.Compensation'
                     (restricted), stewarded by People & Culture.
                     Capability 'Expense Management' holds no grant.
```

Every decision — granted or refused — is written to an append-only audit log.

## The model never decides

Grant resolution is **pure, deterministic graph traversal**. Nemotron is used for
exactly two things: narrowing which data entities a specific call touches, and
writing the explanation a human reads. The classifier can only ever *narrow* the
callee's declared entity set, never widen it, so a hallucination cannot grant
access — it can only cause a denial. See [ADR-0004](docs/adr/0004-the-model-never-decides.md).

## Architecture in one breath

A small subset of the TOGAF content metamodel — Organization Unit, Business
Capability, Data Entity, Agent, Grant — loaded from YAML, validated on load. A
two-tier Nemotron stack: a sovereign fast tier (self-hosted Nemotron Nano on
vLLM) and a managed deep tier (Nemotron Super/Ultra on Nebius Token Factory).
One OpenAI-compatible client serves both; switching a tier is a config edit, not
a branch. Full detail in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quickstart (no GPU, no credits, no network)

```bash
pip install -e ".[dev]"
export WARRANT_CONFIG=config/warrant.offline.yaml
warrant validate
warrant ask expense-auditor inventory-reconciler -p "reconcile Q3 claims"
warrant log
pytest -q
```

## Running against real inference

```bash
cp .env.example .env    # fill in the Token Factory key and the vLLM endpoint URL
set -a && source .env && set +a
export WARRANT_CONFIG=config/warrant.yaml
warrant serve
```

`config/warrant.yaml` is the only thing that decides whether a tier is served by
self-hosted vLLM or Nebius Token Factory:

```yaml
tiers:
  fast:
    kind: vllm              # <- change to token_factory; nothing else changes
    base_url: ${WARRANT_VLLM_BASE_URL}
    model: nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16
    reasoning_budget: 64
```

If the fast tier is unreachable — because the GPU endpoint is stopped to save
money — the router falls through to the deep tier, the request still succeeds,
and the audit record names the tier that served it.

## What this is not

- **Not an agent builder.** WARRANT is framework-agnostic by design; any agent
  that can make an HTTP call can ask for a warrant.
- **Not an EA repository.** SAP LeanIX AI Agent Hub already models agents against
  capability maps. WARRANT consumes a model and makes a runtime decision.
- **Not a sandbox or a gateway.** NVIDIA OpenShell is the enforcement layer;
  WARRANT is the decision layer above it.

## Prior art this builds on and does not duplicate

| Project | What it does | What it doesn't |
|---|---|---|
| [SAP LeanIX AI Agent Hub](https://www.leanix.net/en/blog/sap-leanix-announces-launch-of-ai-agent-hub-and-key-industry-partnerships) | Agents as EA objects linked to capabilities | No runtime decision |
| [Okta A2A Connections](https://www.okta.com/blog/product-innovation/securing-agent-to-agent-connections/) | Runtime "may A call B" | No capability or data-ownership model |
| [LLMKube ModelRouter](https://llmkube.com/docs/concepts/model-router) | Routes local-vs-cloud on data classification | Classification is a caller-asserted header |
| [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) | Kernel-level sandbox + egress/inference policy | Policies are hand-written; no org model |

## Licence

MIT (code). NVIDIA Nemotron weights are separately licensed under the NVIDIA
Nemotron Open Model License — not MIT, not Apache.
