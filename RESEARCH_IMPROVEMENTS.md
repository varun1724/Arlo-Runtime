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

## Structural Issues

- [x] **No JSON validation on workflow outputs** — Round 2: per-step Pydantic schemas in `app/workflows/schemas.py`, registered via `StepDefinition.output_schema`, validated in `_extract_result` with strict mode. Validation failures raise `ClaudeRunError` and trigger auto-retry.
- [x] **Context balloons to 50KB+** — Round 2: `StepDefinition.context_inputs` whitelist + `_prune_context` helper. `build_mvp` set to `["synthesis"]`. Headline test asserts 50%+ size reduction.
- [x] **Uniform 1800s timeout for all steps** — Round 2: calibrated per step (landscape 900, deep_dive/contrarian 1800, synthesis 1200, build_mvp 1200). `claude_runner` already honored `timeout_override`; just needed wiring through `execute_research_job`.
- [x] **No error recovery path** — Round 2: strict mode raises `ClaudeRunError` on bad JSON, which propagates through the existing `max_retries=2` auto-retry logic in `advance_workflow`.

## Prompt Quality Issues

- [x] **Subjective scoring with no anchors** — Added explicit 1/5/8/10 anchors for all 5 dimensions in Step 3.
- [x] **No moat taxonomy** — Added 5-dimension `moats` block (network_effects, switching_costs, data_advantage, brand_or_trust, distribution_lock) in Step 3. Defensibility score derived from this.
- [x] **MVP spec is vague** — Defined MVP strictly as "deployable software with one user-facing feature solving the core problem end-to-end". Added core_user_journey, out_of_scope, success_metric, risky_assumption fields.
- [ ] **No recovery if all ideas killed** — Contrarian analysis can kill every opportunity, and the workflow just produces an empty synthesis with no loop back to expand the search. *(Architectural — deferred to next round)*
- [x] **Total score is unweighted sum** — Now weighted (max 100): solo_dev_feasibility ×1.5, revenue_potential ×1.5, market_timing ×1.0, defensibility ×1.0, evidence_quality ×0.5.

## Missing Features

- [ ] **No streaming/partial results** — Each research step takes 20-30 mins. User sees "running" with no intermediate feedback for 1-2 hours total.
- [ ] **No cost/token tracking** — No visibility into Claude API usage before the approval gate. User can't make informed build/no-build decision.
- [x] **No competitor pricing/unit economics** — Added structured `unit_economics` block (price point, billing model, CAC channel, gross margin signal) in Step 1.
- [x] **No regulatory analysis** — Added explicit regulatory checklist in Step 2 with self-identification for fintech, health, education, EU, hiring, etc.
- [ ] **No founder/team pattern analysis** — Doesn't look at who founded competing startups or what team patterns correlate with success in this space.
- [x] **No demand validation step** — Added tiered demand_signals (HOT/WARM/COLD) in Step 1 with clear definitions.
- [x] **No comparative scoring** — Added `head_to_head` field in Step 3 forcing each opportunity to explain why it beats the next-ranked one.

## Architecture Improvements

- [ ] **Add contrarian → landscape loop** — If contrarian kills most ideas, loop back to Step 0 with expanded search. Needs a new condition operator that can inspect JSON paths (e.g. `final_rankings_empty`). Deferred to Round 3.
- [x] **Prune context for Step 5** — Round 2: `build_mvp` now has `context_inputs=["synthesis"]`.
- [x] **Per-step timeout calibration** — Round 2: applied via `timeout_override` on each step.
- [x] **Validate synthesis before approval** — Round 2: `SynthesisResult` schema enforces `final_rankings` non-empty, scores in range 1-10, all MVP spec fields including `risky_assumption` and `out_of_scope` required. Validation runs before the approval gate via `_extract_result` strict mode.
- [ ] **Evidence verification post-processing** — Optional step to verify that 3+ key facts per opportunity (company names, funding amounts, market sizes) are real. Deferred — non-trivial (needs web search verification step).
