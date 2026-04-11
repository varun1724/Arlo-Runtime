#!/usr/bin/env bash
set -euo pipefail

TOKEN="${ARLO_AUTH_TOKEN:-change-me-to-a-real-secret}"
BASE="${ARLO_BASE_URL:-http://localhost:8000}"
FOCUS="${1:-lead generation, content curation, data aggregation}"
BUDGET="${2:-under 50 dollars per month}"
SKILLS="${3:-Python, APIs, web scraping}"
CONSTRAINTS="${4:-must be legal, no spam}"

echo "============================================"
echo "  Side Hustle Automation Pipeline"
echo "============================================"
echo "  Focus: $FOCUS"
echo "  Budget: $BUDGET"
echo "  Skills: $SKILLS"
echo "  Constraints: $CONSTRAINTS"
echo ""
echo "  This pipeline runs 4 research passes then"
echo "  builds and deploys an n8n workflow."
echo "============================================"
echo ""

WORKFLOW_ID=$(curl -s -X POST "$BASE/workflows/from-template/side_hustle_pipeline" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"initial_context\":{\"focus\":\"$FOCUS\",\"budget\":\"$BUDGET\",\"skills\":\"$SKILLS\",\"constraints\":\"$CONSTRAINTS\"}}" \
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
    echo "  APPROVAL REQUIRED: $STEP_NAME"
    echo "============================================"
    echo ""

    # Round 3: polished approval display mirroring the startup script.
    # Shows cost-so-far + executive summary + per-ranking detail with
    # the n8n_workflow_spec fields so the user can make an informed
    # pick without having to read the raw synthesis JSON.
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
        print(f'Estimated USD: \${cost:.4f}')
    if tin is not None and tout is not None:
        print(f'Tokens: {tin:,} in / {tout:,} out')
    print()

synth_raw = ctx.get('synthesis', '{}')
try:
    synth = json.loads(synth_raw) if isinstance(synth_raw, str) else synth_raw
except: synth = {}

summary = synth.get('executive_summary', '')
if summary:
    print('--- Executive Summary ---')
    print(summary[:1000])
    print()

rankings = synth.get('final_rankings', [])
if not rankings:
    print('No ranked hustles found.')
    print('0')
else:
    print('--- Ranked Side Hustles ---')
    print()
    for r in rankings:
        rank = r.get('rank', '?')
        name = r.get('name', 'Unknown')
        liner = r.get('one_liner', '')
        income = r.get('monthly_income_estimate', '?')
        costs = r.get('monthly_costs', '?')
        total = r.get('total_score', 0)
        verdict = r.get('contrarian_verdict', '?')
        risks = r.get('surviving_risks', [])
        spec = r.get('n8n_workflow_spec', {})

        print(f'  [{rank}] {name}')
        print(f'      {liner}')
        print(f'      Income: {income}  |  Costs: {costs}')
        print(f'      Score: {total}  |  Contrarian: {verdict}')
        if spec:
            trigger = spec.get('trigger_node', spec.get('trigger', '?'))
            freq = spec.get('frequency', '?')
            runtime = spec.get('expected_runtime', '?')
            creds = spec.get('external_credentials', [])
            out_of_scope = spec.get('out_of_scope', [])
            success_metric = spec.get('success_metric', '')
            risky_assumption = spec.get('risky_assumption', '')
            print(f'      Trigger: {trigger}')
            print(f'      Frequency: {freq}  |  Runtime: {runtime}')
            if creds:
                print(f'      Credentials needed: {len(creds)} '
                      f'({\", \".join(creds[:3])})')
            if success_metric:
                print(f'      Success metric: {success_metric[:120]}')
            if risky_assumption:
                print(f'      Risky assumption: {risky_assumption[:120]}')
            if out_of_scope:
                print(f'      Out of scope: {\", \".join(out_of_scope[:3])}')
        if risks:
            print(f'      Surviving risks: {\", \".join(risks[:3])}')
        print()

    print(f'{len(rankings)}')
" 2>&1 > /tmp/arlo_hustle.txt

    COUNT=$(tail -1 /tmp/arlo_hustle.txt 2>/dev/null || echo "")
    sed '$d' /tmp/arlo_hustle.txt 2>/dev/null || true

    # Round 5.A5: guard against the Python heredoc crashing. If that
    # happens, the file is truncated/empty, COUNT ends up empty or
    # non-numeric, and the script would otherwise silently show an
    # approval prompt with no options (or garbage choices). Fail loud
    # and cancel the approval so the user can debug the synthesis JSON.
    if [ -z "$COUNT" ] || ! [[ "$COUNT" =~ ^[0-9]+$ ]]; then
      echo ""
      echo "ERROR: approval display block failed to produce a ranking count"
      echo "  (got COUNT='$COUNT')."
      echo "The synthesis rendering Python heredoc likely crashed — inspect"
      echo "the workflow's context.synthesis via the API for malformed JSON."
      echo "Cancelling approval and exiting."
      curl -s -X POST "$BASE/workflows/$WORKFLOW_ID/approve" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"approved": false}' > /dev/null
      rm -f /tmp/arlo_hustle.txt
      exit 1
    fi

    echo "============================================"
    echo ""
    if [ "$COUNT" = "0" ]; then
      read -p "No hustles to build. Press Enter to finish: " _
      curl -s -X POST "$BASE/workflows/$WORKFLOW_ID/approve" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"approved": false}' > /dev/null
    else
      echo "Which side hustle would you like to automate?"
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
        # Round 3: build a context_overrides payload with the chosen
        # ranking under the `selected_hustle` key so the build step's
        # prompt renders correctly. Without this, approve_step's
        # fallback would kick in and default to rank-1, which is
        # wrong when the user picked something else. Matches the
        # startup pipeline's OVERRIDE_PAYLOAD pattern.
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
# Match by 'rank' field first, fall back to positional index
selected = None
for r in rankings:
    if r.get('rank') == choice:
        selected = r
        break
if selected is None:
    selected = rankings[choice - 1]
print(json.dumps({'approved': True, 'context_overrides': {'selected_hustle': selected}}))
")

        if [ -z "$OVERRIDE_PAYLOAD" ]; then
          echo "Invalid choice; skipping."
          curl -s -X POST "$BASE/workflows/$WORKFLOW_ID/approve" \
            -H "Authorization: Bearer $TOKEN" \
            -H "Content-Type: application/json" \
            -d '{"approved": false}' > /dev/null
        else
          curl -s -X POST "$BASE/workflows/$WORKFLOW_ID/approve" \
            -H "Authorization: Bearer $TOKEN" \
            -H "Content-Type: application/json" \
            -d "$OVERRIDE_PAYLOAD" > /dev/null
          echo "Approved! Building n8n workflow..."
          echo ""
        fi
      fi
    fi
    rm -f /tmp/arlo_hustle.txt
    # Reset for possible second approval gate (test_run)
    APPROVAL_HANDLED=false
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
    echo ""
    echo "Check n8n UI at http://localhost:5678 to see the deployed workflow."
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
