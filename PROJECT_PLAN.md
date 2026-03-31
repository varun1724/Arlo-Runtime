# Arlo Runtime — Project Plan

## 1. Purpose

Arlo Runtime is the backend execution layer for Arlo.

The iPhone app should become the **control surface**:

* voice input
* approvals and confirmations
* job launch
* job monitoring
* result viewing
* lightweight local-native actions where appropriate

Arlo Runtime should become the **work engine**:

* long-running jobs
* research workflows
* builder workflows
* provider/API orchestration
* workspace management
* iteration loops
* evaluation and stopping logic
* durable logs, progress, and outputs

The goal is to evolve Arlo from a strong local assistant into a **job-orchestrating personal operating system**.

---

## 2. Product Definition

### One-line definition

Arlo Runtime is the backend system that runs Arlo’s long-lived, tool-using, sandboxed jobs while the mobile app acts as the user-facing control layer.

### What Arlo Runtime must enable

Arlo should eventually be able to:

* run market research jobs over time
* generate startup ideas backed by evidence
* build and refine project scaffolds asynchronously
* manage long-running iterative workflows
* later support simulation/evaluation-heavy jobs like backtesting
* persist, inspect, and resume work across sessions and devices

### What Arlo Runtime is not

Arlo Runtime is not:

* a general autonomous agent platform
* an unrestricted shell on a remote machine
* a broad file browser
* a freeform tool-execution engine without policy
* an LLM-first control plane

It must stay:

* bounded
* policy-controlled
* observable
* deterministic in execution ownership

---

## 3. Core Architecture Principles

These are non-negotiable.

### 3.1 Deterministic systems own execution

The backend system must own:

* job lifecycle
* workspace selection
* file targeting
* iteration limits
* stop conditions
* policy enforcement
* tool access permissions
* persistence

The model may assist with:

* summarization
* content generation
* refinement
* research synthesis
* artifact drafting

**Exception — builder jobs:** Builder jobs use Claude Code as an autonomous coding agent within a sandboxed per-job workspace. In this case, Claude Code owns file selection and tool use *within the workspace boundary*. The workspace sandbox is the policy boundary. The runtime still owns:

* workspace creation and isolation
* job lifecycle (start, timeout, cancel)
* iteration limits
* what workspace Claude Code is pointed at
* artifact registration after completion

For all other job types, the model must never own:

* execution policy
* unrestricted tool use
* workspace/file selection
* stopping logic
* state mutation outside the designed system

### 3.2 Bounded execution

All work must be bounded by:

* job type
* allowed tools
* workspace scope
* max runtime
* max iterations
* optional budget/cost policies

### 3.3 Sandboxed builder/research workspaces

Job outputs should run in controlled workspaces. No job should be allowed to wander across arbitrary files.

### 3.4 Inspectability

Every job should be inspectable through:

* status
* current step
* logs/events
* generated artifacts
* result summary
* stop reason

### 3.5 Graceful degradation

Provider failure, tool failure, timeout, or policy denial should fail gracefully with durable state and clear user-facing explanations.

---

## 4. High-Level System Architecture

```text
Arlo iPhone App
    ↓ (Tailscale)
Arlo Runtime API (FastAPI + SSE)
    ↓
Job Store (Postgres)
    ↓
Worker (polls Postgres)
    ↓
Claude Code CLI (`claude -p`) — web search for research, autonomous coding for builder
    ↓
Workspace / Artifact Storage (local volume)
```

### 4.1 Arlo app responsibilities

The app should own:

* UI
* voice entry
* confirmations/approvals
* local-native actions that make sense on-device
* current session presentation
* job launch and job monitoring
* viewing outputs/results

### 4.2 Arlo Runtime API responsibilities

The API should own:

* authenticated job creation
* job querying
* recent/current job listing
* result retrieval
* cancellation requests later
* policy-aware acceptance/rejection of requested jobs

### 4.3 Job store responsibilities

The job store should own:

* durable job records
* job status
* timestamps
* current step
* result summaries
* stop reason
* failure state
* references to artifacts/workspaces

### 4.4 Worker responsibilities

Workers should own:

* claiming executable jobs
* running job-specific execution logic
* updating progress
* writing artifacts/results
* respecting limits/policies
* finalizing success/failure/stop state

### 4.5 Workspace responsibilities

Workspace management should own:

