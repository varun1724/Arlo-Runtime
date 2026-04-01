#!/usr/bin/env bash
# Copy best-per-workflow strategies from Docker volume to local files for resume.
set -euo pipefail

echo "Copying best strategies from Docker volume..."

# Copy from worker container
docker compose exec -T worker bash -c 'ls /workspaces/best_strategies/*.json 2>/dev/null' | while read f; do
  BASENAME=$(basename "$f")
  docker compose cp "worker:$f" "./$BASENAME"
  echo "  Saved $BASENAME"
done

# Also show what we got
echo ""
echo "Best strategies saved:"
for f in best_*.json; do
  [ -f "$f" ] || continue
  SHARPE=$(python3 -c "import json; print(f'{json.load(open(\"$f\")).get(\"sharpe\",0):.3f}')")
  echo "  $f — Sharpe: $SHARPE"
done
