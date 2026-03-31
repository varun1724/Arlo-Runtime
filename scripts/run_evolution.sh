#!/usr/bin/env bash
set -euo pipefail

TOKEN="${ARLO_AUTH_TOKEN:-change-me-to-a-real-secret}"
BASE="${ARLO_BASE_URL:-http://localhost:8000}"
CAPITAL="${1:-1000}"
INSTRUMENTS="${2:-SPY,QQQ,IWM}"
RISK="${3:-moderate}"

echo "============================================"
echo "  Trading Strategy Evolution"
echo "============================================"
echo "  Capital: \$$CAPITAL"
echo "  Instruments: $INSTRUMENTS"
echo "  Risk tolerance: $RISK"
echo ""
echo "  Claude will research, generate, backtest,"
echo "  and evolve strategies automatically."
echo "  This may run for a long time."
echo "============================================"
echo ""

WORKFLOW_ID=$(curl -s -X POST "$BASE/workflows/from-template/strategy_evolution" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"initial_context\":{\"starting_capital\":\"$CAPITAL\",\"preferred_instruments\":\"$INSTRUMENTS\",\"risk_tolerance\":\"$RISK\",\"strategy_family\":\"any\",\"backtest_results\":\"none yet\"}}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

echo "Created workflow: $WORKFLOW_ID"
echo ""

APPROVAL_HANDLED=false

for i in $(seq 1 5000); do
  RESPONSE=$(curl -s "$BASE/workflows/$WORKFLOW_ID" -H "Authorization: Bearer $TOKEN")
  STATUS=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
  STEP_IDX=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['current_step_index'])")
  STEP_NAME=$(echo "$RESPONSE" | python3 -c "
import sys,json
d = json.load(sys.stdin)
steps = d.get('step_definitions', [])
idx = d.get('current_step_index', 0)
print(steps[idx]['name'] if idx < len(steps) else 'done')
")

  JOBS_RESPONSE=$(curl -s "$BASE/workflows/$WORKFLOW_ID/jobs" -H "Authorization: Bearer $TOKEN")
  JOB_COUNT=$(echo "$JOBS_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('count',0))")
  LATEST=$(echo "$JOBS_RESPONSE" | python3 -c "
import sys,json
d = json.load(sys.stdin)
jobs = d.get('jobs', [])
if jobs:
    j = jobs[-1]
    print(f\"{j['status']} — {j.get('progress_message','')}\")
else:
    print('waiting')
")

  echo "  [$i] step=$STEP_IDX ($STEP_NAME) | jobs=$JOB_COUNT | $LATEST"

  if [ "$STATUS" = "awaiting_approval" ] && [ "$APPROVAL_HANDLED" = "false" ]; then
    APPROVAL_HANDLED=true
    echo ""
    echo "============================================"
    echo "  STRATEGY FOUND — REVIEW RESULTS"
    echo "============================================"
    echo ""

    echo "$RESPONSE" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ctx = d.get('context', {})
results_raw = ctx.get('backtest_results', '{}')
try:
    results = json.loads(results_raw) if isinstance(results_raw, str) else results_raw
except: results = {}
metrics = results.get('metrics', {})
bench = results.get('benchmark_metrics', {})

print('--- Latest Strategy Performance ---')
for k in ['mean_sharpe_ratio', 'sharpe_ratio', 'mean_total_return', 'total_return', 'mean_max_drawdown', 'max_drawdown', 'consistency', 'total_trades']:
    v = metrics.get(k)
    if v is not None:
        if 'return' in k or 'drawdown' in k:
            print(f'  {k}: {v*100:.2f}%')
        else:
            print(f'  {k}: {v}')
print()
if bench:
    print('--- Benchmark (SPY) ---')
    print(f'  Return: {bench.get(\"total_return\",0)*100:.2f}%')
    print(f'  Sharpe: {bench.get(\"sharpe_ratio\",0):.4f}')
"

    echo ""
    echo "  [1] Accept — stop evolution, this strategy is good"
    echo "  [0] Skip — end without accepting"
    echo ""
    read -p "Enter choice (0-1): " CHOICE

    if [ "$CHOICE" = "1" ]; then
      curl -s -X POST "$BASE/workflows/$WORKFLOW_ID/approve" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"approved": true}' > /dev/null
      echo "Strategy accepted!"
    else
      curl -s -X POST "$BASE/workflows/$WORKFLOW_ID/approve" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"approved": false}' > /dev/null
      echo "Skipped."
    fi
    continue
  fi

  if [ "$STATUS" = "succeeded" ]; then
    echo ""
    echo "=== Evolution Complete ==="
    echo ""
    echo "--- Jobs ---"
    echo "$JOBS_RESPONSE" | python3 -c "
import sys,json
d = json.load(sys.stdin)
for j in d.get('jobs', []):
    step = j.get('step_index', '?')
    jtype = j['job_type']
    status = j['status']
    preview = j.get('result_preview', '')[:100]
    print(f'  Step {step} ({jtype}): {status} — {preview}')
"
    exit 0
  fi

  if [ "$STATUS" = "failed" ]; then
    echo ""
    echo "=== Evolution failed ==="
    echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"Error: {d.get('error_message','unknown')}\")"
    exit 1
  fi

  sleep 15
done

echo "Timed out"
exit 1
