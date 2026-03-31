#!/usr/bin/env bash
set -euo pipefail

TOKEN="${ARLO_AUTH_TOKEN:-change-me-to-a-real-secret}"
BASE="${ARLO_BASE_URL:-http://localhost:8000}"
SKILLS="${1:-Python, FastAPI, data engineering, APIs}"
LOCATION="${2:-remote only}"
MIN_RATE="${3:-75}"
PLATFORMS="${4:-Upwork, Toptal, We Work Remotely, RemoteOK}"

echo "============================================"
echo "  Freelance Opportunity Scanner"
echo "============================================"
echo "  Skills: $SKILLS"
echo "  Location: $LOCATION"
echo "  Min rate: \$$MIN_RATE/hr"
echo "  Platforms: $PLATFORMS"
echo ""
echo "  4 research passes then builds a scanner."
echo "============================================"
echo ""

WORKFLOW_ID=$(curl -s -X POST "$BASE/workflows/from-template/freelance_scanner" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"initial_context\":{\"skills\":\"$SKILLS\",\"location_preference\":\"$LOCATION\",\"min_hourly_rate\":\"\$$MIN_RATE/hr\",\"platforms\":\"$PLATFORMS\"}}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

echo "Created workflow: $WORKFLOW_ID"
echo ""

APPROVAL_HANDLED=false

for i in $(seq 1 1080); do
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
  LATEST_JOB_STATUS=$(echo "$JOBS_RESPONSE" | python3 -c "
import sys,json
d = json.load(sys.stdin)
jobs = d.get('jobs', [])
if jobs:
    j = jobs[-1]
    print(f\"{j['status']} — {j.get('progress_message','')}\")
else:
    print('no jobs yet')
")

  echo "  [$i] step=$STEP_IDX ($STEP_NAME) | $LATEST_JOB_STATUS"

  if [ "$STATUS" = "awaiting_approval" ] && [ "$APPROVAL_HANDLED" = "false" ]; then
    APPROVAL_HANDLED=true
    echo ""
    echo "============================================"
    echo "  PICK A NICHE TO MONITOR"
    echo "============================================"
    echo ""

    echo "$RESPONSE" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ctx = d.get('context', {})
synth_raw = ctx.get('synthesis', '{}')
try:
    synth = json.loads(synth_raw) if isinstance(synth_raw, str) else synth_raw
except: synth = {}

summary = synth.get('executive_summary', '')
if summary:
    print('--- Summary ---')
    print(summary[:1000])
    print()

rankings = synth.get('final_rankings', [])
if rankings:
    print('--- Ranked Freelance Niches ---')
    print()
    for r in rankings:
        rank = r.get('rank', '?')
        name = r.get('name', 'Unknown')
        platform = r.get('platform', '?')
        liner = r.get('one_liner', '')
        rate = r.get('hourly_rate_range', '?')
        total = r.get('total_score', 0)
        risks = r.get('surviving_risks', [])
        spec = r.get('monitoring_spec', {})
        print(f'  [{rank}] {name} ({platform})')
        print(f'      {liner}')
        print(f'      Rate: {rate}  |  Score: {total}')
        if spec:
            print(f'      Poll: {spec.get(\"poll_frequency\", \"?\")}  |  Feed: {spec.get(\"feed_url\", \"?\")[:80]}')
            kw = spec.get('search_keywords', [])
            if kw:
                print(f'      Keywords: {\", \".join(kw[:5])}')
        if risks:
            print(f'      Risks: {\", \".join(risks[:2])}')
        print()
    print(len(rankings))
else:
    print('No ranked niches found.')
    print('0')
" 2>&1 > /tmp/arlo_freelance.txt

    COUNT=$(tail -1 /tmp/arlo_freelance.txt)
    sed '$d' /tmp/arlo_freelance.txt

    echo "============================================"
    echo ""
    if [ "$COUNT" = "0" ]; then
      read -p "No niches to build. Press Enter to finish: " _
      curl -s -X POST "$BASE/workflows/$WORKFLOW_ID/approve" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"approved": false}' > /dev/null
    else
      echo "Which niche would you like to build a scanner for?"
      echo "  [1-$COUNT] Pick by number"
      echo "  [0] Skip — finish without building"
      echo ""
      read -p "Enter choice (0-$COUNT): " CHOICE

      if [ "$CHOICE" = "0" ]; then
        curl -s -X POST "$BASE/workflows/$WORKFLOW_ID/approve" \
          -H "Authorization: Bearer $TOKEN" \
          -H "Content-Type: application/json" \
          -d '{"approved": false}' > /dev/null
        echo "Skipped."
      else
        curl -s -X POST "$BASE/workflows/$WORKFLOW_ID/approve" \
          -H "Authorization: Bearer $TOKEN" \
          -H "Content-Type: application/json" \
          -d '{"approved": true}' > /dev/null
        echo "Approved! Building scanner workflow..."
        echo ""
      fi
    fi
    rm -f /tmp/arlo_freelance.txt
    continue
  fi

  if [ "$STATUS" = "succeeded" ]; then
    echo ""
    echo "============================================"
    echo "  SCANNER DEPLOYED"
    echo "============================================"
    echo ""

    echo "--- Jobs ---"
    echo "$JOBS_RESPONSE" | python3 -c "
import sys,json
d = json.load(sys.stdin)
for j in d.get('jobs', []):
    step = j.get('step_index', '?')
    jtype = j['job_type']
    status = j['status']
    preview = j.get('result_preview', '')[:120]
    print(f'  Step {step} ({jtype}): {status} — {preview}')
"
    echo ""
    echo "Check n8n UI at http://localhost:5678 to see your scanner workflow."
    echo "Configure email/Slack credentials in n8n to receive alerts."
    exit 0
  fi

  if [ "$STATUS" = "failed" ]; then
    echo ""
    echo "=== Pipeline failed ==="
    echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"Error: {d.get('error_message','unknown')}\")"
    exit 1
  fi

  sleep 10
done

echo "Timed out waiting for pipeline to complete"
exit 1
