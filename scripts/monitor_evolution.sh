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

# Dump best_strategies files from Docker volume to a temp location each refresh
BEST_DIR=$(mktemp -d)

while true; do
  # Fetch all data, then render in one Python call
  TMPDIR=$(mktemp -d)
  for i in "${!ID_ARRAY[@]}"; do
    WID="${ID_ARRAY[$i]}"
    curl -s "$BASE/workflows/$WID" -H "Authorization: Bearer $TOKEN" > "$TMPDIR/wf_$i.json" 2>/dev/null &
    curl -s "$BASE/workflows/$WID/jobs" -H "Authorization: Bearer $TOKEN" > "$TMPDIR/jobs_$i.json" 2>/dev/null &
  done
  # Also grab best_strategies from the Docker volume
  docker exec arlo-runtime-worker-1 bash -c 'for f in /workspaces/best_strategies/*.json; do [ -f "$f" ] && cat "$f"; echo "|||FILESEP|||"; done' > "$BEST_DIR/all_best.txt" 2>/dev/null &
  docker exec arlo-runtime-worker-1 ls /workspaces/winning_strategies/ > "$BEST_DIR/winners.txt" 2>/dev/null &
  wait

  python3 - "$TMPDIR" "${#ID_ARRAY[@]}" "$BEST_DIR" <<'PYEOF'
import json, sys, os, datetime

tmpdir = sys.argv[1]
count = int(sys.argv[2])
best_dir = sys.argv[3]

# Load best_strategies from Docker volume (most up-to-date, updated mid-optimization)
best_by_wf = {}
try:
    with open(f'{best_dir}/all_best.txt') as f:
        raw = f.read()
    for chunk in raw.split('|||FILESEP|||'):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            d = json.loads(chunk)
            wfid = d.get('workflow_id', '')
            best_by_wf[wfid[:8]] = d
        except:
            pass
except:
    pass

print('\033[2J\033[H', end='')
print(f'EVOLUTION DASHBOARD — {datetime.datetime.now().strftime("%H:%M:%S")} — {count} workflows')
print(f'{"#":<3} {"STEP":<10} {"CYCLE":<6} {"SHARPE":<9} {"RETURN":<10} {"DD":<9} {"CONS":<7} {"BTESTS":<7}')
print('-' * 65)

for i in range(count):
    try:
        with open(f'{tmpdir}/wf_{i}.json') as f:
            wf = json.load(f)
        with open(f'{tmpdir}/jobs_{i}.json') as f:
            jobs = json.load(f)

        status = wf.get('status', '?')
        step = wf.get('current_step_index', '?')
        wf_id = wf.get('id', '')
        ctx = wf.get('context', {})

        # 1. Try best_strategies file (updates live during optimization)
        m = {}
        best_sharpe_val = 0
        best_data = best_by_wf.get(wf_id[:8])
        if best_data:
            m = best_data.get('metrics', {})
            best_sharpe_val = best_data.get('sharpe', 0) or 0

        # 2. Fall back to context (optimizer_results or backtest_results)
        if not m or best_sharpe_val <= 0:
            for key in ('optimizer_results', 'backtest_results'):
                raw = ctx.get(key, '{}')
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                except:
                    parsed = {}
                if isinstance(parsed, dict):
                    candidate = parsed.get('best_result', parsed)
                    if isinstance(candidate, dict):
                        cm = candidate.get('metrics', {})
                        cs = cm.get('mean_sharpe_ratio', cm.get('sharpe_ratio', 0)) or 0
                        if cm and cs > best_sharpe_val:
                            m = cm
                            best_sharpe_val = cs

        # Count backtests from latest optimize job's progress
        total_backtests = 0
        opt_jobs = [j for j in jobs.get('jobs', []) if j.get('job_type') == 'optimize']
        for oj in opt_jobs:
            # Running optimize job shows iteration_count = current round
            rd = oj.get('result_data')
            if rd:
                try:
                    rd_parsed = json.loads(rd)
                    total_backtests += rd_parsed.get('total_backtests', 0)
                except:
                    pass

        # Count redesign cycles (number of times step 2 has run)
        redesign_jobs = [j for j in jobs.get('jobs', []) if j.get('job_type') == 'research' and j.get('step_index', -1) == 2]
        cycles = len(redesign_jobs) + 1  # +1 for initial generate

        step_names = {0: 'generate', 1: 'optimize', 2: 'redesign'}
        step_label = step_names.get(step, f's{step}')

        s = m.get('mean_sharpe_ratio', m.get('sharpe_ratio', 0)) or 0
        ret = (m.get('mean_total_return', m.get('total_return', 0)) or 0) * 100
        dd = (m.get('mean_max_drawdown', m.get('max_drawdown', 0)) or 0) * 100
        cons = (m.get('consistency', 0) or 0) * 100
        flag = ' ***' if isinstance(s, (int, float)) and s >= 0.8 else ''

        print(f'{i+1:<3} {step_label:<10} {cycles:<6} {s:<9.3f} {ret:>6.1f}%   {dd:>5.1f}%   {cons:>4.0f}%  {total_backtests:<7}{flag}')
    except Exception as e:
        print(f'{i+1:<3} {"error":<10} -      -         -         -       -      {str(e)[:30]}')

# Check winners
print()
try:
    with open(f'{best_dir}/winners.txt') as f:
        files = [l.strip() for l in f if l.strip().endswith('.json')]
    if files:
        print(f'*** {len(files)} WINNER(S) saved to /workspaces/winning_strategies/ ***')
        for fn in sorted(files)[-3:]:
            print(f'  {fn}')
        if len(files) > 3:
            print(f'  ... and {len(files)-3} more')
    else:
        print('No winners yet.')
except:
    print('No winners yet.')
PYEOF

  rm -rf "$TMPDIR"
  sleep 15
done
