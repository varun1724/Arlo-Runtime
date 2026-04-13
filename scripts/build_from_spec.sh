#!/usr/bin/env bash
# Build and deploy an n8n workflow directly from a spec file, skipping
# the full research pipeline. Use this when you already have a ranked
# idea (from a previous pipeline run or your own spec) and just want
# Claude to build the workflow.json, deploy it to n8n, and test it.
#
# Usage:
#   ./scripts/build_from_spec.sh spec.json
#   ./scripts/build_from_spec.sh spec.json "My Side Hustle Name"
#
# The spec file should be a JSON object with the idea details. At minimum
# it should contain the fields Claude needs to build a good workflow:
#   - name, one_liner, monthly_income_estimate, monthly_costs
#   - n8n_workflow_spec: { trigger_node, node_graph, external_credentials,
#     expected_runtime, frequency, out_of_scope, success_metric }
#
# You can paste a full ranking object from a previous pipeline run's
# synthesis output and it will work — Claude reads the whole thing.

set -euo pipefail

TOKEN="${ARLO_AUTH_TOKEN:-change-me-to-a-real-secret}"
BASE="${ARLO_BASE_URL:-http://localhost:8000}"
SPEC_FILE="${1:?Usage: $0 <spec.json> [workflow-name]}"
WORKFLOW_NAME="${2:-Side Hustle Direct Build}"

if [ ! -f "$SPEC_FILE" ]; then
  echo "Error: spec file '$SPEC_FILE' not found"
  exit 1
fi

# Validate it's valid JSON
python3 -c "import json; json.load(open('$SPEC_FILE'))" 2>/dev/null || {
  echo "Error: '$SPEC_FILE' is not valid JSON"
  exit 1
}

echo "============================================"
echo "  Direct Build from Spec"
echo "============================================"
echo "  Spec file: $SPEC_FILE"
echo "  Workflow: $WORKFLOW_NAME"
echo ""
echo "  Steps: build → deploy → test (approval-gated)"
echo "  Skipping: research, feasibility, contrarian, synthesis"
echo "============================================"
echo ""

