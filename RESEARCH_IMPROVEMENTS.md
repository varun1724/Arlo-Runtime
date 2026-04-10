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

## Structural Issues

- [ ] **No JSON validation on workflow outputs** — Standalone research validates against Pydantic models, but workflow steps store raw Claude output with no schema check. If Claude returns malformed JSON or wrong structure, downstream steps silently break.
- [ ] **Context balloons to 50KB+** — By Step 3, the prompt includes all prior JSON strings nested inside each other. Step 5 (build MVP) gets the entire history redundantly since synthesis already summarizes everything.
- [ ] **Uniform 1800s timeout for all steps** — Landscape scan is simpler than contrarian analysis, but all use the same timeout. Should calibrate per-step.
- [ ] **No error recovery path** — If Claude returns plain text instead of JSON, it gets stored as-is and subsequent steps fail when rendering prompts with non-JSON context.

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

- [ ] **Add contrarian → landscape loop** — If contrarian kills most ideas, loop back to Step 0 with expanded search. Add `loop_to: 0` with `max_loop_count: 2`.
- [ ] **Prune context for Step 5** — Only pass synthesis to build_mvp, not the entire context tree. Synthesis already contains everything needed.
- [ ] **Per-step timeout calibration** — Landscape: 900s, Deep dive: 1800s, Contrarian: 1800s, Synthesis: 1200s.
- [ ] **Validate synthesis before approval** — Check that `final_rankings` array exists, has required fields, scores are in range, MVP specs are complete.
- [ ] **Evidence verification post-processing** — Optional step to verify that 3+ key facts per opportunity (company names, funding amounts, market sizes) are real.