* job workspace creation
* path validation
* artifact registration
* cleanup/retention policy
* exportability

---

## 5. Initial Runtime Scope (v1)

The first version should stay intentionally narrow.

### Supported backend job types

#### 1. Research jobs

Research jobs use **Claude Code CLI** (`claude -p`) as the execution engine. The worker spawns Claude Code with a structured research prompt that instructs it to use web search, gather evidence, and output a structured opportunity report in a specified JSON schema. The worker parses the output and stores the result.

First target job: **"Research startup opportunities in a specific market/domain and produce a structured opportunity report."**

Examples:

* market research on a domain
* startup idea exploration
* trend synthesis
* gap/opportunity analysis

#### 2. Builder jobs

Builder jobs use **Claude Code** (via CLI non-interactive mode or SDK) as the execution engine. The worker spawns Claude Code inside a sandboxed per-job workspace. Claude Code autonomously handles file creation, editing, and bash execution within that workspace.

Examples:

* project scaffold generation
* artifact refinement
* project expansion from an existing workspace
* MVP builds from a prompt

### Explicitly out of scope for v1

Do not build yet:

* arbitrary shell execution
* autonomous internet browsing loops without tool policy
* days-long financial simulation jobs
* deployment automation
* full agent swarms
* broad multi-tenant SaaS concerns
* real-world action execution like calendar/reminders from the backend

Those can come later.

---

## 6. Runtime v1 Tech Stack Recommendation

### API

* Python
* FastAPI
* Pydantic

### Database

* Postgres

### Workers

* Python worker service
* simple polling against Postgres for queued jobs (no Redis needed for v1)

### LLM execution (all job types)

* **Claude Code CLI (`claude -p`)** for all job types — runs through Max plan, no separate API billing
* **Research jobs:** Claude Code with structured prompt requesting web search + JSON-schema output; worker parses result
* **Builder jobs:** Claude Code scoped to job workspace directory for autonomous file creation/editing
* Runs inside the worker container

### Storage

* local shared volume for workspaces/artifacts on the runtime machine initially

### Containerization

* Docker
* Docker Compose — must work identically on Mac (dev) and Windows (runtime host) from day one
* Platform-agnostic images and volume mounts

### Networking

* Tailscale for app-to-runtime connectivity
* Runtime API exposed on Tailscale network only — no public internet exposure
* iPhone app connects to runtime via Tailscale IP/hostname

### Host target

* Always-on Windows machine as Arlo Runtime host
* Mac remains primary dev machine for code + app work

---

## 7. Suggested Repository Structure

```text
arlo-runtime/
  app/
    api/
    workers/
    jobs/
    core/
    models/
    services/
    providers/
    tools/
    workspace/
    db/
  tests/
  scripts/
  docker/
  Dockerfile.api
  Dockerfile.worker
  docker-compose.yml
  .env.example
  README.md
```

### Suggested internal module meanings

* `api/` — request handlers, auth, response schemas
* `workers/` — worker entrypoints and polling/consumption logic
* `jobs/` — job-type-specific execution flows
* `core/` — configuration, shared constants, app wiring
* `models/` — typed domain models
* `services/` — orchestration and durable state services
* `providers/` — model-provider integrations
* `tools/` — external tool/data adapters
* `workspace/` — workspace creation, validation, artifact handling
* `db/` — persistence layer and DB models

---

## 8. Domain Models to Establish Early

### 8.1 Job domain

* `ArloJob`
* `JobType`
* `JobStatus`
* `JobStep`
* `JobStopReason`
* `JobIterationPolicy`
* `JobPermissionPolicy`

### 8.2 Research domain

* `ResearchJobRequest`
* `ResearchJobResult`
* `ResearchSource`
* `EvidenceItem`
* `OpportunityFinding`
* `ResearchAssumption`

### 8.3 Builder domain

* `BuilderJobRequest`
* `BuilderJobResult`
* `BuilderWorkspaceRef`
* `ArtifactRef`
* `BuilderTask`
* `BuilderTaskResult`

### 8.4 Provider domain

* `BuilderContentRequest`
* `BuilderContentResult`
* provider config and fallback policy

---

## 9. API Surface (Initial)

Start with a very small API.

### Core endpoints

#### `POST /jobs`

Create a new job.

Initial request types:

* research
* builder

#### `GET /jobs/{job_id}`

Get job status, progress, and result summary.

#### `GET /jobs`

List recent jobs.

