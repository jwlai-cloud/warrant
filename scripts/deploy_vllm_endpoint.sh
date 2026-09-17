#!/usr/bin/env bash
# Deploy the sovereign fast tier: Nemotron 3 Nano on vLLM, on a Nebius GPU
# Serverless Endpoint. Serverless Endpoints are one of the three forms of
# "Nebius AI Cloud compute" the hackathon rules accept (alongside Serverless
# Jobs and DevPods) - a bare GPU VM is NOT on that list.
#
# Flags below are taken from the Nebius deploy-model tutorial and the NVIDIA
# model card, not from memory. See docs/adr/0006-fast-tier-flag-set.md for why
# the tool-call parser and --reasoning-config are deliberately absent.
#
# Endpoints do NOT scale to zero. Stop it when you stop working:
#   nebius ai endpoint stop --id <id>     # stopped = no compute charge
set -euo pipefail

# Nano 4B needs vLLM >= 0.15.1 and --mamba_ssm_cache_dtype float32.
# Nano 30B-A3B needs >= 0.12.0 but wants an H100/A100, not an L40S.
MODEL="${MODEL:-nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16}"
IMAGE="${IMAGE:-vllm/vllm-openai:v0.18.0-cu130}"
NAME="${NAME:-warrant-fast-tier}"
PLATFORM="${PLATFORM:-gpu-l40s-a}"
PRESET="${PRESET:-1gpu-8vcpu-32gb}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-32768}"   # card says 262144; we need far less

: "${AUTH_TOKEN:?set AUTH_TOKEN to a random secret; it becomes WARRANT_VLLM_API_KEY}"

# The nano_v3 reasoning parser is still a downloadable plugin, not built in.
# It is fetched into the container at start because there is no image layer
# for it. Splitting reasoning from content is what keeps the classifier's
# JSON parseable.
PARSER_URL="https://huggingface.co/${MODEL}/resolve/main/nano_v3_reasoning_parser.py"

echo "Deploying ${NAME}: ${MODEL} on ${PLATFORM}/${PRESET} via ${IMAGE}"

nebius ai endpoint create \
  --name "${NAME}" \
  --image "${IMAGE}" \
  --container-command "/bin/sh" \
  --args "-c" \
  --args "wget -q ${PARSER_URL} -O /tmp/nano_v3_reasoning_parser.py && \
          exec python3 -m vllm.entrypoints.openai.api_server \
            --model ${MODEL} \
            --served-model-name ${MODEL} \
            --host 0.0.0.0 --port 8000 \
            --max-model-len ${MAX_MODEL_LEN} \
            --max-num-seqs 8 \
            --tensor-parallel-size 1 \
            --trust-remote-code \
            --mamba_ssm_cache_dtype float32 \
            --reasoning-parser-plugin /tmp/nano_v3_reasoning_parser.py \
            --reasoning-parser nano_v3" \
  --platform "${PLATFORM}" \
  --preset "${PRESET}" \
  --container-port 8000 \
  --shm-size 16Gi \
  --public \
  --auth token \
  --token "${AUTH_TOKEN}" \
  --preemptible

cat <<NEXT

Next:
  URL=\$(nebius ai endpoint get-by-name --name ${NAME} --format json \\
        | jq -r '.status.public_endpoints[] | select(startswith("https://"))' | head -1)
  export WARRANT_VLLM_BASE_URL="\$URL/v1"
  export WARRANT_VLLM_API_KEY="${AUTH_TOKEN}"

  scripts/smoke_fast_tier.sh          # proves the tier before WARRANT touches it
  warrant ask expense-auditor inventory-reconciler -p 'reconcile Q3 claims'

  nebius ai endpoint stop --id <id>   # STOP IT WHEN DONE
NEXT
