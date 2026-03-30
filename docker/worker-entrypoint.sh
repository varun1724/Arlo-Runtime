#!/bin/bash
set -e

# Fix ownership of the workspaces volume (mounted as root by Docker)
chown -R arlo:arlo /workspaces 2>/dev/null || true

# Drop to non-root user and run the worker
exec gosu arlo python -m app.workers.main