#### `GET /jobs/{job_id}/stream` (SSE)

Server-Sent Events endpoint for real-time job progress updates. The app connects here after launching a job to receive live status changes, step transitions, and completion events without polling.

### Later endpoints

#### `POST /jobs/{job_id}/cancel`

Cancel a running job.

#### `GET /jobs/{job_id}/artifacts`

List artifacts for a job/workspace.

#### `GET /jobs/{job_id}/logs`

Return bounded job log events.

Keep v1 minimal.

---

## 10. Job Lifecycle Model

A job should move through a clear lifecycle.

### Base lifecycle

* queued
* running
* succeeded
* failed
* canceled
* stopped_by_policy

### Important timestamps

* created_at
* started_at
* updated_at
* completed_at

### Important progress data

* current_step
* progress_message
* iteration_count
* result_preview
* error_message
* stop_reason

This must be durable and queryable.

---

## 11. Worker Execution Model

### Runtime execution model (initial)

Start with a simple worker model.

Worker loop:

1. claim queued job
2. mark running
3. execute job-specific logic
4. update current step/progress over time
5. write results/artifacts
6. finalize state

### Why this model first

This is enough to support:

* async research
* async builder jobs
* progress display
* future iteration support

No need for distributed complexity yet.

---

## 12. Workspace / Sandbox Model

### 12.1 Initial workspace strategy

Use per-job or per-builder-job workspace directories under a controlled runtime root.

Example:

```text
/workspaces/
  job-123/
  job-124/
```

### 12.2 Rules

* all builder files must stay within controlled workspace root
* all artifact references must be validated
* no arbitrary path traversal
* no access to unrelated host files

### 12.3 Future evolution

Later, heavier jobs can move into per-job containers.

But do not require that for v1.

---

## 13. Security and Trust Boundaries

### 13.1 App vs runtime

The mobile app is a client/control surface.
The runtime is the execution layer.

### 13.2 Provider boundaries

Providers may help generate content.
Providers must never:

* select arbitrary files
* choose unrestricted tools
* mutate system state directly
* bypass policy

### 13.3 Tool permissions

Every job type should eventually run under an explicit permission policy.

Examples:

* research jobs may use web/data tools
* builder jobs may use builder providers and workspaces
* future simulation jobs may use market-data tools only

### 13.4 Authentication

Even for a personal prototype, protect the backend with at least:

* bearer token or similar
* environment-based secret config

---

## 14. Configuration and Secrets

Create a centralized config system.

### Needed now

* API auth token
* database URL
* workspace root
* runtime mode
* timeout settings
* retry settings
* Tailscale hostname/IP configuration

### Files

* `.env.example`
* typed settings/config module

Do not scatter config across the codebase.

---

## 15. Observability and Logging

Arlo Runtime should be observable from the start.

### Minimum logging

* job created
* worker claimed job
* step transitions
* provider/tool failure
* success/failure completion

### Job-level inspectability

Persist enough information to show in the app later:

* current step
* high-level log lines/events
* stop reason
* error summary

Keep this lightweight but durable.

---

## 16. Iteration / Loop Model (Later Phase)

This should not be overbuilt on day one, but the system should be ready for it.

### Needed concepts

* max_iterations
* target_threshold
* time_budget
* stop_reason
* per-iteration evaluation summary

This will be crucial for:

* iterative research refinement
* iterative builder refinement
* later strategy/backtest loops

---

## 17. Product Boundaries: What Stays on Phone vs Backend

### Keep local on phone

* reminders
* calendar
* notes
* local-native UI flows
* quick communication draft presentation/export
* confirmations

### Move to runtime

* research jobs
* builder jobs
* long-running generation/refinement
* provider-heavy tasks
* evidence/source gathering
* iterative job loops
* later simulation/backtesting workloads

This hybrid model is the intended Arlo architecture.

---

## 18. Delivery Phases — Actual Implementation Status

### Phase 1 — Runtime foundation [COMPLETE]

* FastAPI + Postgres + Worker polling loop
* Docker Compose stack (Mac + Windows compatible)
* Job model with full lifecycle (queued → running → succeeded/failed/canceled)
* Bearer token auth
* SSE streaming for real-time job progress

### Phase 2 — Research jobs [COMPLETE]

* Claude Code CLI (`claude -p`) with web search via `--dangerously-skip-permissions`
* Structured JSON research reports with source citations
* Sonnet model for research (cost-efficient)

