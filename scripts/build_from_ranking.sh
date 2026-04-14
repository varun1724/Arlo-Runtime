#!/usr/bin/env bash
# Build an n8n workflow directly from a ranking in a completed pipeline run.
#
# Usage:
#   ./scripts/build_from_ranking.sh <workflow-id> [rank]
#
# Examples:
#   ./scripts/build_from_ranking.sh abc123-def456    # defaults to rank 1
#   ./scripts/build_from_ranking.sh abc123-def456 2  # build rank #2
#   ./scripts/build_from_ranking.sh abc123-def456 3  # build rank #3
#
# The script:
#   1. Fetches the workflow's synthesis from the API
#   2. Extracts the specified ranking
#   3. Saves it as specs/<name>.json
#   4. Hands off to build_from_spec.sh to build + deploy + test

set -euo pipefail

TOKEN="${ARLO_AUTH_TOKEN:-change-me-to-a-real-secret}"
BASE="${ARLO_BASE_URL:-http://localhost:8000}"
WORKFLOW_ID="${1:?Usage: $0 <workflow-id> [rank]}"
RANK="${2:-1}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SPECS_DIR="$PROJECT_DIR/specs"
mkdir -p "$SPECS_DIR"

echo "============================================"
echo "  Build from Pipeline Ranking"
echo "============================================"
echo "  Workflow: $WORKFLOW_ID"
echo "  Rank: #$RANK"
echo "============================================"
echo ""

# Fetch workflow to a temp file (avoids shell escaping issues with JSON)
TMPFILE=$(mktemp)
trap "rm -f $TMPFILE" EXIT

curl -s "$BASE/workflows/$WORKFLOW_ID" \
  -H "Authorization: Bearer $TOKEN" > "$TMPFILE"

# Extract the ranking via Python
SPEC_FILE=$(RANK="$RANK" SPECS_DIR="$SPECS_DIR" TMPFILE="$TMPFILE" python3 -c "
import json, os, re, sys

rank = int(os.environ['RANK'])
specs_dir = os.environ['SPECS_DIR']

with open(os.environ['TMPFILE']) as f:
    d = json.load(f)

status = d.get('status', 'unknown')
if status not in ('succeeded', 'awaiting_approval'):
    print(f'ERROR: workflow status is \"{status}\" — need a completed pipeline with synthesis', file=sys.stderr)
    sys.exit(1)

ctx = d.get('context', {})
synth_raw = ctx.get('synthesis', '{}')
if isinstance(synth_raw, str):
    try:
        synth = json.loads(synth_raw)
    except json.JSONDecodeError:
        print('ERROR: synthesis in workflow context is not valid JSON', file=sys.stderr)
        sys.exit(1)
else:
    synth = synth_raw or {}

rankings = synth.get('final_rankings', [])
if not rankings:
    print('ERROR: no final_rankings found in synthesis', file=sys.stderr)
    sys.exit(1)

# Find the requested rank
selected = None
for r in rankings:
    if r.get('rank') == rank:
        selected = r
        break

if selected is None:
    print(f'ERROR: rank #{rank} not found. Available rankings:', file=sys.stderr)
    for r in rankings:
        print(f'  #{r.get(\"rank\", \"?\")} — {r.get(\"name\", \"unknown\")}', file=sys.stderr)
    sys.exit(1)

# Show all available rankings for context
print('Available rankings:', file=sys.stderr)
for r in rankings:
    marker = ' <-- selected' if r.get('rank') == rank else ''
    print(f'  #{r.get(\"rank\", \"?\")} — {r.get(\"name\", \"unknown\")}{marker}', file=sys.stderr)
print(file=sys.stderr)

# Generate a clean filename from the name
name = selected.get('name', 'unknown')
slug = re.sub(r'[^a-zA-Z0-9]+', '_', name).strip('_').lower()[:60]
spec_file = os.path.join(specs_dir, f'{slug}.json')

json.dump(selected, open(spec_file, 'w'), indent=2)
print(spec_file)
") || exit 1

if [ -z "$SPEC_FILE" ]; then
  echo "Failed to extract ranking"
  exit 1
fi

NAME=$(python3 -c "import json; print(json.load(open('$SPEC_FILE')).get('name', 'Unknown'))")
echo "Building: $NAME"
echo "Spec saved: $SPEC_FILE"
echo ""

# Hand off to build_from_spec.sh
exec "$SCRIPT_DIR/build_from_spec.sh" "$SPEC_FILE" "$NAME"
