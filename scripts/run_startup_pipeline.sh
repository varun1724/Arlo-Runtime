#!/usr/bin/env bash
set -euo pipefail

TOKEN="${ARLO_AUTH_TOKEN:-change-me-to-a-real-secret}"
BASE="${ARLO_BASE_URL:-http://localhost:8000}"
DOMAIN="${1:-AI-powered developer tools}"
FOCUS="${2:-code review, testing automation}"

echo "Starting Startup Idea Pipeline"
echo "  Domain: $DOMAIN"
echo "  Focus: $FOCUS"
echo ""

WORKFLOW_ID=$(curl -s -X POST "$BASE/workflows/from-template/startup_idea_pipeline" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"initial_context\":{\"domain\":\"$DOMAIN\",\"focus_areas\":\"$FOCUS\"}}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

echo "Created workflow: $WORKFLOW_ID"
echo "Polling status..."
echo ""

APPROVAL_HANDLED=false

# Poll for up to 45 minutes
for i in $(seq 1 270); do
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

  # Get latest job progress
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

  echo "  [$i] workflow=$STATUS step=$STEP_IDX ($STEP_NAME) | job: $LATEST_JOB_STATUS"

  # Handle approval interactively
  if [ "$STATUS" = "awaiting_approval" ] && [ "$APPROVAL_HANDLED" = "false" ]; then
    APPROVAL_HANDLED=true
    echo ""
    echo "============================================"
    echo "  APPROVAL REQUIRED: Step $STEP_IDX ($STEP_NAME)"
    echo "============================================"
    echo ""

    # Show ranked ideas and let user pick
    NUM_IDEAS=$(echo "$RESPONSE" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ctx = d.get('context', {})
eval_raw = ctx.get('evaluation_result', '{}')
try:
    ev = json.loads(eval_raw) if isinstance(eval_raw, str) else eval_raw
except: ev = {}
rankings = ev.get('rankings', [])

if not rankings:
    print('0')
else:
    for i, r in enumerate(rankings):
        print(f'---')
        name = r.get('name', 'Unknown')
        feas = r.get('feasibility', '?')
        market = r.get('market_potential', '?')
        weeks = r.get('time_to_mvp_weeks', '?')
        risks = r.get('risks', [])
        print(f'  [{i+1}] {name}')
        print(f'      Feasibility: {feas}/10  |  Market potential: {market}/10  |  Time to MVP: {weeks} weeks')
        if risks:
            print(f'      Risks: {\", \".join(risks[:3])}')

    top = ev.get('top_pick', {})
    if top:
        print(f'')
        print(f'  Recommended: {top.get(\"name\", \"?\")}')
        print(f'  Reasoning: {top.get(\"reasoning\", \"\")[:300]}')

    print(f'{len(rankings)}')
" 2>&1)

    # Print everything except the last line (which is the count)
    COUNT=$(echo "$NUM_IDEAS" | tail -1)
    echo "$NUM_IDEAS" | sed '$d'

    echo ""
    echo "============================================"
    echo ""
    if [ "$COUNT" = "0" ]; then
      echo "No ranked ideas found in evaluation."
      echo "  [0] Skip — finish without building"
      read -p "Enter choice: " CHOICE
      CHOICE="0"
    else
      echo "Which idea would you like to build an MVP for?"
      echo "  [1-$COUNT] Pick an idea by number"
      echo "  [0] Skip — finish the pipeline without building"
      echo ""
      read -p "Enter choice (0-$COUNT): " CHOICE
    fi

    if [ "$CHOICE" = "0" ]; then
      echo ""
      echo "Skipping build step..."
      curl -s -X POST "$BASE/workflows/$WORKFLOW_ID/approve" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"approved": false}' > /dev/null
      echo "Skipped."
      echo ""
    else
      # Extract the chosen idea name and inject it into context
      CHOSEN_IDEA=$(echo "$RESPONSE" | python3 -c "
import sys, json
choice = int('$CHOICE') - 1
d = json.load(sys.stdin)
ctx = d.get('context', {})
eval_raw = ctx.get('evaluation_result', '{}')
try:
    ev = json.loads(eval_raw) if isinstance(eval_raw, str) else eval_raw
except: ev = {}
rankings = ev.get('rankings', [])
if 0 <= choice < len(rankings):
    r = rankings[choice]
    # Override top_pick to the chosen idea
    ev['top_pick'] = {'name': r['name'], 'reasoning': f'User selected this idea', 'mvp_scope': r.get('mvp_scope', r['name'])}
    print(json.dumps(ev))
else:
    print(json.dumps(ev))
")
      echo ""
      echo "Building MVP for choice #$CHOICE..."
      # Approve with overridden evaluation_result containing user's pick
      curl -s -X POST "$BASE/workflows/$WORKFLOW_ID/approve" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"approved\": true, \"context_overrides\": {\"evaluation_result\": $(echo "$CHOSEN_IDEA" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))")}}" > /dev/null
      echo "Approved! Building MVP..."
      echo ""
    fi
    continue
  fi

  if [ "$STATUS" = "succeeded" ]; then
    echo ""
    echo "=== Pipeline succeeded ==="
    echo ""

    # Show jobs
    echo "--- Jobs ---"
    echo "$JOBS_RESPONSE" | python3 -c "
import sys,json
d = json.load(sys.stdin)
for j in d.get('jobs', []):
    print(f\"  Step {j['step_index']}: {j['job_type']} — {j['status']} — {j.get('result_preview','')[:100]}\")
"
    echo ""

    # Show context keys
    echo "--- Workflow Context Keys ---"
    echo "$RESPONSE" | python3 -c "
import sys,json
d = json.load(sys.stdin)
ctx = d.get('context', {})
for k in ctx:
    v = str(ctx[k])
    print(f'  {k}: {v[:120]}...' if len(v) > 120 else f'  {k}: {v}')
"
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
