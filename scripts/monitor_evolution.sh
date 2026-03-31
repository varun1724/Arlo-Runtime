#!/usr/bin/env bash
# Monitor all running evolution workflows.
set -euo pipefail

TOKEN="${ARLO_AUTH_TOKEN:-change-me-to-a-real-secret}"
BASE="${ARLO_BASE_URL:-http://localhost:8000}"

# Collect all workflow IDs once
IDS=$(curl -s "$BASE/workflows" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "
import json,sys
d = json.load(sys.stdin)
for w in d.get('workflows',[]):
    if w['status'] in ('running','awaiting_approval'):
        print(w['id'])
")

if [ -z "$IDS" ]; then
  echo "No running workflows found."
  exit 0
fi

ID_ARRAY=($IDS)
echo "Monitoring ${#ID_ARRAY[@]} workflows. Ctrl+C to stop."
sleep 2

while true; do
  # Fetch all data, then render in one Python call
  TMPDIR=$(mktemp -d)
  for i in "${!ID_ARRAY[@]}"; do
    WID="${ID_ARRAY[$i]}"
    curl -s "$BASE/workflows/$WID" -H "Authorization: Bearer $TOKEN" > "$TMPDIR/wf_$i.json" 2>/dev/null &
    curl -s "$BASE/workflows/$WID/jobs" -H "Authorization: Bearer $TOKEN" > "$TMPDIR/jobs_$i.json" 2>/dev/null &
  done
  wait

  python3 - "$TMPDIR" "${#ID_ARRAY[@]}" <<'PYEOF'
import json, sys, os, datetime

tmpdir = sys.argv[1]
count = int(sys.argv[2])

print('\033[2J\033[H', end='')
print(f'EVOLUTION DASHBOARD — {datetime.datetime.now().strftime("%H:%M:%S")} — {count} workflows')
print(f'{"#":<3} {"STATUS":<12} {"ITER":<5} {"SHARPE":<9} {"RETURN":<9} {"DD":<8} {"CONS":<6}')
print('-' * 55)

for i in range(count):
    try:
        with open(f'{tmpdir}/wf_{i}.json') as f:
            wf = json.load(f)
        with open(f'{tmpdir}/jobs_{i}.json') as f:
            jobs = json.load(f)

        status = wf.get('status', '?')
        ctx = wf.get('context', {})
        r = ctx.get('backtest_results', '{}')
        try:
            results = json.loads(r) if isinstance(r, str) else r
        except:
            results = {}
        m = results.get('metrics', {}) if isinstance(results, dict) else {}

        trading = [j for j in jobs.get('jobs', []) if j.get('job_type') == 'trading']
        itr = len(trading)

        s = m.get('mean_sharpe_ratio', m.get('sharpe_ratio', 0)) or 0
        ret = (m.get('mean_total_return', m.get('total_return', 0)) or 0) * 100
        dd = (m.get('mean_max_drawdown', m.get('max_drawdown', 0)) or 0) * 100
        cons = (m.get('consistency', 0) or 0) * 100
        flag = ' ***' if isinstance(s, (int, float)) and s >= 0.8 else ''

        print(f'{i+1:<3} {status:<12} {itr:<5} {s:<9.3f} {ret:<8.1f}% {dd:<7.1f}% {cons:<5.0f}%{flag}')
    except Exception as e:
        print(f'{i+1:<3} {"error":<12} -     -         -        -       -     {str(e)[:30]}')

# Check winners
print()
import subprocess
try:
    wr = subprocess.run(['docker', 'compose', 'exec', '-T', 'worker', 'ls', '/workspaces/winning_strategies/'],
                       capture_output=True, text=True)
    files = [f for f in wr.stdout.strip().split('\n') if f.endswith('.json')]
    if files:
        print(f'*** {len(files)} WINNER(S) ***')
        for f in files:
            print(f'  {f}')
    else:
        print('No winners yet.')
except:
    print('No winners yet.')
PYEOF

  rm -rf "$TMPDIR"
  sleep 30
done
