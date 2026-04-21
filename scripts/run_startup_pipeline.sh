#!/usr/bin/env bash
set -euo pipefail

TOKEN="${ARLO_AUTH_TOKEN:-change-me-to-a-real-secret}"
BASE="${ARLO_BASE_URL:-http://localhost:8000}"
DOMAIN="${1:-AI-powered developer tools}"
FOCUS="${2:-code review, testing automation}"
CONSTRAINTS="${3:-solo developer, limited budget}"

# Round 6: deep research mode opt-in. Set ARLO_DEEP_MODE=1 to enable
# broader research (15-20 opportunities, longer step timeouts, more
# contrarian sourcing depth, 7 final rankings instead of 5).
# Recommended ON for Claude Max users where token cost is effectively
# zero.
DEEP_MODE_FLAG="false"
DEEP_MODE_LABEL="off"
case "${ARLO_DEEP_MODE:-}" in
  1|true|TRUE|yes|YES|on|ON)
    DEEP_MODE_FLAG="true"
    DEEP_MODE_LABEL="ON"
    ;;
esac

echo "============================================"
echo "  Startup Idea Pipeline (Deep Research)"
echo "============================================"
echo "  Domain: $DOMAIN"
echo "  Focus: $FOCUS"
echo "  Constraints: $CONSTRAINTS"
echo "  Deep research mode: $DEEP_MODE_LABEL"
echo ""
echo "  This pipeline runs 4 research passes before"
echo "  asking you to pick an idea. Expect 30-60 min."
echo "============================================"
echo ""

# Build the JSON body via a python heredoc so the input strings can
# contain arbitrary punctuation (em dashes, quotes, commas) without
# breaking the curl call.
REQUEST_BODY=$(
  DOMAIN="$DOMAIN" FOCUS="$FOCUS" CONSTRAINTS="$CONSTRAINTS" \
  DEEP_MODE_FLAG="$DEEP_MODE_FLAG" \
  python3 -c "
import json, os
print(json.dumps({
    'initial_context': {
        'domain':       os.environ['DOMAIN'],
        'focus_areas':  os.environ['FOCUS'],
        'constraints':  os.environ['CONSTRAINTS'],
    },
    'deep_research_mode': os.environ['DEEP_MODE_FLAG'] == 'true',
}))
"
)

