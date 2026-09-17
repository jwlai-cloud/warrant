# Tech breakdown — what we used and why

> Written for learning after the hackathon, not for judges. Fill in the
> "what surprised us" sections as you go — they are the parts worth re-reading.

## vLLM

**What it actually does:**

**Why we chose it over alternatives:** see ADR-0002.

**The specific parts we used:** `python3 -m vllm.entrypoints.openai.api_server`,
`--reasoning-parser-plugin` + `--reasoning-parser nano_v3`,
`--mamba_ssm_cache_dtype float32`, `response_format: json_schema`, and the
top-level `thinking_token_budget` sampling parameter.

**What we deliberately did NOT use, and why:** `--tool-call-parser qwen3_coder`
(WARRANT issues no tool calls) and `--reasoning-config` (open bug vllm#39103
nulls out `content` on Nemotron 3). ADR-0006.

**What surprised us:** the reasoning parser is the component most likely to
break a JSON-schema call, because when it misfires the answer does not error -
it lands in `reasoning_content` and `content` comes back `null`. Downstream that
is indistinguishable from a model that returned nothing, and `classify.py` fails
closed on it, so the system looks like it is working while the fast tier is doing
nothing. `scripts/smoke_fast_tier.sh` exists specifically to catch that.

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

**The specific parts we used:** `thinking_token_budget` (per-request cap on
reasoning tokens - vLLM forces the reasoning-end token once the count is
reached), `chat_template_kwargs.enable_thinking`, JSON-schema constrained output
for entity classification.

**What surprised us:** `reasoning_budget` is not a wire parameter and never was
- the scaffold invented it by analogy. The real per-request knob is vLLM's
top-level `thinking_token_budget`; `chat_template_kwargs` carries only
`enable_thinking`. A third mechanism exists (a logits processor configured with
`THINKING_BUDGET_LOGITS_PROCESSOR_ARGS` at server launch) which is server-wide,
not per-request. Three similar-sounding things, one of them fictional.

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
