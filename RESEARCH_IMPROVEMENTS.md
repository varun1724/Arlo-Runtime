# Startup Research Pipeline — Improvement Tracker

## Recent Changes

### Round 1: Prompt Quality Pass (templates.py)
All 5 prompt steps in `app/workflows/templates.py` (`STARTUP_IDEA_PIPELINE`) overhauled. JSON output schemas extended (new fields added) but all existing keys retained for backward compatibility.

- **Step 0 (landscape_scan):** Added contrarian sourcing instructions (Reddit, HN, GitHub, Product Hunt, YC RFS), required `timing_signal_type` from a 6-category taxonomy (REGULATORY_SHIFT, TECHNOLOGY_UNLOCK, BEHAVIORAL_CHANGE, COST_COLLAPSE, DISTRIBUTION_UNLOCK, INCUMBENT_FAILURE), added `non_obviousness_check` requiring 5+ non-obvious opportunities.
- **Step 1 (deep_dive):** Replaced vague `pricing_benchmarks` with structured `unit_economics` block (typical_price_point, billing_model, cac_channel, gross_margin_signal). Added tiered `demand_signals` (HOT/WARM/COLD). Added `no_competitors_classification` (overlooked vs no_demand vs too_hard vs too_small). Added required `early_failure_signal` per opportunity.
- **Step 2 (contrarian_analysis):** Required NAMED failed predecessors (no vague "many failed"). Required 5-year incumbent look-back with specific evidence/sources. Added regulatory checklist that self-identifies regulated domains (fintech, health, education, EU, hiring). Added `kill_probability` (low/medium/high).
- **Step 3 (synthesis_and_ranking):** Added score anchors (1/5/8/10 definitions for each dimension). Added `moats` taxonomy (network_effects, switching_costs, data_advantage, brand_or_trust, distribution_lock). Switched to weighted `total_score` (max 100, solo_dev_feasibility and revenue_potential weighted 1.5x). Added `head_to_head` field for comparative ranking. Tightened MVP spec: added `core_user_journey`, `out_of_scope`, `success_metric`, `risky_assumption`. Defined MVP strictly as deployable software.
- **Step 5 (build_mvp):** Added explicit scope rules — build only rank-1 idea, ignore ranks 2-5, treat `out_of_scope` as forbidden. Echoed strict MVP definition. Required `BUILD_DECISIONS.md` artifact explaining tech choices, tradeoffs, what was NOT built, and how to test the risky_assumption.

**Verified:** `templates.py` parses; all 6 steps render correctly with sample context.
**Pending deployment:** commit + push + ssh vsara@100.75.94 + git pull + rebuild.

### Round 2: Structural & Architectural Pass

Framework-level changes that no amount of prompt engineering can fix. Added strict per-step output validation, context pruning, calibrated timeouts, and a thorough test framework that retroactively validates Round 1.

**New: `app/workflows/schemas.py`** — Pydantic models for every research step output (`LandscapeResult`, `DeepDiveResult`, `ContrarianResult`, `SynthesisResult`). Mirrors the JSON contracts in the prompt templates. Versioned names (`startup_landscape_v1`, etc.) so future schema changes coexist with legacy templates. Critical lists use `min_length` so silent empty-output failures surface as validation errors. All models use `extra="allow"` for forward compatibility.

**Extended `StepDefinition`** (`app/models/workflow.py`) — added two optional fields:
- `output_schema: str | None` — name lookup into `STEP_OUTPUT_SCHEMAS`
- `context_inputs: list[str] | None` — whitelist of context keys passed to prompt rendering

Both default to `None` for full backward compatibility.

**Strict validation in `app/jobs/research.py`** — research jobs now load their `StepDefinition` from the workflow row, look up the schema in the registry, and validate the parsed JSON. Validation failures and JSON parse errors raise `ClaudeRunError` (instead of silently storing raw strings), which feeds the existing `max_retries` auto-retry path. The stored JSON is normalized via `model_dump_json()` so downstream steps see clean input.

**Context pruning in `app/services/workflow_service.py`** — extracted `_prune_context` and `_should_retry_step` as pure helpers. `_create_step_job` now respects `step.context_inputs`, passing only whitelisted keys to the prompt renderer. The full context is still saved on the workflow row for debugging.