WORKFLOW_ID=$(curl -s -X POST "$BASE/workflows/from-template/startup_idea_pipeline" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$REQUEST_BODY" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

echo "Created workflow: $WORKFLOW_ID"
echo ""

APPROVAL_HANDLED=false

# Poll for up to 3 hours (1080 iterations * 10s)
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

  # Get latest job progress (Round 4: also includes live token/cost data)
  JOBS_RESPONSE=$(curl -s "$BASE/workflows/$WORKFLOW_ID/jobs" -H "Authorization: Bearer $TOKEN")
  LATEST_JOB_STATUS=$(echo "$JOBS_RESPONSE" | python3 -c "
import sys,json
d = json.load(sys.stdin)
jobs = d.get('jobs', [])
if jobs:
    j = jobs[-1]
    base = f\"{j['status']} — {j.get('progress_message','')}\"
    tin = j.get('tokens_input')
    tout = j.get('tokens_output')
    cost = j.get('estimated_cost_usd')
    if tin is not None or tout is not None or cost is not None:
        parts = []
        if tin is not None and tout is not None:
            parts.append(f\"{tin:,} in / {tout:,} out\")
        if cost is not None:
            parts.append(f'\${cost:.4f}')
        if parts:
            base += ' | ' + ' '.join(parts)
    print(base)
else:
    print('no jobs yet')
")

  echo "  [$i] step=$STEP_IDX ($STEP_NAME) | $LATEST_JOB_STATUS"

  # Handle approval interactively
  if [ "$STATUS" = "awaiting_approval" ] && [ "$APPROVAL_HANDLED" = "false" ]; then
    APPROVAL_HANDLED=true
    echo ""
    echo ""
    echo "============================================"
    echo "  RESEARCH COMPLETE — PICK AN IDEA"
    echo "============================================"
    echo ""

    # Display the synthesis results
    echo "$RESPONSE" | python3 -c "
import sys, json

d = json.load(sys.stdin)
ctx = d.get('context', {})

# Round 3: show cost so far before the user picks
cost = d.get('total_estimated_cost_usd')
tin = d.get('total_tokens_input')
tout = d.get('total_tokens_output')
if cost is not None or tin is not None:
    print('--- Research Cost So Far ---')
    if cost is not None:
        print(f'  Estimated USD: \${cost:.4f}')
    if tin is not None and tout is not None:
        print(f'  Tokens: {tin:,} in / {tout:,} out')
    print()

# Parse synthesis
synth_raw = ctx.get('synthesis', '{}')
try:
    synth = json.loads(synth_raw) if isinstance(synth_raw, str) else synth_raw
except: synth = {}

# Show executive summary
summary = synth.get('executive_summary', '')
if summary:
    print('--- Executive Summary ---')
    print(summary[:1000])
    print()

# Show ranked ideas
rankings = synth.get('final_rankings', [])
if not rankings:
    print('No ranked ideas found.')
    print('0')
else:
    print('--- Ranked Opportunities ---')
    print()
    for r in rankings:
        rank = r.get('rank', '?')
        name = r.get('name', 'Unknown')
        liner = r.get('one_liner', '')
        scores = r.get('scores', {})
        total = r.get('total_score', 0)
        risks = r.get('surviving_risks', [])
        mvp = r.get('mvp_spec', {})

        print(f'  [{rank}] {name}')
        print(f'      {liner}')
        print(f'      Scores: timing={scores.get(\"market_timing\",\"?\")}/10  '
              f'defensibility={scores.get(\"defensibility\",\"?\")}/10  '
              f'feasibility={scores.get(\"solo_dev_feasibility\",\"?\")}/10  '
              f'revenue={scores.get(\"revenue_potential\",\"?\")}/10  '
              f'evidence={scores.get(\"evidence_quality\",\"?\")}/10  '
              f'TOTAL={total}/100')
        if risks:
            print(f'      Risks: {\", \".join(risks[:3])}')
        if mvp:
            build_time = mvp.get('build_time_weeks', '?')
            tech = mvp.get('tech_stack', '?')
            print(f'      MVP: {build_time} weeks, {tech}')
        print()

    print(f'{len(rankings)}')
" 2>&1 > /tmp/arlo_synthesis.txt

    COUNT=$(tail -1 /tmp/arlo_synthesis.txt)
    # Print everything except the last line
    sed '$d' /tmp/arlo_synthesis.txt

    echo "============================================"
    echo ""
    if [ "$COUNT" = "0" ]; then
      echo "No ideas to build."
      read -p "Press Enter to finish: " _
      curl -s -X POST "$BASE/workflows/$WORKFLOW_ID/approve" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"approved": false}' > /dev/null
    else
      echo "Which idea would you like to build an MVP for?"
      echo "  [1-$COUNT] Pick an idea by number"
      echo "  [0] Skip — finish without building"
      echo ""
      read -p "Enter choice (0-$COUNT): " CHOICE

      if [ "$CHOICE" = "0" ]; then
        echo ""
        echo "Skipping build step..."
        curl -s -X POST "$BASE/workflows/$WORKFLOW_ID/approve" \
          -H "Authorization: Bearer $TOKEN" \
          -H "Content-Type: application/json" \
          -d '{"approved": false}' > /dev/null
        echo "Done."
      else
        # Validate choice is in range and build the context_overrides payload
        # containing the user's selected ranking. The build_mvp step has
        # context_inputs=["selected_idea"], so this is what gets passed to the
        # builder prompt — the user's pick, not always rank-1.
        OVERRIDE_PAYLOAD=$(echo "$RESPONSE" | CHOICE="$CHOICE" python3 -c "
import sys, json, os
choice = int(os.environ['CHOICE'])
d = json.load(sys.stdin)
ctx = d.get('context', {})
synth_raw = ctx.get('synthesis', '{}')
try:
    synth = json.loads(synth_raw) if isinstance(synth_raw, str) else synth_raw
except Exception:
    synth = {}
rankings = synth.get('final_rankings', [])
if not rankings or choice < 1 or choice > len(rankings):
    print('INVALID', file=sys.stderr)
    sys.exit(2)
# Prefer matching by 'rank' field if present; fall back to position.
selected = None
for r in rankings:
    if r.get('rank') == choice:
        selected = r
        break
if selected is None:
    selected = rankings[choice - 1]
print(json.dumps({'approved': True, 'context_overrides': {'selected_idea': selected}}))
")
        if [ -z "$OVERRIDE_PAYLOAD" ]; then
          echo ""
          echo "Invalid choice #$CHOICE — must be between 1 and $COUNT."
          echo "Aborting without approval."
          exit 1
        fi

        echo ""
        echo "Building MVP for choice #$CHOICE..."
        curl -s -X POST "$BASE/workflows/$WORKFLOW_ID/approve" \
          -H "Authorization: Bearer $TOKEN" \
          -H "Content-Type: application/json" \
          -d "$OVERRIDE_PAYLOAD" > /dev/null
        echo "Approved! Building MVP (this may take 10-20 minutes)..."
        echo ""
      fi
    fi
    rm -f /tmp/arlo_synthesis.txt
    continue
  fi

  if [ "$STATUS" = "succeeded" ]; then
    echo ""
    echo "============================================"
    echo "  PIPELINE COMPLETE"
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
