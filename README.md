# Arlo Runtime

Backend execution engine for Arlo — runs research, builder, trading, and optimization jobs via Claude Code CLI and trading engine API. Supports multi-step workflows with loops, approval gates, and autonomous strategy evolution.

## Quick Start

```bash
cp .env.example .env
# Add CLAUDE_CODE_OAUTH_TOKEN (from: claude setup-token)

# Start the stack with 6 workers
docker compose up --build -d --scale worker=6

# Verify
curl http://localhost:8000/health
```

## Architecture

- **API**: FastAPI on port 8000
- **Database**: PostgreSQL 16
- **Workers**: 6 polling workers (claim jobs, execute, advance workflows)
- **Job types**: research (Claude Sonnet), builder (Claude Opus), trading (HTTP API), optimize (local parameter search), n8n
- **External**: Arlo Trading Engine (backtesting), n8n (automation)

## Workflows

Multi-step pipelines with conditional branching, loops, and approval gates.

### Available Templates

```
startup_idea_pipeline     — Deep research → analysis → synthesis → build MVP
side_hustle_pipeline      — Research side hustles → evaluate → plan
freelance_scanner         — Scan freelance opportunities → filter → apply
strategy_evolution        — Generate → Optimize params → Claude redesign → loop
```

### Strategy Evolution (Token-Efficient)

The evolution pipeline uses a local parameter optimizer to minimize Claude API usage:

```
Step 0: generate_strategy     — Claude generates initial strategy (1 call)
Step 1: local_optimize        — Tests 100+ parameter combinations via trading engine (FREE)
Step 2: evaluate_and_redesign — Claude redesigns architecture when optimizer plateaus (1 call)
                              → Loops back to Step 1
```

**~90% reduction in Claude usage** vs calling Claude every iteration.

```bash
# Launch 6 parallel evolution workflows
./scripts/run_parallel_evolution.sh

# Resume from saved best strategies
./scripts/resume_evolution.sh

# Monitor progress
./scripts/monitor_evolution.sh
```

Winning strategies auto-save to `/workspaces/winning_strategies/` when they pass:
- Sharpe > 0.8, Return > 10%, Max DD < 20%, Consistency > 75%, 30+ trades, no fold < -15%

## API Endpoints

```
# Jobs
POST /jobs                          Create standalone job
GET  /jobs                          List jobs
GET  /jobs/{id}                     Get job status + results
POST /jobs/{id}/cancel              Cancel job
GET  /jobs/{id}/stream              SSE progress stream

# Workflows
GET  /workflows/templates           List available templates
POST /workflows/from-template/{id}  Create workflow from template
GET  /workflows                     List workflows
GET  /workflows/{id}                Get workflow status + context
POST /workflows/{id}/cancel         Cancel workflow
POST /workflows/{id}/approve        Approve pending step
```

## Key Files

```
app/
  api/                  FastAPI routes (jobs, workflows)
  jobs/                 Job executors
    research.py         Claude CLI for research
    builder.py          Claude CLI for code generation
    trading.py          Trading engine HTTP client
    local_optimizer.py  Parameter optimization (no Claude)
  workers/              Polling worker + job dispatcher
  workflows/            Pipeline templates
  services/             Job + workflow orchestration
scripts/
  run_parallel_evolution.sh   Launch 6 evolution workflows
  resume_evolution.sh         Resume from saved state
  monitor_evolution.sh        Live dashboard
  save_best.sh                Copy best strategies from Docker volume
workspaces/
  strategy_guide.md           Static reference for Claude (API docs, strategies)
  cached_research.json        Pre-computed research (skips expensive web search)
```

## Development

```bash
# Run tests
docker compose exec api python3 -m pytest tests/ -v

# Check evolution status
docker compose logs worker --tail=20

# Save best strategies locally
./scripts/save_best.sh
```
