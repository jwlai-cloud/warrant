#!/usr/bin/env bash
# Deploy the sovereign fast tier: Nemotron on vLLM, on a Nebius GPU Serverless
# Endpoint. Serverless Endpoints are one of the three forms of "Nebius AI Cloud
# compute" the hackathon rules accept (alongside Serverless Jobs and DevPods) -
# a bare GPU VM is NOT on that list.
#
# NOTE: Serverless Endpoints do not scale to zero. Stop the endpoint when you
# are not working:  nebius ai endpoint stop --id <id>
set -euo pipefail

MODEL="${MODEL:-nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16}"
NAME="${NAME:-warrant-fast-tier}"
PRESET="${PRESET:-1gpu-16vcpu-200gb}"   # TODO(verify) preset name in the console
PLATFORM="${PLATFORM:-gpu-l40s-a}"      # L40S/AMD - cheapest viable box

echo "Deploying ${NAME} serving ${MODEL} on ${PLATFORM}/${PRESET}"

nebius ai endpoint create \
  --name "${NAME}" \
  --image "vllm/vllm-openai:latest" \
  --platform "${PLATFORM}" \
  --preset "${PRESET}" \
  --port 8000 \
  --args "--model=${MODEL}" \
  --args "--served-model-name=${MODEL}" \
  --args "--max-model-len=32768" \
  --args "--trust-remote-code"
  # For Nemotron 3 Nano 30B additionally:
  #   --args "--reasoning-parser-plugin=nano_v3_reasoning_parser.py"
  #   --args "--reasoning-parser=nano_v3"
  #   --args "--enable-auto-tool-choice"
  #   --args "--tool-call-parser=qwen3_coder"

echo
echo "Next:"
echo "  nebius ai endpoint list                      # grab the public URL"
echo "  export WARRANT_VLLM_BASE_URL=https://<url>/v1"
echo "  warrant ask expense-auditor inventory-reconciler -p 'reconcile Q3 claims'"
echo "  nebius ai endpoint stop --id <id>            # STOP IT WHEN DONE"
