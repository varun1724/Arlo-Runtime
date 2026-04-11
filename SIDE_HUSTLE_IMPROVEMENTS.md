# Side Hustle Pipeline — Improvement Tracker

## Context

The `side_hustle_pipeline` template (`app/workflows/templates.py:532`) is an 8-step automation pipeline modeled loosely after the startup pipeline. Goal: research automatable side hustles → evaluate → contrarian → rank → user approves → generate an n8n workflow JSON → deploy to the running n8n instance → execute a test run.

It was last touched before any of the startup pipeline's Rounds 1-5 happened, so it has **none** of the discipline those rounds added: no output schemas, no auto-retry, no context pruning, no artifact enforcement for the n8n-specific output, no live progress, no async notifications, no calibrated prompts. The CLI script (`scripts/run_side_hustle_pipeline.sh`) is the same interactive-blocking style the startup script had before Round 5.

The headline problem is bigger than that, though: **the n8n REST API integration is broken at the HTTP layer.** It calls endpoints that no longer exist in current n8n versions. So even if every other step ran perfectly, the deploy step would 404 and the test step would fail to trigger anything.

This document tracks the fixes needed, organized into the same disciplined rounds the startup pipeline used.

---

## Inventory of files involved

| File | Role |
|------|------|
| `app/workflows/templates.py` (lines 532-796) | `SIDE_HUSTLE_PIPELINE` template with 8 step definitions |
| `app/workflows/templates.py` (lines 798-1000+) | `FREELANCE_SCANNER_PIPELINE` — sibling template, same problems |
| `app/jobs/n8n.py` | Job executor for `job_type=n8n` (deploy + test_run steps) |
| `app/tools/n8n.py` | `N8nClient` async HTTP wrapper for n8n REST API |
| `app/jobs/builder.py` | Generic builder used by `build_n8n_workflow` step |
| `app/workflows/schemas.py` | Pydantic schemas — **side hustle has none here** |
| `app/core/config.py` | n8n connection settings (`n8n_base_url`, `n8n_api_key`, timeouts) |
| `docker-compose.yml` (lines 46-62) | n8n service definition (image, env, volume) |
| `docker/init-n8n-db.sql` | Initializes a separate `n8n` postgres database |
| `scripts/run_side_hustle_pipeline.sh` | Interactive CLI client (polls + blocks on stdin) |
| `app/workers/executor.py` | Routes `job_type=n8n` to `execute_n8n_job` |

No tests exist for `app/jobs/n8n.py`, `app/tools/n8n.py`, or any of the side hustle prompts. The only side-hustle-related test is `tests/test_workflows.py::test_list_templates` which just asserts the template ID exists in the registry.

---

## Critical bugs (must fix before any meaningful run)

### Bug 1: n8n REST API endpoints are wrong
**File:** `app/tools/n8n.py`

Three concrete issues, all fatal for current n8n versions (v1.0+):

**A. Activation endpoint changed.**
```python
# CURRENT (broken on n8n v0.218+):
PATCH /api/v1/workflows/{id}  body={"active": true}

# CORRECT:
POST /api/v1/workflows/{id}/activate
POST /api/v1/workflows/{id}/deactivate
```

**B. Manual execution endpoint doesn't exist in the public API.**
```python
# CURRENT:
POST /api/v1/workflows/{id}/run

# REALITY:
# n8n's public REST API has no general-purpose "execute this workflow"
# endpoint. To trigger a workflow externally you need EITHER:
#   (a) A Webhook trigger node baked into the workflow JSON, then call
#       POST {n8n_base_url}/webhook/{webhook_path} directly
#   (b) The internal /rest/workflows/{id}/run endpoint, which uses cookie
#       auth from the UI session — NOT compatible with the X-N8N-API-KEY
#       header path the client uses
# Option (a) is the only sane path for external automation.
```

