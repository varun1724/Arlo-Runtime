#!/usr/bin/env bash
set -euo pipefail

TOKEN="${ARLO_AUTH_TOKEN:-change-me-to-a-real-secret}"
BASE="${ARLO_BASE_URL:-http://localhost:8000}"
PROMPT="${1:-Create a basic FastAPI project with a health endpoint, SQLAlchemy models, and a Dockerfile}"

echo "Creating builder job: '$PROMPT'"
JOB_ID=$(curl -s -X POST "$BASE/jobs" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"job_type\":\"builder\",\"prompt\":\"$PROMPT\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

echo "Created job: $JOB_ID"
echo "Polling status (builder jobs may take up to 10 minutes)..."

# Poll for up to 12 minutes (72 iterations * 10s)
for i in $(seq 1 72); do
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
    echo "--- Workspace ---"
    WORKSPACE=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('workspace_path',''))")
    echo "Path: $WORKSPACE"
    echo ""
    echo "--- Artifacts ---"
    curl -s "$BASE/jobs/$JOB_ID/artifacts" -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for a in data.get('artifacts', []):
    kind = 'DIR ' if a.get('is_dir') else 'FILE'
    size = a.get('size_bytes', 0)
    print(f'  {kind} {a[\"path\"]} ({size} bytes)')
print(f\"Total: {data.get('count', 0)} items\")
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
