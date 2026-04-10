#!/usr/bin/env bash
# Run the arlo-runtime test suite inside the api container.
#
# Usage:
#   ./scripts/run_tests.sh                # full suite
#   ./scripts/run_tests.sh tests/test_workflow_retry.py  # one file
#   ./scripts/run_tests.sh -k schema      # filter by name
#
# Local-only quick tests (no DB) can also be run directly with:
#   python3 -m pytest tests/test_startup_schemas.py \
#                     tests/test_prompt_schema_alignment.py \
#                     tests/test_research_validation.py \
#                     tests/test_workflow_context_pruning.py \
#                     -v --noconftest

set -euo pipefail

cd "$(dirname "$0")/.."

docker compose exec -T api pytest tests/ -v --tb=short "$@"