**`startup_idea_pipeline` template wired up:**
| Step | output_schema | max_retries | timeout | context_inputs |
|---|---|---|---|---|
| landscape_scan | startup_landscape_v1 | 2 | 900s (15m) | — |
| deep_dive | startup_deep_dive_v1 | 2 | 1800s (30m) | — |
| contrarian_analysis | startup_contrarian_v1 | 2 | 1800s (30m) | — |
| synthesis_and_ranking | startup_synthesis_v1 | 2 | 1200s (20m) | — |
| build_mvp | — | — | 1200s | `["synthesis"]` |

**Settings hardening** — `app/core/config.py` now uses `extra="ignore"` so Settings tolerates unrelated `.env` keys (e.g. docker-compose vars). One-line fix that lets local tests run without docker.

**Test framework — 71 new tests, 84 total passing locally:**

| File | Tests | Purpose |
|---|---|---|
| `tests/fixtures/startup_pipeline_fixtures.py` | (fixtures) | VALID/MINIMAL/INVALID samples for every step output |
| `tests/test_startup_schemas.py` | 29 | Pydantic schema unit tests, registry lookup, completeness |
| `tests/test_prompt_schema_alignment.py` | 7 | **Catches Round 1 prompt drift.** Extracts JSON example from each prompt template, populates placeholders, validates against the matching schema. |
| `tests/test_research_validation.py` | 15 | Strict, loose, and standalone modes of `_extract_result`. Mocks Claude output. |
| `tests/test_workflow_context_pruning.py` | 13 | `_prune_context` unit tests + headline assertion that pruning shrinks the rendered prompt by 50%+. |
| `tests/test_workflow_retry.py` | 7 unit + 3 integration | `_should_retry_step` decision math + DB-backed retry-path tests. |
| `tests/test_workflows.py` | +2 | Asserts `STARTUP_IDEA_PIPELINE` template has the new fields wired up correctly. |
| `scripts/run_tests.sh` | (script) | Wrapper for `docker compose exec api pytest`. |

**The alignment tests retroactively validate Round 1.** If a future prompt edit introduces a typo or renames a field, the Pydantic example in the prompt's OUTPUT block stops matching the schema, and `test_*_prompt_example_matches_schema` fails immediately. This closes the silent-drift loophole.

**Local verification:**
```
python3 -m pytest \
  tests/test_startup_schemas.py \
  tests/test_prompt_schema_alignment.py \
  tests/test_research_validation.py \
  tests/test_workflow_context_pruning.py \
  tests/test_workflow_retry.py \
  --noconftest -v -k "not (failed_step or exhausted)"
# 71 passed in 0.44s
```

**Pending deployment:** commit + push + ssh vsara@100.75.94 + cd C:\trading\arlo-runtime + git pull + docker compose up -d --build, then `./scripts/run_tests.sh` to run the full suite (including the 3 DB integration tests in `test_workflow_retry.py` and 2 in `test_workflows.py`).

### Round 3: Approval UX, Build Enforcement, Quality Bars, Cost Visibility

A fresh sweep of the pipeline after Round 2 turned up several high-impact bugs that weren't visible in earlier reviews. Round 3 closes the rest of the tracker AND fixes those.

**Headline bug fixed: user can now actually pick a non-#1 idea.** The script previously displayed "Pick an idea [1-N]" but discarded the choice and always built rank-1. Now:
- `scripts/run_startup_pipeline.sh` parses the user's choice, finds the matching ranking from synthesis, and sends it as `context_overrides.selected_idea` to the approve endpoint
- `app/workflows/templates.py` build_mvp prompt rewired to read `{selected_idea}` with `context_inputs=["selected_idea"]`
- `app/services/workflow_service.py` approve_step has a defensive fallback: if a downstream step needs `selected_idea` and the caller didn't supply one, default to rank-1 from prior synthesis (preserves backward compat for direct API callers)