# Build the workflow creation request. The build step's prompt includes
# the full spec. The deploy + test steps use the same static-JSON
# pattern as the full side hustle pipeline.
REQUEST_BODY=$(SPEC_FILE="$SPEC_FILE" WORKFLOW_NAME="$WORKFLOW_NAME" python3 -c "
import json, os

spec = json.load(open(os.environ['SPEC_FILE']))
spec_str = json.dumps(spec, indent=2)
name = spec.get('name', 'the selected side hustle')

build_prompt = '''Build an n8n workflow automation for this side hustle.

SELECTED OPPORTUNITY:
''' + spec_str + '''

INSTRUCTIONS:
1. Create a valid n8n workflow JSON file called \`workflow.json\` in the
current directory. The workflow must follow n8n's workflow format with
proper nodes and connections.

2. CRITICAL: the workflow MUST use a Webhook trigger node
(\`n8n-nodes-base.webhook\`) as its entry point — NOT a Schedule Trigger
or Manual Trigger. The parent system triggers this workflow by POSTing
to the webhook URL for the test run, and n8n's REST API does not expose
a general-purpose 'execute workflow' endpoint. Without a webhook trigger,
the test run will fail with 'no webhook URL available'.

3. The webhook trigger's \`parameters.path\` should be the slug from the
spec's trigger_node field if provided, otherwise a descriptive kebab-case
slug.

4. Follow the node_graph from the spec closely. Use the exact n8n node
types listed. Configure ALL required parameters for every node — n8n
will reject activation if any required parameters are missing.

5. Create a README.md explaining what this workflow does, how to
configure credentials, and what payload the webhook expects.

6. Create a BUILD_DECISIONS.md explaining your design choices.

7. Create a \`test_payload.json\` file containing a realistic JSON object
that can be POSTed to the webhook URL to exercise the workflow.

8. Write arlo_manifest.json including a 'workflow_json' key that contains
the full contents of workflow.json.

IMPORTANT: workflow.json must be valid n8n workflow JSON for n8n v2.15.0:
   - a \`name\` string
   - a \`nodes\` array (non-empty, including exactly one webhook trigger)
   - a \`connections\` object
   - a \`settings\` object (empty {} is fine — n8n v2 REJECTS without it)

CRITICAL: Configure ALL required parameters for EVERY node. Do not leave
any node with missing parameters — n8n's activation validator will reject
the workflow with 'Missing or invalid required parameters'. If a node
needs credentials the operator hasn't configured yet, use placeholder
values and document them in the README.
'''

print(json.dumps({
    'name': os.environ['WORKFLOW_NAME'],
    'template_id': 'side_hustle_pipeline',
    'steps': [
        {
            'name': 'build_n8n_workflow',
            'job_type': 'builder',
            'prompt_template': build_prompt,
            'output_key': 'build_result',
            'timeout_override': 2400,
            'max_retries': 1,
            'required_artifacts': [
                'workflow.json',
                'README.md',
                'BUILD_DECISIONS.md',
                'test_payload.json',
            ],
        },
        {
            'name': 'deploy_to_n8n',
            'job_type': 'n8n',
            'prompt_template': '{\"action\": \"create\", \"activate\": true, \"from_previous_build\": true}',
            'output_key': 'deploy_result',
            'condition': {'field': 'build_result', 'operator': 'not_empty'},
            'loop_to': 0,
            'max_loop_count': 3,
            'loop_condition': {
                'field': 'deploy_result',
                'operator': 'contains',
                'value': 'activation_error',
            },
        },
        {
            'name': 'test_run',
            'job_type': 'n8n',
            'prompt_template': '{\"action\": \"execute\", \"from_previous_deploy\": true}',
            'output_key': 'test_result',
            'condition': {'field': 'deploy_result', 'operator': 'not_empty'},
            'requires_approval': True,
        },
    ],
    'initial_context': {
        'selected_hustle': spec_str,
    },
}))
")

WORKFLOW_ID=$(curl -s -X POST "$BASE/workflows" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$REQUEST_BODY" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

echo "Created workflow: $WORKFLOW_ID"
echo "Building: $(python3 -c "import json; print(json.load(open('$SPEC_FILE')).get('name', 'unknown'))")"
echo ""

APPROVAL_HANDLED=false

for i in $(seq 1 360); do
  RESPONSE=$(curl -s "$BASE/workflows/$WORKFLOW_ID" -H "Authorization: Bearer $TOKEN")
  STATUS=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
  STEP_IDX=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['current_step_index'])")

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

  STEP_NAMES=("build_n8n_workflow" "deploy_to_n8n" "test_run")
  STEP_NAME="${STEP_NAMES[$STEP_IDX]:-done}"
  echo "  [$i] step=$STEP_IDX ($STEP_NAME) | $LATEST_JOB_STATUS"

  if [ "$STATUS" = "awaiting_approval" ] && [ "$APPROVAL_HANDLED" = "false" ]; then
    APPROVAL_HANDLED=true
    echo ""
    echo "============================================"
    echo "  TEST RUN APPROVAL"
    echo "============================================"
    echo "  The n8n workflow has been built and deployed."
    echo "  Approve to trigger a test execution via webhook."
    echo ""
    echo "  [1] Run test"
    echo "  [0] Skip test (finish without running)"
    echo ""
    read -p "Enter choice (0-1): " CHOICE

    if [ "$CHOICE" = "0" ]; then
      curl -s -X POST "$BASE/workflows/$WORKFLOW_ID/approve" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"approved": false}' > /dev/null
      echo "Skipped test run."
    else
      curl -s -X POST "$BASE/workflows/$WORKFLOW_ID/approve" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"approved": true}' > /dev/null
      echo "Running test..."
    fi
    APPROVAL_HANDLED=false
    continue
  fi

  if [ "$STATUS" = "succeeded" ]; then
    echo ""
    echo "============================================"
    echo "  BUILD COMPLETE"
    echo "============================================"
    echo ""
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
    echo "Check n8n UI to see the deployed workflow."
    exit 0
  fi

  if [ "$STATUS" = "failed" ]; then
    echo ""
    echo "=== Build failed ==="
    echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"Error: {d.get('error_message','unknown')}\")"
    exit 1
  fi

  sleep 10
done

echo "Timed out waiting for build to complete"
exit 1
