#!/bin/bash
set -e

# Fix ownership of the workspaces volume (mounted as root by Docker)
chown -R arlo:arlo /workspaces 2>/dev/null || true

# Seed the cross-run facts cache on first start. Only copies the
# template if the cache file doesn't already exist — we never overwrite
# user edits. Safe to run on every worker container start.
FACTS_TEMPLATE="/opt/arlo/cross_run_facts.template.json"
FACTS_CACHE="/workspaces/cross_run_facts.json"
if [ -f "$FACTS_TEMPLATE" ] && [ ! -f "$FACTS_CACHE" ]; then
    cp "$FACTS_TEMPLATE" "$FACTS_CACHE"
    chown arlo:arlo "$FACTS_CACHE" 2>/dev/null || true
    echo "Seeded cross-run facts cache from template: $FACTS_CACHE"
fi

# Drop to non-root user and run the worker
exec gosu arlo python -m app.workers.main