**Builder artifact enforcement.** Round 1 added a `BUILD_DECISIONS.md` requirement to the build_mvp prompt, but `app/jobs/builder.py` only checked for `arlo_manifest.json` — so missing artifacts were silently lost. Now:
- New `REQUIRED_BUILDER_ARTIFACTS = ("README.md", "BUILD_DECISIONS.md")` constant
- `_check_required_artifacts` direct-Path scan (avoids the workspace scanner's dotfile filter)
- Missing artifacts raise `ClaudeRunError`, feeding the workflow's auto-retry path
- `build_mvp` step now has `max_retries=1` (one retry on missing files; building is expensive)
- `builder.py` also honors per-step `timeout_override` (mirrors Round 2's research.py plumbing)

**Tighter data-quality validation.** Schemas were too lenient; Claude could produce technically-valid-but-low-quality output. Now:
- `SynthesisResult.final_rankings` requires `min_length=3` (was 1)
- `SynthesisRanking.total_score` requires `ge=20.0` (force a retry rather than display garbage)
- `MvpSpec` field min_lengths: `core_user_journey>=20`, `risky_assumption>=15`, `success_metric>=15`, `validation_approach>=15`, `what_to_build>=20`, `tech_stack>=3`
- Fixtures updated; new INVALID variants for "too few rankings", "low total_score", "short risky_assumption", "short core_user_journey"

**Friendly validation error messages.** Replaced verbose Pydantic ValidationError dumps with one-line user-facing messages. Added `_friendly_validation_error` helper in `research.py` that extracts the offending field name and the constraint message. Used in both strict-mode workflow validation and standalone ResearchReport validation. Tests assert messages are <300 chars and contain the field name.

**Token/cost tracking** (full plumbing):
- Three new nullable columns on `JobRow`: `tokens_input`, `tokens_output`, `estimated_cost_usd`
- Alembic migration `0004_add_token_cost_columns.py`
- New `extract_usage()` helper in `app/services/claude_runner.py` with per-model price table (haiku/sonnet/opus, conservative pricing)
- `research.py` and `builder.py` extract usage after each Claude call and pass to `finalize_job`
- `JobResponse` and `WorkflowResponse` Pydantic models extended with the new fields
- `_workflow_to_response` aggregates per-job costs into `total_tokens_input/output` and `total_estimated_cost_usd` via SQL `SUM`
- `run_startup_pipeline.sh` displays "Research cost so far: $X.XXXX" at the approval gate

**Recovery loop if all ideas killed:**
- New `loop_condition: StepCondition | None` on `StepDefinition` — gates `loop_to` on a runtime check (defaults to None for backward compat)
- New condition operator `survivor_count_below` and `_count_survivors` helper that counts opportunities with verdict in `{survives, weakened}`
- `contrarian_analysis` step in `STARTUP_IDEA_PIPELINE` now has `loop_to=0`, `max_loop_count=2`, `loop_condition={survivor_count_below 3}`
- When the loop fires, `advance_workflow` injects `previous_attempt_killed_all="true"` into context
- The `landscape_scan` prompt detects this flag and switches into "RECOVERY MODE" — broadens the search, lowers the obviousness bar, leans harder on contrarian sources

**Founder/team patterns** (existing tracker item):
- `deep_dive` prompt extended with founder/team analysis instructions covering 5 archetypes (DOMAIN_EXPERT, TECHNICAL, REPEAT, FIRST_TIME, MIXED)
- `DeepDiveOpportunity` schema gained optional `founder_patterns: str | None` field

**Test framework — 36 new tests, 120 total passing locally:**

| File | Tests | Purpose |
|---|---|---|
| `tests/test_startup_schemas.py` | +4 | Quality bar tests (too few rankings, low total_score, short MVP fields) |
| `tests/test_research_validation.py` | +4 | Friendly error helper coverage |
| `tests/test_workflow_models.py` | +2 | `loop_condition` field on StepDefinition |
| `tests/test_loop_recovery.py` | **NEW** 18 | `_count_survivors` + `survivor_count_below` operator + template wiring assertions |
| `tests/test_builder_artifact_enforcement.py` | **NEW** 8 | `_check_required_artifacts` + max_retries on build_mvp |
| `tests/test_workflow_approval.py` | **NEW** 3 (DB-bound) | End-to-end `context_overrides` with selected_idea + fallback to rank-1 |
| `tests/fixtures/startup_pipeline_fixtures.py` | (extended) | VALID_SYNTHESIS bumped to 3 rankings; new INVALID variants for Round 3 constraints |
| `tests/test_workflow_context_pruning.py` | (updated) | Asserts build_mvp uses `selected_idea`, not `synthesis` |
| `tests/test_prompt_schema_alignment.py` | (updated) | Longer placeholder strings to satisfy Round 3 min_length |

**Local verification:**
```
python3 -m pytest \
  tests/test_startup_schemas.py tests/test_prompt_schema_alignment.py \
  tests/test_research_validation.py tests/test_workflow_context_pruning.py \
  tests/test_workflow_retry.py tests/test_loop_recovery.py \
  tests/test_builder_artifact_enforcement.py tests/test_workflow_models.py \
  tests/test_research_models.py tests/test_builder_models.py \
  --noconftest -q -k "not (failed_step or exhausted)"
# 120 passed in 0.47s
```

**Pending deployment:** commit + push + git pull + `docker compose build api && docker compose up -d api && docker compose exec -T api alembic upgrade head` (to apply 0004), then `./scripts/run_tests.sh`.

**Manual verification (post-deploy):**
1. Run `./scripts/run_startup_pipeline.sh "AI dev tools" "code review" "solo dev"`
2. At the approval gate, pick idea **#2** (not the default)
3. Confirm the rendered build_mvp prompt contains idea #2's name (not idea #1's)
4. Confirm the workspace contains `BUILD_DECISIONS.md` after the build
5. Check the workflow's `total_estimated_cost_usd` is populated and shown at the gate
6. Optional: run with a deliberately narrow domain so contrarian kills everything → confirm the loop fires and landscape gets `previous_attempt_killed_all=true`

## Structural Issues

- [x] **No JSON validation on workflow outputs** — Round 2: per-step Pydantic schemas in `app/workflows/schemas.py`, registered via `StepDefinition.output_schema`, validated in `_extract_result` with strict mode. Validation failures raise `ClaudeRunError` and trigger auto-retry.
- [x] **Context balloons to 50KB+** — Round 2: `StepDefinition.context_inputs` whitelist + `_prune_context` helper. `build_mvp` set to `["synthesis"]`. Headline test asserts 50%+ size reduction.
- [x] **Uniform 1800s timeout for all steps** — Round 2: calibrated per step (landscape 900, deep_dive/contrarian 1800, synthesis 1200, build_mvp 1200). `claude_runner` already honored `timeout_override`; just needed wiring through `execute_research_job`.
- [x] **No error recovery path** — Round 2: strict mode raises `ClaudeRunError` on bad JSON, which propagates through the existing `max_retries=2` auto-retry logic in `advance_workflow`.

## Prompt Quality Issues

- [x] **Subjective scoring with no anchors** — Added explicit 1/5/8/10 anchors for all 5 dimensions in Step 3.
- [x] **No moat taxonomy** — Added 5-dimension `moats` block (network_effects, switching_costs, data_advantage, brand_or_trust, distribution_lock) in Step 3. Defensibility score derived from this.
- [x] **MVP spec is vague** — Defined MVP strictly as "deployable software with one user-facing feature solving the core problem end-to-end". Added core_user_journey, out_of_scope, success_metric, risky_assumption fields.
- [x] **No recovery if all ideas killed** — Round 3: contrarian step now has `loop_to=0`, `max_loop_count=2`, and a `loop_condition: survivor_count_below 3`. When fewer than 3 opportunities survive, the workflow loops back to landscape with `previous_attempt_killed_all=true` injected; the landscape prompt detects this and broadens the search.
- [x] **Total score is unweighted sum** — Now weighted (max 100): solo_dev_feasibility ×1.5, revenue_potential ×1.5, market_timing ×1.0, defensibility ×1.0, evidence_quality ×0.5.

## Missing Features

- [ ] **No streaming/partial results** — Each research step takes 20-30 mins. User sees "running" with no intermediate feedback for 1-2 hours total. *(Deferred to Round 4 — needs SSE plumbing through claude_runner)*
- [x] **No cost/token tracking** — Round 3: `tokens_input`, `tokens_output`, `estimated_cost_usd` per JobRow + `total_estimated_cost_usd` aggregate on WorkflowResponse. Displayed at the approval gate.
- [x] **No competitor pricing/unit economics** — Added structured `unit_economics` block (price point, billing model, CAC channel, gross margin signal) in Step 1.
- [x] **No regulatory analysis** — Added explicit regulatory checklist in Step 2 with self-identification for fintech, health, education, EU, hiring, etc.
- [x] **No founder/team pattern analysis** — Round 3: deep_dive prompt now asks for founder archetype (DOMAIN_EXPERT, TECHNICAL, REPEAT, FIRST_TIME, MIXED) with optional `founder_patterns` field on `DeepDiveOpportunity`.
- [x] **No demand validation step** — Added tiered demand_signals (HOT/WARM/COLD) in Step 1 with clear definitions.
- [x] **No comparative scoring** — Added `head_to_head` field in Step 3 forcing each opportunity to explain why it beats the next-ranked one.

## Architecture Improvements

- [x] **Add contrarian → landscape loop** — Round 3: implemented via new `loop_condition` field on `StepDefinition` and `survivor_count_below` operator. Loops up to 2 times when fewer than 3 ideas survive contrarian.
- [x] **Prune context for Step 5** — Round 2: `build_mvp` now has `context_inputs=["selected_idea"]` (Round 3 update — was `["synthesis"]` in Round 2).
- [x] **Per-step timeout calibration** — Round 2: applied via `timeout_override` on each step.
- [x] **Validate synthesis before approval** — Round 2 + Round 3 quality bars: `SynthesisResult.final_rankings >= 3`, `total_score >= 20`, `MvpSpec` fields have min_lengths.
- [ ] **Evidence verification post-processing** — Optional step to verify that 3+ key facts per opportunity (company names, funding amounts, market sizes) are real. Deferred — non-trivial (needs web search verification step).

## Round 3 Bugs Fixed (caught in fresh sweep)

- [x] **User couldn't pick a non-#1 idea** — Script discarded the user's choice; build_mvp always built rank-1. Fixed by sending `selected_idea` via `context_overrides` and rewiring build_mvp to read it.
- [x] **`BUILD_DECISIONS.md` requirement not enforced** — Round 1 added it to the prompt; Round 3 actually checks for it via `_check_required_artifacts`.
- [x] **Builder didn't honor per-step `timeout_override`** — Mirror of the Round 2 plumbing in research.py; builder now reads the StepDefinition.
- [x] **Synthesis quality bar too lax** — Schema accepted empty MVP fields and a single low-score ranking. Fixed via min_lengths and `total_score>=20`.
- [x] **Validation errors were verbose Pydantic dumps** — Replaced with one-line friendly errors.

## Deferred to Round 4

- [x] **Streaming partial results** — Round 4: `run_claude` now defaults to `--output-format stream-json`. Line-by-line event parsing with optional `on_progress` callback. research.py and builder.py both use a throttled (5s) callback that updates `progress_message`, `tokens_input`, `tokens_output`, `estimated_cost_usd` in real time. `WorkflowProgressEvent` extended with `current_job_id` and live token/cost fields. Script displays live tokens in the polling line.
- [ ] Evidence verification post-processing (needs a web-search verification step) — deferred to Round 5
- [ ] Worker-restart race condition with distributed locking (real but lower priority) — deferred to Round 5
- [x] **Targeted contributor doc** — Round 4: new `docs/ADDING_A_TEMPLATE.md` walks through the 5-step recipe for adding a new workflow template with references to the existing startup_idea_pipeline as the worked example.

### Round 4: Bug Hardening, Test Coverage, and Live Progress Visibility

A fresh sweep after Round 3 turned up two real bugs that tests were hiding by luck, plus several uncovered code paths. Round 4 fixes them AND adds the headline deferred feature — live progress visibility during long Claude calls.

**Bug A fixed: `selected_idea` was rendered as Python `repr()`, not JSON.**
- `_render_prompt` in `app/services/workflow_service.py` used `str(v) for v in context.values()`. For Python dicts (the shape `selected_idea` takes after Round 3's `context_overrides` path), `str()` produces `{'rank': 2, 'name': '...'}` — Python repr, NOT JSON. The Round 3 test passed only because `"second idea"` happened to be a substring of the Python repr.
- Fix: new `_stringify_for_prompt` helper that JSON-encodes dicts and lists with `indent=2`. Strings pass through unchanged so existing JSON-string step outputs keep working.
- Tests: 7 new regression tests in `test_workflow_context_pruning.py` asserting dict values render as valid JSON, list values render as valid JSON, and string values remain untouched.

**Bug B fixed: `extract_usage` crashed on string token counts.**
- `claude_runner.py` did `usage.get("cache_creation_input_tokens") or 0` — preserves any truthy value as-is, including strings. Then `input_tokens + cache_creation + cache_read` raised `TypeError: int + str` when a buggy CLI version emitted `"100"`.
- Fix: new `_safe_int` helper that coerces int/str/None defensively. All four usage fields now go through it.
- Tests: 6 new regression tests in `test_research_validation.py` covering string cache tokens, string primary tokens, garbage values, and the helper directly.

**Loop count semantics clarified (doc-only).** Added a docstring to `StepDefinition.max_loop_count` explaining the exact semantics: "maximum number of times the loop_to step is allowed to execute, INCLUDING its initial run." Plus 3 new tests in `test_loop_recovery.py` documenting the boundary math (`max=2 → 2 total runs, max=1 disables loop, max=3 → 3 total runs`).

**Test coverage gaps closed:**
- `test_workflow_approval.py`: 3 new tests for malformed synthesis fallback (empty rankings, null rank-1, empty-dict rank-1) — proves the fallback doesn't crash on edge cases
- `tests/test_workflow_cost_aggregation.py` (NEW): 2 DB-bound tests proving `total_estimated_cost_usd` is `None` (not 0) when no jobs report usage, and sums correctly when they do
- `test_builder_artifact_enforcement.py`: +1 test asserting the missing-artifact path raises `ClaudeRunError` specifically (the exact exception type that triggers max_retries)

**Headline new feature: streaming Claude CLI output.**
- `run_claude` in `app/services/claude_runner.py` defaults to `--output-format stream-json --verbose`
- New `_run_claude_streaming` helper reads `process.stdout.readline()` in an async loop, parses each line as a JSON event, accumulates `type: assistant` text blocks, and extracts `usage`/`model` from system init and result events
- Malformed lines are skipped with a debug log (not fatal)
- Deadline check on every iteration → timely `ClaudeTimeoutError` even mid-stream
- Legacy `_run_claude_buffered` path kept for `output_format != "stream-json"` callers
- Returns the SAME dict shape as before so existing callers don't change
- Optional `on_progress` callback fires once per parsed event with `{accumulated_chars, usage, model}`. Misbehaving callbacks are caught and logged; they never kill the run
- `research.py` and `builder.py` wire up a 5-second throttled callback that updates `progress_message`, `tokens_input`, `tokens_output`, `estimated_cost_usd` on the JobRow during long-running Claude calls
- `WorkflowProgressEvent` extended with `current_job_id`, `tokens_input_so_far`, `tokens_output_so_far`, `cost_so_far_usd`
- `/workflows/{id}/stream` SSE endpoint populates the new fields from the latest job
- `scripts/run_startup_pipeline.sh` polling line now shows `| 12,453 in / 3,201 out | $0.0832` when live cost data is present

**Test framework — 14 new tests, 145 total passing locally:**

| File | Tests | Purpose |
|---|---|---|
| `tests/test_workflow_context_pruning.py` | +7 | Bug A regression + `_stringify_for_prompt` helper |
| `tests/test_research_validation.py` | +6 | Bug B regression + `_safe_int` helper |
| `tests/test_loop_recovery.py` | +3 | Loop count boundary math |
| `tests/test_workflow_approval.py` | +3 (DB) | Fallback edge cases with malformed synthesis |
| `tests/test_workflow_cost_aggregation.py` | **NEW** 2 (DB) | SUM returns None when all null, sums correctly otherwise |
| `tests/test_builder_artifact_enforcement.py` | +1 | Exact exception type (ClaudeRunError) is raised |
| `tests/test_claude_runner_streaming.py` | **NEW** 8 | Stream-json runner: assembles result, calls on_progress, handles malformed JSON, handles empty lines, nonzero exit, timeout, callback exception tolerance |

**Local verification:**
```
python3 -m pytest \
  tests/test_startup_schemas.py tests/test_prompt_schema_alignment.py \
  tests/test_research_validation.py tests/test_workflow_context_pruning.py \
  tests/test_workflow_retry.py tests/test_loop_recovery.py \
  tests/test_builder_artifact_enforcement.py tests/test_workflow_models.py \
  tests/test_research_models.py tests/test_builder_models.py \
  tests/test_claude_runner_streaming.py \
  --noconftest -q -k "not (failed_step or exhausted)"
# 145 passed in 1.52s
```

**Pending deployment:** commit + push + git pull + `docker compose build api && docker compose up -d api`. **No new alembic migration** — Round 4 reuses the token/cost columns from Round 3's `0004` migration.

**Manual verification (post-deploy):**
1. Start a fresh startup_idea_pipeline run and watch the polling line — token counts should increment during long Claude calls, not stay at zero until the job finishes
2. Hit `GET /workflows/{id}/stream` and confirm the SSE events contain `current_job_id`, `tokens_input_so_far`, and `cost_so_far_usd`
3. After approval, inspect the build_mvp job's prompt via psql — the `SELECTED OPPORTUNITY:` block should contain valid JSON (verified parseable), not Python repr with single quotes
4. Run a build that intentionally omits `BUILD_DECISIONS.md` → confirm the first attempt fails with a `ClaudeRunError` about missing artifacts and the retry kicks in automatically

### Round 5: Async Notifications, Remote Approval, Deep Research Mode

**The motivation:** the user runs everything on a Windows worker via Tailscale and pays nothing-per-token (Claude Max). Round 4's pipeline still required them to babysit a terminal — `run_startup_pipeline.sh` is an interactive polling client that blocks on stdin for the approval choice. Round 5 cuts the laptop tether: kick off a workflow with one curl, walk away, get an emailed PDF with the ranked ideas, click an approval link from your phone, get a second email when the build is done with a tar.gz download link.

**Headline new capability — async notification framework + remote approval:**

- **`app/services/notifications.py`** (NEW) — pluggable dispatcher fired by `advance_workflow` at three transition points: `awaiting_approval`, `build_complete`, `workflow_failed`. Wrapped in try/except so notification failures NEVER break the workflow. Opt-in: a blank `approval_recipient_email` makes it a no-op.
- **`app/services/email_sender.py`** (NEW) — `aiosmtplib` wrapper, one async function. Builds `multipart/mixed` (with `multipart/alternative` for HTML+text) and supports attachments. STARTTLS by default.
- **`app/services/report_renderer.py`** (NEW) — `weasyprint`-based renderer. Takes a parsed `SynthesisResult` and a list of `(rank, name, signed_url)` approval links, returns `(html_body, text_fallback, pdf_bytes)`. Inline mobile-friendly CSS, one card per ranking with score breakdown, MVP spec, and a prominent **Build this one →** button. PDF is attached for offline reading on a phone.
- **`app/services/signed_urls.py`** (NEW) — stateless HMAC-SHA256 signed tokens. Reuses `arlo_auth_token` as the secret (no new secret to rotate). 48-hour TTL. Encodes `{wf, choice, exp, p}` (purpose differentiates `approve` vs `artifacts` so an approval token can't be reused for a workspace download).
- **`GET /workflows/{id}/approve-link/{token}`** — public endpoint, no bearer auth (the HMAC IS the auth). Verifies signature + expiry + purpose, looks up the chosen ranking from the workflow's stored synthesis, calls `approve_step` with `selected_idea` in `context_overrides`. Returns a small HTML success/error page (clicked from an email client). Mounted on a separate `public_router` so FastAPI's dependency injection doesn't require a header.
- **`GET /workflows/{id}/artifacts.tar.gz?token=...`** — streams the `build_mvp` job's workspace as a gzipped tarball. Same signed-URL mechanism, different purpose. In-memory tar is fine for typical workspace sizes.

**Headline new capability — deep research mode (Claude Max):**

- **`CreateWorkflowFromTemplateRequest.deep_research_mode: bool = False`** — opt-in flag. When true, `_apply_deep_research_mode` (in `app/workflows/templates.py`) deep-copies the step list, bumps `contrarian_analysis.max_loop_count` from 2 → 4, bumps `landscape_scan.timeout_override` from 900s → 1800s, and injects `deep_mode="true"` into `initial_context`. The landscape, deep_dive, and synthesis prompt templates gained a `{deep_mode}` placeholder + a "DEEP RESEARCH MODE — aim for the high end of each count" instruction block that fires only when the substituted value is `"true"`. Defaults preserve Round 1-4 behavior exactly.

**Round 4 bug sweep (small):**

- **`scripts/run_startup_pipeline.sh`** truthiness bug: `if tin or tout or cost:` was False when any value was zero. Fixed to `is not None`.
- **Stream-json `tool_use` / `tool_result` events** were silently dropped by Round 4's parser, so the live progress message never reflected "Claude is searching the web." `_run_claude_streaming` now tracks `latest_tool_activity` from both inline assistant blocks and top-level events, and exposes it as `tool_activity` in the on_progress snapshot. `research.py` and `builder.py` prepend it to the progress_message: e.g. `"Using WebSearch — Streaming output (12,453 chars, 3,201 tokens out)"`.

**Settings additions** (`app/core/config.py`): `smtp_host`, `smtp_port`, `smtp_username`, `smtp_password`, `email_from_address`, `approval_recipient_email`, `notification_base_url`. All blank-by-default; setting `approval_recipient_email` is the single switch that turns notifications on.

**Dockerfile changes:** both `Dockerfile.api` and `Dockerfile.worker` now `apt-get install` weasyprint's runtime deps (`libpango-1.0-0`, `libpangoft2-1.0-0`, `libharfbuzz0b`, `fontconfig`). The worker needs them too because `notifications.notify()` fires from `advance_workflow` which runs in the worker process. `pyproject.toml` gains `aiosmtplib>=3.0.0` and `weasyprint>=62.0`.

**Test framework — ~50 new tests:**

| File | Tests | Purpose |
|---|---|---|
| `tests/test_signed_urls.py` | **NEW** 12 | HMAC roundtrip, tampered signature/payload, expiry, wrong purpose, malformed token, determinism, choice/wf isolation |
| `tests/test_email_sender.py` | **NEW** 5 | MIME structure, PDF attachment, STARTTLS, optional credentials, multiple attachments |
| `tests/test_report_renderer.py` | **NEW** 14 | HTML/text/PDF tuple, every ranking name appears, approval URLs in `href`, PDF magic bytes, plaintext fallback has no tags, missing-cost tolerance, HTML escaping, rankings without rank fields |
| `tests/test_notifications.py` | **NEW** 10 | Mocked email_sender; opt-in switch (blank recipient = no-op), exception swallowing, all 3 event types, attachments wired |
| `tests/test_deep_research_mode.py` | **NEW** 11 | Helper bumps loop count + timeout, injects deep_mode, doesn't mutate originals, prompts contain `{deep_mode}` + DEEP RESEARCH MODE marker, request model accepts the flag |
| `tests/test_workspace_download.py` | **NEW** 5 (DB) | Valid token streams gzip, invalid → 401, missing workspace → 404, no build job → 404 |
| `tests/test_workflow_approval.py` | +5 (DB) | approve-by-link valid token → builds idea, invalid → 401, mismatched wf → 400, choice=0 skips, wrong purpose rejected |
| `tests/test_claude_runner_streaming.py` | +2 | tool_use event populates `tool_activity`, tool_result clears it |

**Pending deployment:** commit + push + ssh vsara@100.75.94 + git pull + `docker compose build api worker` (Dockerfile changes affect both containers) + `docker compose up -d api worker`. **No new alembic migration** — signed URLs are stateless, notifications don't persist. Set the SMTP/recipient env vars in `.env` on the Windows machine.

**Manual end-to-end verification (the headline workflow):**
1. Kick off via curl with `"deep_research_mode": true`
2. Close laptop, walk away
3. ~45-60 minutes later: receive an email with the synthesis PDF + inline ranking cards
4. Click the approval link for the chosen idea on the phone
5. Browser shows success page; `build_mvp` runs
6. ~15 minutes later: receive the second email with the tar.gz download link
7. Download from the phone, inspect — should contain README.md, BUILD_DECISIONS.md, full project

## Deferred to Round 6

- [ ] Evidence verification post-processing (needs a separate Claude call with web search; non-trivial design)
- [ ] Worker-restart race condition with distributed locking (rare in practice)
- [ ] Schema versioning v2 path (premature until we actually need to break v1)
- [ ] iOS Arlo app deep integration (separate project; wait for REST API to stabilize)
- [ ] Notification HTML template on disk (move from inline string to `templates/emails/approval_gate.html`)
- [ ] Full CONTRIBUTING.md / WORKFLOW_DESIGN.md guides (the targeted `docs/ADDING_A_TEMPLATE.md` ships in Round 4; broader guides can come later)
