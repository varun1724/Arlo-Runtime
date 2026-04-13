# CLAUDE.md

## Project
Arlo Runtime is the workflow orchestration engine for the Arlo ecosystem. It manages multi-step AI research pipelines (startup ideas, side hustles, freelance scanners), n8n workflow building/deployment, email notifications with PDF reports, and a job queue processed by a background worker.

## Tech Stack
- Python 3.11+, FastAPI, async SQLAlchemy + asyncpg, Pydantic v2, Alembic
- PostgreSQL database, Docker Compose (api + worker + db + n8n containers)
- Claude Code CLI as the AI subprocess (research + builder jobs)
- n8n v2.15.0 REST API for workflow deployment and webhook execution
- WeasyPrint for HTML-to-PDF report rendering
- aiosmtplib for async SMTP email delivery
- HMAC-signed URLs for stateless approval/artifact tokens

## Before Every Message
1. Read the memory index at `~/.claude/projects/-Users-varunscodingaccount-Desktop-Swift-projects-arlo-trading-engine/memory/MEMORY.md` for user context and prior decisions
2. Check the current plan file if one exists (listed in system reminders)
3. Review git status and recent commits to understand current state

## Working Rules
- After completing any non-trivial code change, use a sub-agent (Explore type) to verify the changes compile, make sense architecturally, and don't break existing patterns before presenting results to the user
- Run syntax checks (`python3 -c "import ast; ast.parse(open(f).read())"`) on every modified file before committing
- Run relevant tests locally when possible; if Docker is needed, provide the exact command for the user
- Prefer editing existing files over creating new ones
- Follow existing patterns in the codebase (dispatch dicts, schema validation, prompt engineering conventions)

## Key Architecture Patterns
- Pipeline templates live in `app/workflows/templates.py` with Pydantic schemas in `app/workflows/schemas.py`
- Six dispatch dicts must stay in sync across `app/api/workflow_routes.py` and `app/services/notifications.py` — the A5 consistency test enforces this
- Research jobs go through `_extract_json_payload` → `_sanitize_json_payload` → schema validation in `app/jobs/research.py`
- The n8n executor in `app/jobs/n8n.py` handles create/activate/execute phases with soft-fail on activation for the retry loop
- Builder jobs run Claude Code CLI in an isolated workspace directory
- `advance_workflow` in `app/services/workflow_service.py` handles step progression, retries, loops, and notification dispatch

## Deployment
Containers run on a Windows machine via Tailscale SSH (`ssh vsara@100.75.94`, project at `C:\trading\Arlo-Runtime`). Deploy cycle: commit → push → SSH pull → docker compose build + up → pytest.

## What to Avoid
- Adding features beyond what was asked
- Hardcoding step names or template IDs — use the dispatch dict pattern
- Breaking the startup pipeline when modifying shared code (contrarian, synthesis steps are shared)
- Committing without explicit user request