**C. Execution polling endpoint exists but its response shape doesn't match what `poll_execution` expects.**
```python
# Current code expects:
execution.get("status") in ("success", "error", "crashed")

# n8n actually returns:
{
  "id": "...",
  "finished": true|false,
  "mode": "manual|trigger|webhook",
  "data": {...},
  "status": "success|failed|waiting|running"  # status field name varies by version
}
```
Needs version-aware parsing or a stable normalization layer.

**Fix scope:** This is a Round 4-equivalent rewrite of `app/tools/n8n.py`. The whole "execute" path needs to be replaced with "ensure the workflow has a webhook trigger, hit the webhook URL, optionally poll the execution row by webhook execution ID."

### Bug 2: Builder doesn't enforce `workflow.json`
**File:** `app/jobs/builder.py:32`

```python
REQUIRED_BUILDER_ARTIFACTS = ("README.md", "BUILD_DECISIONS.md")
```

This list was set for the startup pipeline. The side hustle pipeline ALSO uses the generic builder, but it needs `workflow.json` to exist on disk (the n8n deploy step depends on it). If Claude forgets to create it, the failure surfaces 1 step later in `_extract_workflow_json_from_build` with a cryptic "no workflow JSON" message instead of being caught at build time with a clean retry.

**Fix:** the builder needs per-pipeline required-artifact lists, not a single hardcoded tuple. Or — simpler — the side hustle build prompt explicitly names workflow.json as a required artifact and the builder reads the list from the StepDefinition.

### Bug 3: Deploy/test prompts embed huge JSON via string interpolation
**File:** `app/workflows/templates.py:774-790`

```python
"prompt_template": (
    '{{"action": "create", "activate": true, "workflow_json_from_build": true, '
    '"build_result": {build_result}}}'
)
```

`{build_result}` here is the entire builder job's serialized result_data — potentially many KB of JSON with embedded quotes and braces. The template renderer uses string `.format()`, which doesn't escape JSON, so any quote, backslash, or special character in the build result corrupts the resulting prompt JSON. The prompt then fails to parse in `execute_n8n_job` with "n8n job prompt is not valid JSON."

**Fix:** instead of inlining the result data, the n8n step should pull it from the previous job's `result_data` column directly via the workflow context (the way `context_inputs=["selected_idea"]` works for build_mvp). The prompt template becomes a small static JSON like `{"action":"create","activate":true,"from_previous_step":"build_n8n_workflow"}` and the executor reads the previous step's result.

### Bug 4: No JSON validation of generated n8n workflows
**File:** `app/jobs/n8n.py:198-217`

`_extract_workflow_json_from_build` does `json.loads(wf)` and returns the parsed object, but never checks that it actually looks like an n8n workflow (has `nodes`, `connections`, at least one trigger). A malformed-but-parseable JSON gets POSTed to n8n, which then returns a generic 400 with no useful diagnostics.

**Fix:** validate the workflow JSON structure before sending it to n8n. Check at minimum: `nodes` is a non-empty list, `connections` exists, exactly one trigger node, no nodes referencing missing credentials.

### Bug 5: 30-second HTTP timeout is too short
**File:** `app/tools/n8n.py:50`

```python
async with httpx.AsyncClient(timeout=30) as client:
```

Hardcoded 30s for ALL requests. Creating a workflow with 20+ nodes can hit this; activating a workflow triggers credential validation which can be slow. Should be configurable and more generous (60-120s) for state-changing requests, while staying short (5s) for status polls.

### Bug 6: Side hustle template has no error recovery
The startup pipeline has `max_retries: 2-3` on every research step plus `max_loop_count` on contrarian. The side hustle pipeline has neither. A single transient failure (API rate limit, malformed JSON response, n8n timeout) kills the entire workflow with no retry.

---

## Round-by-round improvement plan

The structure mirrors the startup pipeline's Rounds 1-5 because the discipline carried over works.

### Round 1 — Prompt quality pass

