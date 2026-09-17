#!/usr/bin/env bash
# Prove the fast tier before WARRANT depends on it. Checks the three things
# that can each independently fail and would otherwise fail silently inside
# classify.py's except-branch, which fails closed and looks like success.
#
# Usage: WARRANT_VLLM_BASE_URL=... WARRANT_VLLM_API_KEY=... scripts/smoke_fast_tier.sh
set -euo pipefail

BASE="${WARRANT_VLLM_BASE_URL:?set WARRANT_VLLM_BASE_URL (must end in /v1)}"
KEY="${WARRANT_VLLM_API_KEY:-not-needed}"
MODEL="${MODEL:-nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16}"
BUDGET="${BUDGET:-64}"

req() { curl -sS -X POST "${BASE}/chat/completions" \
          -H "Authorization: Bearer ${KEY}" -H 'Content-Type: application/json' -d "$1"; }

echo "1/3 models endpoint"
curl -sS "${BASE}/models" -H "Authorization: Bearer ${KEY}" | jq -e '.data[0].id'

echo "2/3 json_schema response_format returns non-null content"
# The bug in vllm#39103 shows up exactly here: content null, everything in
# reasoning_content. If this line fails, the reasoning parser is eating the
# answer and the classifier will silently fail closed on every call.
R=$(req "{\"model\":\"${MODEL}\",\"messages\":[
      {\"role\":\"system\",\"content\":\"Return only JSON.\"},
      {\"role\":\"user\",\"content\":\"Which of these are financial? Employee.Compensation, Inventory.StockLevel\"}],
    \"temperature\":0,
    \"response_format\":{\"type\":\"json_schema\",\"json_schema\":{\"name\":\"warrant_output\",
      \"schema\":{\"type\":\"object\",\"properties\":{\"data_entities\":{\"type\":\"array\",
      \"items\":{\"type\":\"string\"}}},\"required\":[\"data_entities\"],
      \"additionalProperties\":false},\"strict\":true}}}")
echo "$R" | jq -e '.choices[0].message.content != null' >/dev/null \
  || { echo "FAIL: content is null - reasoning parser swallowed the answer (vllm#39103)"; echo "$R" | jq .; exit 1; }
echo "$R" | jq -er '.choices[0].message.content' | jq -e '.data_entities | type == "array"'

echo "3/3 thinking_token_budget is accepted and bounds reasoning tokens"
B=$(req "{\"model\":\"${MODEL}\",\"messages\":[
      {\"role\":\"user\",\"content\":\"Think carefully, then answer: 17*23?\"}],
    \"temperature\":0,\"max_tokens\":512,\"thinking_token_budget\":${BUDGET}}")
echo "$B" | jq -e '.error == null' >/dev/null \
  || { echo "FAIL: server rejected thinking_token_budget"; echo "$B" | jq .; exit 1; }
RT=$(echo "$B" | jq -r '.usage.completion_tokens_details.reasoning_tokens // "absent"')
echo "   reasoning_tokens=${RT} budget=${BUDGET}"
# ponytail: reported, not asserted. Budget forces the end-of-reasoning token,
# so a small overshoot is expected; assert only if it is wildly over.
[ "$RT" = "absent" ] || [ "$RT" -le $((BUDGET * 3)) ] \
  || { echo "FAIL: budget ignored (${RT} >> ${BUDGET})"; exit 1; }

echo "PASS - fast tier is real. Point WARRANT at it."
