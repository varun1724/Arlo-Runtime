#!/usr/bin/env bash
# Kick off a single apartment_search workflow.
#
# This is the trigger for the recurring SF apartment scan. The
# pipeline itself is one-shot; recurrence is handled by whatever
# scheduler runs this script. The defaults baked into
# apply_apartment_search_defaults() handle every search criterion,
# so this script just POSTs an empty initial_context.
#
# Windows Task Scheduler setup (Git Bash):
#   Program/script:  C:\Program Files\Git\bin\bash.exe
#   Add arguments:   -c "/c/trading/Arlo-Runtime/scripts/run_apartment_scan.sh"
#   Triggers:        Daily at 08:00 and Daily at 18:00 (twice a day)
#   Run whether     [x] checked (so it fires even when not logged in)
#   user is logged on
#
# macOS / Linux launchd / cron:
#   0 8,18 * * *  /path/to/Arlo-Runtime/scripts/run_apartment_scan.sh
#
# Override the default budget / sqft / etc. at trigger time:
#   MAX_RENT=5500 MIN_SQFT=750 ./run_apartment_scan.sh
set -euo pipefail

TOKEN="${ARLO_AUTH_TOKEN:-change-me-to-a-real-secret}"
BASE="${ARLO_BASE_URL:-http://localhost:8000}"

# Optional overrides. When empty, the runtime falls back to the defaults
# in app/workflows/templates.py:_APARTMENT_SEARCH_DEFAULTS.
MAX_RENT="${MAX_RENT:-}"
MIN_SQFT="${MIN_SQFT:-}"
MIN_BEDROOMS="${MIN_BEDROOMS:-}"
MOVE_IN_WINDOW="${MOVE_IN_WINDOW:-}"
MAX_COST_USD="${MAX_COST_USD:-}"   # workflow-level Claude spend cap

CONTEXT=$(python3 -c "
import json, os
ctx = {}
for env_key, ctx_key in [
    ('MAX_RENT', 'max_rent_usd'),
    ('MIN_SQFT', 'min_sqft'),
    ('MIN_BEDROOMS', 'min_bedrooms'),
    ('MOVE_IN_WINDOW', 'move_in_window'),
]:
    v = os.environ.get(env_key, '')
    if v:
        ctx[ctx_key] = int(v) if env_key in ('MAX_RENT','MIN_SQFT','MIN_BEDROOMS') else v
print(json.dumps(ctx))
")

PAYLOAD=$(python3 -c "
import json, os
body = {'initial_context': json.loads('$CONTEXT' or '{}')}
mc = os.environ.get('MAX_COST_USD', '')
if mc:
    body['max_cost_usd'] = float(mc)
print(json.dumps(body))
")

echo "[$(date -Iseconds)] Triggering apartment_search at $BASE"
echo "  context: $CONTEXT"

RESPONSE=$(curl -sS -X POST "$BASE/workflows/from-template/apartment_search" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

WF_ID=$(echo "$RESPONSE" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('id', ''))
except Exception:
    print('')
")

if [ -z "$WF_ID" ]; then
  echo "ERROR: failed to create workflow"
  echo "$RESPONSE"
  exit 1
fi

echo "  workflow_id: $WF_ID"
echo "  stream: $BASE/workflows/$WF_ID/stream"
