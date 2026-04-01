#!/usr/bin/env bash
# Launch 6 parallel evolution workflows.
# Start with: docker compose up --build -d --scale worker=6
set -euo pipefail

TOKEN="${ARLO_AUTH_TOKEN:-change-me-to-a-real-secret}"
BASE="${ARLO_BASE_URL:-http://localhost:8000}"
CAPITAL="${1:-1000}"
INSTRUMENTS="${2:-SPY,QQQ,IWM,VTI,GLD,TLT,AGG,EFA}"
SEED_FILE="${3:-}"

# Check for existing running workflows — if found, just monitor
EXISTING=$(curl -s "$BASE/workflows" -H "Authorization: Bearer $TOKEN" 2>/dev/null \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(len([w for w in d.get('workflows',[]) if w['status']=='running']))" 2>/dev/null || echo "0")

if [ "$EXISTING" != "0" ]; then
  echo "$EXISTING evolution workflow(s) already running. Monitoring..."
  echo ""
  exec "$(dirname "$0")/monitor_evolution.sh"
fi

echo "============================================"
echo "  Parallel Strategy Evolution (6 workflows)"
echo "============================================"
echo "  Capital: \$$CAPITAL"
echo "  Instruments: $INSTRUMENTS"
echo "============================================"
echo ""

# Load seed if provided
SEED="none"
if [ -n "$SEED_FILE" ] && [ -f "$SEED_FILE" ]; then
  SEED=$(python3 -c "
import json
with open('$SEED_FILE') as f:
    data = json.load(f)
print(json.dumps(data.get('strategy_submission', 'none')))
")
  echo "Seed strategy loaded from: $SEED_FILE"
fi

# Strategy families to explore
FAMILIES=(
  "dual_momentum_rotation"
  "mean_reversion_vix_filter"
  "volatility_targeting_risk_parity"
  "macro_regime_switching"
  "trend_following_multi_timeframe"
  "adaptive_momentum"
)

DESCRIPTIONS=(
  "Dual Momentum Rotation"
  "Mean Reversion + VIX"
  "Vol Target / Risk Parity"
  "Macro Regime Switching"
  "Trend Following Multi-TF"
  "Adaptive Momentum"
)

# Launch all 6 workflows
declare -a WORKFLOW_IDS
for i in "${!FAMILIES[@]}"; do
  FAMILY="${FAMILIES[$i]}"
  DESC="${DESCRIPTIONS[$i]}"

  if [ "$i" = "0" ] && [ "$SEED" != "none" ]; then
    THIS_SEED="$SEED"
  else
    THIS_SEED="\"none\""
  fi

  WF_ID=$(python3 -c "
import json, subprocess
ctx = {
    'starting_capital': '$CAPITAL',
    'preferred_instruments': '$INSTRUMENTS',
    'risk_tolerance': 'moderate',
    'strategy_family': '$FAMILY',
    'backtest_results': 'none yet',
    'seed_strategy': $THIS_SEED,
}
payload = json.dumps({'initial_context': ctx})
result = subprocess.run(
    ['curl', '-s', '-X', 'POST', '$BASE/workflows/from-template/strategy_evolution',
     '-H', 'Authorization: Bearer $TOKEN', '-H', 'Content-Type: application/json',
     '-d', payload],
    capture_output=True, text=True
)
try:
    data = json.loads(result.stdout)
    print(data.get('id', 'ERROR'))
except:
    print('ERROR')
")

  WORKFLOW_IDS+=("$WF_ID")
  echo "  [$((i+1))] $DESC → $WF_ID"
done

# Save workflow IDs to temp file for the dashboard
IDS_FILE="/tmp/arlo_parallel_ids.txt"
printf '%s\n' "${WORKFLOW_IDS[@]}" > "$IDS_FILE"

echo ""
echo "All 6 workflows launched. Monitoring..."
echo "Winning strategies save to: /workspaces/winning_strategies/"
echo "Press Ctrl+C to stop monitoring (workflows continue in background)."
echo ""
sleep 3

# Hand off to the monitor script
exec "$(dirname "$0")/monitor_evolution.sh"
