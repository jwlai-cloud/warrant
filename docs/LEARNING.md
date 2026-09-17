# Tech breakdown — what we used and why

> Written for learning after the hackathon, not for judges. Fill in the
> "what surprised us" sections as you go — they are the parts worth re-reading.

## vLLM

**What it actually does:**

**Why we chose it over alternatives:** see ADR-0002.

**The specific parts we used:** `vllm serve`, the `nano_v3` reasoning-parser
plugin, `--tool-call-parser qwen3_coder`, `--reasoning-parser-plugin`,
`chat_template_kwargs.reasoning_budget`, `--mamba-cache-mode`.

**What surprised us:**

**Primary sources:**
- [vLLM recipe: Nemotron 3 Nano 30B](https://recipes.vllm.ai/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16) — launch flags, parser plugin, min vLLM version
- [Nebius: deploy a model on Serverless Endpoints](https://docs.nebius.com/serverless/tutorials/deploy-model) — the `vllm/vllm-openai` container path
- [vLLM docs: Nebius deployment](https://docs.vllm.ai/en/latest/deployment/frameworks/nebius/)

---

## NVIDIA Nemotron 3

**What it actually does:** hybrid Mamba-2 + MoE. Nano 30B-A3B is 30B total /
3.5B active, with only 6 of 52 layers being attention — the rest carry a
constant-size recurrent state instead of a growing KV cache, which is why the
context window is so large and throughput holds up on long inputs.

**The specific parts we used:** `reasoning_budget` (per-request cap on reasoning
tokens, with documented graceful-close semantics), `enable_thinking`, JSON-schema
constrained output for entity classification.

**What surprised us:**

**Primary sources:**
- [Nemotron 3 Nano 30B model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16)
- [Nemotron 3 Nano 30B FP8](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-FP8) — supported hardware is H100/A100, **not L40S**
- [Nebius Token Factory: Nemotron](https://nebius.com/services/token-factory/nemotron) — which Nemotron models are served

---

## Nebius Token Factory / Serverless

**What it actually does:**

**The specific parts we used:** `/v1/chat/completions`, Serverless Endpoints
(GPU + CPU-only), `nebius ai endpoint start|stop`.

**What surprised us:** Serverless Endpoints do **not** scale to zero —
autoscaling is roadmapped Q4+ 2026, and a running endpoint bills continuously at
Compute VM rates. The "no idle GPU costs" marketing line means *you aren't
charged for an idle GPU you didn't provision*, not that the endpoint suspends
itself. This shaped the whole tier/fallback design.

**Primary sources:**
- [Serverless Endpoints docs](https://docs.nebius.com/serverless/endpoints)
- [Serverless pricing & quotas](https://docs.nebius.com/serverless/pricing-quotas)
- [Nebius prices](https://nebius.com/prices)

---

## NVIDIA OpenShell (planned)

**What it actually does:** an Apache-2.0, Rust runtime that executes agents in
sandboxes with kernel-level isolation across four layers — filesystem
(Landlock), network egress filtering, process isolation, and inference privacy
routing — all from declarative YAML policy.

**Why it matters here:** it is the enforcement layer WARRANT's decisions should
drive. WARRANT computes the grant; OpenShell enforces it.

**Primary sources:**
- [OpenShell overview](https://docs.nvidia.com/openshell/about/overview)
- [OpenShell repo](https://github.com/NVIDIA/OpenShell)

---

## The competitive landscape (worth re-reading before the writeup)

- [SAP LeanIX AI Agent Hub](https://www.leanix.net/en/blog/sap-leanix-announces-launch-of-ai-agent-hub-and-key-industry-partnerships) — GA 4 Nov 2025; agents as an Application subtype linked to capabilities
- [Ardoq AI agent discovery](https://www.ardoq.com/blog/ai-agent-discovery) — agents into the architecture graph
- [Okta Agent-to-Agent Connections](https://www.okta.com/blog/product-innovation/securing-agent-to-agent-connections/) — runtime "may A call B", no capability model
- [LLMKube ModelRouter](https://llmkube.com/docs/concepts/model-router) — egress-policy routing, classification is a caller-asserted header
