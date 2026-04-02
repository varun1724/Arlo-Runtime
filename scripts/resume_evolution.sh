#!/usr/bin/env bash
# Resume 6 parallel evolution workflows, each seeded from its saved state.
# Usage: ./scripts/resume_evolution.sh [saved_file_prefix]
# Default prefix: saved_evolution
set -euo pipefail

TOKEN="${ARLO_AUTH_TOKEN:-change-me-to-a-real-secret}"
BASE="${ARLO_BASE_URL:-http://localhost:8000}"
CAPITAL="${1:-1000}"
INSTRUMENTS="${2:-SPY,QQQ,IWM,VTI,GLD,TLT,AGG,EFA}"
PREFIX="${3:-saved_evolution}"

# Load cached research
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CACHED_RESEARCH_FILE="$SCRIPT_DIR/../workspaces/cached_research.json"
if [ -f "$CACHED_RESEARCH_FILE" ]; then
  CACHED_RESEARCH=$(cat "$CACHED_RESEARCH_FILE")
else
  CACHED_RESEARCH='{"strategies": [], "recommendation": "No cached research"}'
fi

# Check for existing running workflows
EXISTING=$(curl -s "$BASE/workflows" -H "Authorization: Bearer $TOKEN" 2>/dev/null \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(len([w for w in d.get('workflows',[]) if w['status']=='running']))" 2>/dev/null || echo "0")

if [ "$EXISTING" != "0" ]; then
  echo "$EXISTING workflow(s) already running. Monitoring..."
  exec "$(dirname "$0")/monitor_evolution.sh"
fi

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

# Find saved files matching prefix pattern
SAVED_FILES=($(ls ${PREFIX}_*.json 2>/dev/null | sort))

echo "============================================"
echo "  Resume Parallel Evolution (6 workflows)"
echo "============================================"
echo "  Capital: \$$CAPITAL"
echo "  Instruments: $INSTRUMENTS"
echo "  Saved files found: ${#SAVED_FILES[@]}"
echo "============================================"
echo ""

for i in "${!FAMILIES[@]}"; do
  FAMILY="${FAMILIES[$i]}"
  DESC="${DESCRIPTIONS[$i]}"

  # Try to load best strategy from Docker volume first (survives credit exhaustion)
  # Fall back to local saved file
  BEST_FILE=""
  if [ "$i" -lt "${#SAVED_FILES[@]}" ]; then
    # Check if a best_* file exists for this workflow's ID
    SAVED_WF_ID=$(python3 -c "import json; print(json.load(open('${SAVED_FILES[$i]}'))['workflow_id'][:8])" 2>/dev/null || echo "")
    if [ -f "best_${SAVED_WF_ID}.json" ]; then
      BEST_FILE="best_${SAVED_WF_ID}.json"
    fi
  fi

  if [ -n "$BEST_FILE" ]; then
    SEED_FILE="$BEST_FILE"
    SEED=$(python3 -c "
import json
with open('$SEED_FILE') as f:
    data = json.load(f)
strat = data.get('strategy_submission', 'none')
print(json.dumps(strat))
")
    SHARPE=$(python3 -c "import json; print(f'{json.load(open(\"$SEED_FILE\")).get(\"sharpe\",0):.3f}')")
    echo "  [$((i+1))] $DESC — BEST from $SEED_FILE (Sharpe: $SHARPE)"

  elif [ "$i" -lt "${#SAVED_FILES[@]}" ]; then
    SEED_FILE="${SAVED_FILES[$i]}"
    SEED=$(python3 -c "
import json
with open('$SEED_FILE') as f:
    data = json.load(f)
strat = data.get('strategy_submission', 'none')
print(json.dumps(strat))
")
    SHARPE=$(python3 -c "
import json
with open('$SEED_FILE') as f:
    data = json.load(f)
print(f'{data.get(\"metrics_summary\",{}).get(\"sharpe\",0):.3f}')
")
    echo "  [$((i+1))] $DESC — seeded from $SEED_FILE (Sharpe: $SHARPE)"
  else
    SEED="\"none\""
    echo "  [$((i+1))] $DESC — fresh start"
  fi

  WF_ID=$(python3 -c "
import json, subprocess
cached_research = json.dumps($CACHED_RESEARCH)
ctx = {
    'starting_capital': '$CAPITAL',
    'preferred_instruments': '$INSTRUMENTS',
    'risk_tolerance': 'moderate',
    'strategy_family': '$FAMILY',
    'backtest_results': 'none yet',
    'seed_strategy': $SEED,
    'strategy_research': cached_research,
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

  echo "    → Workflow: $WF_ID"
done

echo ""
echo "All 6 workflows launched with seeds. Monitoring..."
echo ""
sleep 3

exec "$(dirname "$0")/monitor_evolution.sh"
