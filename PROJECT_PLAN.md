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

## 18. Delivery Phases

## Phase 1 — Runtime foundation

Goal: create the backend spine.

Deliverables:

* FastAPI service
* Postgres (worker polls Postgres directly — no Redis)
* worker service
* Docker Compose stack (works identically on Mac and Windows)
* job model + persistence
* basic auth token
* Tailscale networking setup

## Phase 2 — First real async domain: research

Goal: prove the job flow end-to-end with the first target job — "research startup opportunities in a market/domain."

Deliverables:

* research job request/result models
* create job via API
* worker executes research job using Claude Code CLI (`claude -p`) with web search
* SSE endpoint for real-time progress streaming
* structured opportunity report as output
* status + result retrieval

## Phase 3 — Async builder jobs

Goal: move builder into true backend execution using Claude Code.

Deliverables:

* builder job request/result models
* Claude Code integration (CLI non-interactive mode or SDK) in worker
* workspace-backed builder execution — worker spawns Claude Code scoped to job workspace
* artifact metadata/results persisted
* Claude Code auth setup in container environment

## Phase 4 — Iteration + policies

Goal: support bounded loops safely.

Deliverables:

* iteration policy
* stop reasons
* permission policy model
* stronger logging and evaluation framework beginnings

## Phase 5 — Runtime/app integration

Goal: connect the app to the runtime cleanly over Tailscale.

Deliverables:

* app launches remote jobs via Tailscale-accessible API
* app subscribes to SSE stream for live progress updates
* app shows progress/results
* app-side duplicate execution paths start getting simplified

---

## 19. First Milestone Definition

### Milestone 1

**Arlo can create and complete a startup opportunity research job remotely.**

Success criteria:

* app or curl can create a research job (e.g., "research startup opportunities in the pet tech market")
* job is persisted in backend DB
* worker claims and runs it using Claude Code CLI with web search
* job progress streams in real-time via SSE
* final structured opportunity report is stored
* API returns job state/result cleanly
* works via Tailscale from iPhone to Windows runtime

This is the first serious proof that Arlo Runtime is real.

### Milestone 2

**Arlo can create and complete a builder job remotely.**

Success criteria:

* builder job creates or updates a backend workspace
* artifacts are written and tracked
* result is retrievable through job status/result endpoints

---

## 20. Risks and Mitigations

### Risk: overbuilding infrastructure too early

Mitigation:

* use FastAPI + Postgres + one worker first (no Redis)
* no Kubernetes or broad distributed complexity

### Risk: app/runtime boundaries become muddy

Mitigation:

* keep app as control surface
* keep runtime as execution layer

### Risk: provider sprawl / unsafe tool use

Mitigation:

* add explicit permission policy model early
* deterministic routing owns tool selection

### Risk: builder sandbox drifts into arbitrary file execution

Mitigation:

* controlled workspace root — Claude Code is always launched with cwd set to the job workspace
* strict path validation
* Claude Code runs within the workspace boundary; the workspace *is* the sandbox
* worker enforces timeout and iteration limits externally

### Risk: Claude Code rate limits throttle concurrent builder jobs

Mitigation:

* queue builder jobs and run them sequentially (one at a time) in v1
* monitor Max plan rate limits and adjust concurrency later

### Risk: jobs become opaque

Mitigation:

* durable status, current step, and logs from the start

---

## 21. Definition of Success for Arlo Runtime v1

Arlo Runtime v1 is successful if:

* the backend can accept and persist jobs
* a worker can execute jobs independently of the mobile app
* job progress and results are durable and inspectable
* research jobs work end-to-end
* builder jobs work end-to-end in a controlled workspace
* the app can later integrate as a clean control surface
* the system remains bounded, deterministic, and understandable

---

## 22. Immediate Next Steps

1. Create the basic runtime repo structure
2. Add FastAPI app skeleton
3. Add Postgres service in Docker Compose (platform-agnostic, works on Mac + Windows)
4. Add config/settings module and `.env.example`
5. Add core job model and DB schema
6. Add worker service skeleton (polls Postgres directly)
7. Implement `POST /jobs`, `GET /jobs`, `GET /jobs/{id}`, `GET /jobs/{id}/stream` (SSE)
8. Implement first end-to-end research job: "startup opportunity research" using Claude Code CLI
9. Run the stack on Mac via Docker Compose
10. Run the identical stack on the Windows machine via Docker Compose
11. Set up Tailscale so the iPhone app can reach the runtime

---

## 23. Final Note

Arlo Runtime should be treated as the beginning of the real execution platform, not a side helper service.

The phone app is evolving into:

* interface
* approval layer
* result viewer
* local-native assistant surface

The runtime is evolving into:

* execution engine
* job system
* builder/research platform
* future long-running intelligence layer

That is the correct architecture for the Arlo product vision.