### Phase 3 — Builder jobs [COMPLETE]

* Claude Code autonomous coding in sandboxed per-job workspaces
* Non-root user in worker container (required for `--dangerously-skip-permissions`)
* `arlo_manifest.json` for structured build output
* Opus model for code generation

### Phase 4 — Workflow orchestration [COMPLETE]

* Multi-step workflows with context passing between steps
* Conditional step execution, loop-back support (up to N iterations)
* Human approval gates (`requires_approval` on steps)
* `advance_workflow()` orchestration after each job completes
* Workflow templates: startup idea pipeline, side hustle automation, freelance scanner, strategy evolution

### Phase 5 — Deep multi-pass research [COMPLETE]

* 6-step startup pipeline: landscape scan → deep dive → contrarian analysis → synthesis → approve → build MVP
* Per-job-type model selection (sonnet for research, opus for builder)
* Research prompts require web search, source citations, cross-referencing

### Phase 6 — n8n integration [COMPLETE]

* n8n service in Docker Compose (shared Postgres)
* N8nClient async wrapper for n8n REST API
* "n8n" job type for deploying/executing workflows
* Side hustle automation pipeline (8 steps: research → build n8n workflow → deploy)

### Phase 7 — Polish & reliability [COMPLETE]

* Job/workflow cancellation (`POST /jobs/{id}/cancel`, `POST /workflows/{id}/cancel`)
* Job event log (`job_events` table, `GET /jobs/{id}/logs`)
* Workspace cleanup (72h retention, periodic cleanup, pinning)
* Workflow step retry (auto-retry with `max_retries`, manual `POST /workflows/{id}/retry`)
* Graceful worker shutdown (SIGTERM/SIGINT handling)

### Phase 8 — Freelance scanner pipeline [COMPLETE]

* 7-step pipeline: research niches → evaluate → contrarian → rank → approve → build n8n scanner → deploy

### Trading Engine Integration [COMPLETE]

* Separate project: `arlo-trading-engine/`
* FastAPI + TimescaleDB + Redis + Celery
* Core backtester with position sizing, slippage, risk limits
* Walk-forward analysis (anti-overfitting)
* Parameter sensitivity analysis
* FRED macro data + NewsAPI sentiment integration
* MacroAccessor/SentimentAccessor available to strategies
* Strategy evolution pipeline: research → generate → backtest → evaluate/evolve (loop 50x) → approve
* 50-test suite (all passing)

---

## 19. Current Architecture

```
Arlo iPhone App (future)
    ↓ (Tailscale)
Arlo Runtime API (FastAPI, port 8000)
    ↓
Postgres (jobs, workflows, events)
    ↓
Worker (polls jobs, executes via Claude Code CLI)
    ↓
Claude Code (Sonnet for research, Opus for building)
    ↓
n8n (workflow automation, port 5678)

Trading Engine API (FastAPI, port 8001)
    ↓
TimescaleDB (market data, strategies, backtests)
    ↓
Celery Workers (backtests, data ingestion)
```

### Job Types

| Type | Executor | Model | Description |
|------|----------|-------|-------------|
| research | Claude Code CLI | Sonnet | Web search + structured reports |
| builder | Claude Code CLI | Opus | Autonomous coding in sandboxed workspace |
| n8n | n8n REST API | — | Deploy/execute n8n workflows |
| trading | Trading Engine API | — | Submit strategies, run backtests |

### Workflow Templates

| Template | Steps | Description |
|----------|-------|-------------|
| `startup_idea_pipeline` | 6 | Deep research → contrarian → synthesis → approve → build MVP |
| `side_hustle_pipeline` | 8 | Research → evaluate → build n8n workflow → deploy |
| `freelance_scanner` | 7 | Research niches → rank → build scanner → deploy to n8n |
| `strategy_evolution` | 5 | Research → generate → backtest/evolve (loop) → approve |

---

## 20. Remaining Work

### Near-term

* Deploy to always-on Windows machine + Tailscale
* Connect Arlo iPhone app to runtime API
* Alpaca paper trading integration for winning strategies
* Add more FRED/sentiment data sources
* Competitive intelligence monitor pipeline

### Long-term

* SEO content pipeline
* Strategy ensemble/voting (multiple strategies running simultaneously)
* Real-money trading (after paper trading proves out)
* Full agent swarm capability