**Goal:** raise the four research prompts to the same quality bar as the startup pipeline's Round 1.

**Step 0 — `research_side_hustles`** (`templates.py:543`)
Current state: shallow. Mentions "use web search" but no taxonomy, no contrarian source list, no non-obviousness check.

Changes:
- Add a **TIMING SIGNAL TAXONOMY** identical to the startup pipeline (REGULATORY_SHIFT, TECHNOLOGY_UNLOCK, BEHAVIORAL_CHANGE, COST_COLLAPSE, DISTRIBUTION_UNLOCK, INCUMBENT_FAILURE). Side hustles also have timing — the "API just opened up" / "platform just deprecated their first-party tool" / "new EU regulation creates a compliance niche" shifts matter here too.
- Add a **CONTRARIAN SOURCING list** (Reddit niche subs, indie hacker forums, IndieHackers.com revenue reports, Twitter screenshot threads, YouTube shorts of "how I make $X/mo automated"). Bias against gurus and toward verifiable revenue claims.
- Add a **non_obviousness_check** field (yes/no) — at least 5 of the 10-12 opportunities must be non-obvious.
- Required: every income range claim must cite a verifiable source (revenue dashboard, public Stripe payouts, Reddit "I made $X" thread). No "experts say" or "people report" without a name.
- Add `automation_realness_check`: explicit "is this actually automatable, or does it secretly require manual judgment for every transaction?" — many side hustle gurus call things "automated" that have a human in every loop.

**Step 1 — `evaluate_feasibility`** (`templates.py:591`)
Current state: 6 dimensions, no score anchors, no calibration.

