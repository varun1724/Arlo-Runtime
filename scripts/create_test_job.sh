#!/usr/bin/env bash
set -euo pipefail

TOKEN="${ARLO_AUTH_TOKEN:-change-me-to-a-real-secret}"
BASE="${ARLO_BASE_URL:-http://localhost:8000}"
PROMPT="${1:-Research startup opportunities in the pet tech market}"

echo "Creating research job: '$PROMPT'"
JOB_ID=$(curl -s -X POST "$BASE/jobs" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"job_type\":\"research\",\"prompt\":\"$PROMPT\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

echo "Created job: $JOB_ID"
echo "Polling status (research jobs may take a few minutes)..."

# Poll for up to 10 minutes (60 iterations * 10s)
for i in $(seq 1 60); do
  RESPONSE=$(curl -s "$BASE/jobs/$JOB_ID" -H "Authorization: Bearer $TOKEN")
  STATUS=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
  STEP=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('current_step',''))")
  MSG=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('progress_message',''))")
  echo "  [$i] status=$STATUS step=$STEP — $MSG"

  if [ "$STATUS" = "succeeded" ]; then
    echo ""
    echo "=== Job succeeded ==="
    echo ""
    echo "--- Preview ---"
    echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('result_preview',''))"
    echo ""
    echo "--- Structured Report ---"
    echo "$RESPONSE" | python3 -c "
import sys, json
data = json.load(sys.stdin)
rd = data.get('result_data')
if rd:
    print(json.dumps(json.loads(rd), indent=2))
else:
    print('(no structured data)')
"
    exit 0
  fi

  if [ "$STATUS" = "failed" ]; then
    echo ""
    echo "=== Job failed ==="
    echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"Error: {d.get('error_message','unknown')}\")"
    exit 1
  fi

  sleep 10
done

echo "Timed out waiting for job to complete"
exit 1