Changes:
- Add **score anchors** for each dimension (1/5/8/10 with explicit definitions) so scores are comparable across runs. This is how the startup pipeline does it. Without anchors, Claude's 7 vs 8 means nothing.
- Replace `automation_feasibility` with `n8n_specific_feasibility`: does n8n have nodes for every step? Are the nodes free or paid? Are credentials available?
- Replace generic `legal_safety` with explicit checklist: TOS violations (which platform's TOS? cite the section), CFAA / data scraping legality, FTC affiliate disclosure rules, CAN-SPAM if email is involved, GDPR if data crosses to EU, state-level wage/tax thresholds.
- New required field: **`n8n_node_inventory`** — for each opportunity, list the specific n8n nodes needed (HTTP Request, Schedule Trigger, Code, etc.) and flag any that don't exist or require paid versions.

**Step 2 — `contrarian_analysis`** (`templates.py:637`)
Current state: vague. "Search Reddit for failures" with no enforcement.

Changes:
- Required: at least one **NAMED predecessor** that died in this exact niche (company name + year + specific reason). Same rule as the startup contrarian step.
- **Platform crackdown evidence:** required to cite at least one specific recent enforcement action (banned account, API change, TOS update) for any opportunity that depends on a specific platform.
- **Income reality check** must cite at least one screenshot or revenue dashboard, not just a Reddit comment. If only Reddit comments are available, mark `evidence_strength: weak`.
- Add **`kill_probability`** (low/medium/high) like the startup pipeline.
- Required: every "saturation" claim cites a specific search result count (e.g., "47 YouTube videos in last 6 months teaching this exact hustle"), not just "there are a lot."

**Step 3 — `synthesis_and_ranking`** (`templates.py:679`)
Current state: ranks by total score, no anchors, no head-to-head, MVP spec is too vague.

Changes:
- Use **weighted scoring** like the startup pipeline:
  - `total_score = (revenue_potential * 1.5) + (time_to_first_dollar * 1.5) + (automation_feasibility * 1.0) + (legal_safety * 1.0) + (maintenance_effort * 1.0) + (scalability * 0.5)`
- Add **head_to_head** field per ranked entry explaining why this beats the next-ranked opportunity.
- Tighten the **n8n_workflow_spec** required fields:
  - `trigger_node`: specific n8n node type and config (e.g., "Schedule Trigger every 6 hours" or "Webhook trigger at /side-hustle-X")
  - `node_graph`: ordered list of node types with brief descriptions
  - `external_credentials`: list of every API key / OAuth credential the user must configure in n8n before activation
  - `expected_runtime`: realistic per-execution duration
  - `frequency`: how often it runs
  - `out_of_scope`: 3 features explicitly NOT in the v1 (prevents Claude from over-engineering the workflow JSON)
  - `success_metric`: how to know post-deploy if the workflow is working
  - `risky_assumption`: the one belief that, if wrong, kills the side hustle

**Step 5 — `build_n8n_workflow`** (`templates.py:736`)
Current state: vague "create workflow.json", no validation requirements.

Changes:
- Strict file requirements: `workflow.json`, `README.md`, `BUILD_DECISIONS.md`, `arlo_manifest.json`. Builder rejects the build if any are missing.
- **Embed an n8n workflow JSON skeleton** in the prompt so Claude has a known-good starting point with the right keys (`name`, `nodes`, `connections`, `settings`, `staticData`, `tags`, `pinData`, `meta`).
- Required: the workflow MUST have a webhook trigger (not Schedule Trigger) so the deploy step can trigger it externally for the test run. Document why (until n8n exposes a manual-trigger REST endpoint, webhooks are the only externally-triggerable path).
- Required: `BUILD_DECISIONS.md` must echo `out_of_scope` from the synthesis spec, document credentials needed, and explain how to test the `risky_assumption`.
- Required: a `test_payload.json` file containing the JSON payload to send to the webhook for the test run, so the test step has known-good input.

**Verification:**
- New `tests/test_side_hustle_prompts.py` that asserts every prompt contains its required structural markers (timing signal taxonomy in step 0, score anchors in step 1, named predecessor requirement in step 2, head_to_head in step 3, webhook trigger requirement in step 5).

### Round 2 — Schema validation, structural fixes, test framework

Mirrors the startup pipeline's Round 2.

**New schemas in `app/workflows/schemas.py`:**
```python
class SideHustleResearchResult(BaseModel):
    opportunities: list[SideHustleOpportunity] = Field(min_length=8)
    sources_consulted: list[str] = Field(min_length=3)
    model_config = ConfigDict(extra="allow")

class SideHustleFeasibilityResult(BaseModel):
    evaluations: list[SideHustleEvaluation] = Field(min_length=5)
    ...

class SideHustleContrarianResult(BaseModel):
    analyses: list[SideHustleContrarianAnalysis] = Field(min_length=5)
    ...

class SideHustleSynthesisResult(BaseModel):
    final_rankings: list[SideHustleRanking] = Field(min_length=2, max_length=7)
    executive_summary: str = Field(min_length=100)
    ...
```

Versioned names: `side_hustle_research_v1`, `side_hustle_feasibility_v1`, `side_hustle_contrarian_v1`, `side_hustle_synthesis_v1`. Register in `STEP_OUTPUT_SCHEMAS`.

**Wire them up in the template:**
| Step | output_schema | max_retries | timeout | context_inputs |
|------|---|---|---|---|
| research_side_hustles | side_hustle_research_v1 | 2 | 1800s | — |
| evaluate_feasibility | side_hustle_feasibility_v1 | 2 | 1800s | `["side_hustle_research"]` |
| contrarian_analysis | side_hustle_contrarian_v1 | 2 | 1800s | `["feasibility"]` |
| synthesis_and_ranking | side_hustle_synthesis_v1 | 2 | 1800s | `["side_hustle_research", "feasibility", "contrarian"]` |
| build_n8n_workflow | — | 1 | 1800s | `["selected_hustle"]` |
| deploy_to_n8n | — | 2 | 600s | `["build_result"]` |
| test_run | — | 1 | 600s | `["deploy_result"]` |

The `context_inputs` whitelist is critical — without it, the entire growing workflow context bleeds into every prompt (Round 2's headline fix on the startup side).

**Approval gate fix:** the `selected_hustle` context override on approval should mirror how `selected_idea` works in the startup pipeline. The build step reads only `selected_hustle`, not the entire synthesis blob.

**Deploy/test prompt rewrite:** stop embedding `{build_result}` and `{deploy_result}` via string interpolation. The n8n executor should read previous step results via `context_inputs` lookup against the workflow row, not via prompt embedding.

**New tests:**
- `tests/test_side_hustle_schemas.py` — round-trip validation, min-length enforcement, extra-field tolerance
- `tests/test_side_hustle_prompt_alignment.py` — every prompt's `{placeholders}` are subset of the prior step's output keys
- `tests/test_side_hustle_template_integrity.py` — every step has a schema (except builder + n8n), every step has appropriate retries

### Round 3 — Approval UX, build enforcement, n8n contract

Mirrors the startup pipeline's Round 3.

**Approval gate UX:**
- The CLI script should display the same kind of formatted ranking summary as the startup script's Round 3. Cost so far, top 3 hustles with one-liners, scores, n8n_workflow_spec preview, expected income.
- Approval can also happen via the email link (Round 5 of the startup pipeline already provides this — the side hustle template just needs to wire `selected_hustle` into `approve-link/{token}` the same way `selected_idea` is wired).

**Builder enforcement:**
- Add `required_artifacts` to `StepDefinition`. The builder reads it from the step instead of using a hardcoded constant. Side hustle build_n8n_workflow sets `required_artifacts=["workflow.json", "README.md", "BUILD_DECISIONS.md", "test_payload.json"]`.
- Add a `validate_n8n_workflow_json` helper that checks structure (nodes list non-empty, connections object, exactly one trigger node, all referenced credentials documented in BUILD_DECISIONS.md). If validation fails, raise `ClaudeRunError` so the auto-retry path kicks in.

**N8n integration contract:**
- Document explicitly in `app/jobs/n8n.py` that the side hustle pipeline only supports webhook-triggered workflows for the test run.
- The deploy step's job result includes the webhook URL (computed as `{n8n_base_url}/webhook/{webhook_path}` where `webhook_path` comes from the workflow's webhook node).
- The test step posts the contents of `test_payload.json` to that URL and reads the response.

**Cost/usage tracking:** already plumbed through Round 3 — the side hustle template inherits this for free once the steps have proper schemas.

**Test additions:**
- `tests/test_side_hustle_approval.py` — the approval gate correctly passes `selected_hustle` (not the entire synthesis) into the build step
- `tests/test_n8n_workflow_validator.py` — `validate_n8n_workflow_json` accepts good workflows, rejects ones missing nodes/connections/triggers
- `tests/test_side_hustle_builder_artifacts.py` — missing workflow.json or test_payload.json triggers `ClaudeRunError`

### Round 4 — n8n REST API rewrite + bug hardening

This is the round that actually fixes the broken n8n integration. Mirrors the startup pipeline's Round 4 in spirit (bug hardening + live progress).

**Rewrite `app/tools/n8n.py`:**
- New `activate_workflow` and `deactivate_workflow` use `POST /api/v1/workflows/{id}/activate` and `.../deactivate`.
- Remove `execute_workflow` entirely. Replace with `trigger_webhook(webhook_url, payload)` that does an HTTP POST to the workflow's webhook URL.
- Replace `poll_execution` with version-aware status normalization. Detect n8n version on first call (`GET /api/v1/info` or similar) and route through the right shape.
- Add per-method timeouts: 60s for state changes, 5s for polls, 30s for webhook triggers.
- Add retry-with-backoff for transient 5xx and connection errors.

**Rewrite `app/jobs/n8n.py`:**
- The deploy step extracts the webhook URL from the workflow JSON's webhook node (look for nodes with `type: "n8n-nodes-base.webhook"` and read the `webhookId` + path).
- The test step reads `test_payload.json` from the builder workspace and POSTs it to the webhook URL.
- Result data includes the webhook URL prominently so the user can hit it from anywhere later.

**Live progress for n8n jobs:**
- The current n8n job updates progress at coarse boundaries ("creating", "activating", "executing"). Add a polling-progress callback that updates the JobRow's `progress_message` every 5s with "Waiting for execution (15s elapsed, status: running)" so users get feedback during long workflow runs.

**New tests:**
- `tests/test_n8n_client.py` — mocked httpx, exercises the new endpoint paths and version normalization
- `tests/test_n8n_job_executor.py` — mocked N8nClient, exercises create → activate → trigger flow with realistic n8n response shapes
- `tests/test_n8n_webhook_extraction.py` — extracts webhook URL from a sample workflow JSON correctly

### Round 5 — Async notifications (free from startup pipeline's Round 5)

The notification framework, signed approval URLs, email + PDF rendering, and approve-by-link endpoint already exist. The side hustle pipeline just needs to **opt in** by:

- Wiring the approval-gate notification to call the existing `notify(workflow_id, "awaiting_approval")` hook (already happens for any workflow that pauses, so this should already work — verify by running it).
- Adding a side-hustle-specific email template variant in `app/services/report_renderer.py` so the PDF shows hustle-specific fields (income range, n8n workflow spec, expected runtime) instead of startup-specific fields (defensibility scores, MVP spec).
- The build-complete notification fires on `build_n8n_workflow` succeeding the same way it fires on `build_mvp`. The notification body should include the n8n workflow URL and a link to the deployed n8n web UI.
- Optional: a third notification on `test_run` completion with the execution result, since this is the actual "did it work" moment.

**No code changes** to the notification framework itself. Just template plumbing.

### Round 6 — Optional polish

- Deep research mode for side hustles (mirror the `_apply_deep_research_mode` helper, bump per-step timeouts, broaden landscape in deep mode)
- Cost dashboard at `/dashboard` showing side hustle pipeline runs alongside startup runs
- Track which hustles the user explicitly DIDN'T pick across runs as negative context for future scans
- Notification HTML template on disk for side hustle reports

---

## Critical files to modify (summary table for implementation)

| File | Round | Change |
|------|-------|--------|
| `app/workflows/templates.py` | 1 | Rewrite all 5 side hustle prompts (research, feasibility, contrarian, synthesis, build) with quality bars |
| `app/workflows/schemas.py` | 2 | New `SideHustleResearchResult`, `SideHustleFeasibilityResult`, `SideHustleContrarianResult`, `SideHustleSynthesisResult` |
| `app/workflows/templates.py` | 2 | Add `output_schema`, `max_retries`, `context_inputs` to every step |
| `app/workflows/templates.py` | 2 | Rewrite deploy/test prompts to read previous results via context_inputs, not via `{build_result}` interpolation |
| `app/models/workflow.py` | 3 | Add optional `required_artifacts: list[str] \| None` to `StepDefinition` |
| `app/jobs/builder.py` | 3 | Read `required_artifacts` from StepDefinition; fall back to current hardcoded list |
| `app/jobs/builder.py` | 3 | New `validate_n8n_workflow_json` helper; call it from a side-hustle-specific path |
| `app/services/workflow_service.py` | 3 | Approval gate's `selected_hustle` flows into build step the same way `selected_idea` does |
| `app/tools/n8n.py` | 4 | **Full rewrite.** New activate/deactivate endpoints, replace execute_workflow with webhook trigger, version-aware status normalization, per-method timeouts, retry-with-backoff |
| `app/jobs/n8n.py` | 4 | Deploy step extracts webhook URL from workflow JSON; test step reads test_payload.json and POSTs to webhook URL |
| `app/jobs/n8n.py` | 4 | Live polling progress callback for long executions |
| `app/services/report_renderer.py` | 5 | Side-hustle-specific PDF/email template variant |
| `app/api/workflow_routes.py` | 5 | Approve-link wiring for `selected_hustle` (mirrors `selected_idea`) |
| `scripts/run_side_hustle_pipeline.sh` | 3 | Formatted approval display + cost line, mirroring the startup script's Round 3 polish |
| `tests/test_side_hustle_schemas.py` | 2 | **NEW** |
| `tests/test_side_hustle_prompts.py` | 1 | **NEW** |
| `tests/test_side_hustle_prompt_alignment.py` | 2 | **NEW** |
| `tests/test_n8n_client.py` | 4 | **NEW** |
| `tests/test_n8n_job_executor.py` | 4 | **NEW** |
| `tests/test_n8n_webhook_extraction.py` | 4 | **NEW** |
| `tests/test_n8n_workflow_validator.py` | 3 | **NEW** |
| `tests/test_side_hustle_builder_artifacts.py` | 3 | **NEW** |
| `tests/test_side_hustle_approval.py` | 3 | **NEW** |

---

## Order of operations

The startup pipeline shipped its rounds sequentially because each round depended on the previous (schemas needed prompts; tests needed schemas; cost tracking needed validation; live progress needed streaming). The side hustle pipeline has the same dependency graph PLUS the n8n REST rewrite as a hard prerequisite for any meaningful end-to-end test.

**Critical path:**

1. **Round 4 first (n8n REST rewrite).** Without this, no end-to-end test of any other round is possible. Prove the integration works against the actual running n8n container with a hand-crafted minimal workflow before touching any prompt code.
2. **Round 1 (prompts) second.** Now you can run the pipeline and see what comes out of each step.
3. **Round 2 (schemas + tests) third.** Lock in the prompt outputs with strict validation.
4. **Round 3 (UX + builder enforcement) fourth.** Polish the approval flow and require all artifacts.
5. **Round 5 (notification template variant) last.** Free win once everything else is solid.
6. **Round 6 (optional polish).** Whenever.

This is the inverse order of the startup pipeline's rounds — for the startup pipeline we did prompts first because the integration was already working. For the side hustle pipeline the integration is the bottleneck.

---

## Open questions before starting Round 4

These need answers before I can spec the n8n REST rewrite precisely:

1. **What version of n8n is currently running on the Windows host?** Run `docker compose exec n8n n8n --version`. The API contract differs between v0.x and v1.x significantly.
2. **Is the X-N8N-API-KEY actually working today?** The env var sets it but n8n requires a personal API key generated in the UI (Settings → API). Has that been done? If not, every API call already 401s.
3. **Is the n8n container even reachable from the worker container?** `docker compose exec worker curl -s http://n8n:5678/healthz` should return ok.
4. **Should the side hustle pipeline use the existing n8n container or get its own?** The current setup shares one, which is fine for now but means user-created workflows and pipeline-created workflows mix together.

Get these four answers before writing any code.

---

## What ships when

Each round is independently shippable and disciplined to the same "small named tested fix" bar the startup pipeline used. No Big Bang rewrites. Every commit message references its round, every change has tests, every round ends with a deployable state.

The estimated breakdown by round (engineering time, not wall clock):
- Round 4 (n8n REST rewrite): largest. 1-2 days of focused work plus integration testing against a real n8n instance.
- Round 1 (prompts): medium. ~0.5-1 day per prompt × 5 prompts.
- Round 2 (schemas + tests): medium. Mostly mechanical given the templates from the startup pipeline's schemas.py.
- Round 3 (UX + builder enforcement): small. Each fix is local.
- Round 5 (notification template): small. Mostly template tweaks.

**Recommended kick-off:** answer the four open questions above, then start Round 4 with a single end-to-end happy-path test against the live n8n container (deploy a minimal "Hello World" webhook workflow, trigger it, get a response). Until that test is green, nothing else matters.
