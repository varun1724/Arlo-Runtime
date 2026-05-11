"""Pydantic schemas for validating workflow research outputs.

These schemas mirror the JSON contracts in the prompt templates in
``app/workflows/templates.py``. They are looked up by name from
``StepDefinition.output_schema`` via :data:`STEP_OUTPUT_SCHEMAS`.

Design notes:
- Every model uses ``ConfigDict(extra="allow")`` so that prompt-level
  field additions don't break in-flight workflows.
- Critical lists use ``min_length`` so that silent empty-output failures
  surface as schema validation errors and trigger the existing workflow
  retry mechanism.
- Model names are versioned (e.g. ``startup_landscape_v1``) so future
  schema breaks can coexist with legacy templates.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ─────────────────────────────────────────────────────────────────────
# Step 0: landscape_scan → LandscapeResult
# ─────────────────────────────────────────────────────────────────────

TimingSignalType = Literal[
    "REGULATORY_SHIFT",
    "TECHNOLOGY_UNLOCK",
    "BEHAVIORAL_CHANGE",
    "COST_COLLAPSE",
    "DISTRIBUTION_UNLOCK",
    "INCUMBENT_FAILURE",
]


class KeyPlayer(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    description: str
    estimated_revenue_or_funding: str


class LandscapeOpportunity(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    description: str
    timing_signal_type: TimingSignalType
    timing_signal: str
    evidence: str
    non_obviousness_check: Literal["yes", "no"]
    non_obviousness_justification: str | None = None


class LandscapeResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    market_size: str
    growth_rate: str
    landscape_summary: str
    key_players: list[KeyPlayer] = Field(min_length=1)
    opportunities: list[LandscapeOpportunity] = Field(min_length=5)
    macro_trends: list[str] = Field(min_length=1)
    sources_consulted: list[str] = Field(min_length=3)


# ─────────────────────────────────────────────────────────────────────
# Step 1: deep_dive → DeepDiveResult
# ─────────────────────────────────────────────────────────────────────

NoCompetitorsClassification = Literal[
    "overlooked",
    "no_demand",
    "too_hard",
    "too_small",
]

DemandTier = Literal["HOT", "WARM", "COLD"]

# Used to be a Literal enum constrained to software billing models
# (subscription / usage / one_time / freemium / marketplace_take). That
# enum rejected valid non-software values like "wholesale", "retail_dtc",
# "retainer", "commission", "hardware_sale" — which broke every attempt
# to run the pipeline on a CPG, service, or capex-heavy domain. The
# prompt still lists the canonical software values as suggested
# vocabulary; the schema now accepts any short string so Claude can
# emit the shape of whatever domain it's actually researching.
BillingModel = str

GrossMarginSignal = Literal["high", "medium", "low"]

EvidenceStrength = Literal["strong", "moderate", "weak"]


class Competitor(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    funding: str
    founded: str
    status: str
    what_they_do: str


class MarketSizeEstimate(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str
    estimate: str
    year: str


class DemandSignal(BaseModel):
    model_config = ConfigDict(extra="allow")

    tier: DemandTier
    source: str
    signal: str


class UnitEconomics(BaseModel):
    model_config = ConfigDict(extra="allow")

    typical_price_point: str
    billing_model: str = Field(min_length=3, max_length=50)
    cac_channel: str
    gross_margin_signal: GrossMarginSignal


class DeepDiveOpportunity(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    description: str
    competitors: list[Competitor]
    no_competitors_classification: NoCompetitorsClassification | None = None
    no_competitors_evidence: str | None = None
    market_size_estimates: list[MarketSizeEstimate] = Field(min_length=1)
    demand_signals: list[DemandSignal] = Field(min_length=1)
    unit_economics: UnitEconomics
    # Round 3: founder/team patterns. Optional because legacy templates and
    # earlier in-flight workflows don't include it.
    founder_patterns: str | None = None
    early_failure_signal: str
    evidence_strength: EvidenceStrength
    initial_assessment: str


class DroppedOpportunity(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    reason: str


class DeepDiveResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    deep_dive_opportunities: list[DeepDiveOpportunity] = Field(min_length=3)
    dropped_opportunities: list[DroppedOpportunity] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────
# Step 2: contrarian_analysis → ContrarianResult
# ─────────────────────────────────────────────────────────────────────

KillProbability = Literal["low", "medium", "high"]

Verdict = Literal["survives", "weakened", "killed"]

ComplianceBurden = Literal["low", "medium", "high"]


class FailedPredecessor(BaseModel):
    model_config = ConfigDict(extra="allow")

    company: str
    year: str
    what_happened: str
    lesson: str


class IncumbentThreat(BaseModel):
    model_config = ConfigDict(extra="allow")

    incumbent: str
    evidence: str
    source: str


class RegulatoryRisk(BaseModel):
    model_config = ConfigDict(extra="allow")

    is_regulated_domain: bool
    regulatory_bodies: list[str] = Field(default_factory=list)
    specific_risks: list[str] = Field(default_factory=list)
    compliance_burden: ComplianceBurden


class ContrarianAnalysis(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    failed_predecessors: list[FailedPredecessor] = Field(default_factory=list)
    incumbent_threats: list[IncumbentThreat] = Field(default_factory=list)
    market_headwinds: list[str] = Field(default_factory=list)
    regulatory_risk: RegulatoryRisk
    technical_risks: list[str] = Field(default_factory=list)
    kill_scenario: str
    kill_probability: KillProbability
    verdict: Verdict
    verdict_reasoning: str


class ContrarianResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    contrarian_analyses: list[ContrarianAnalysis] = Field(min_length=3)
    summary: str


# ─────────────────────────────────────────────────────────────────────
# Step 3: synthesis_and_ranking → SynthesisResult
# ─────────────────────────────────────────────────────────────────────

class Scores(BaseModel):
    model_config = ConfigDict(extra="allow")

    market_timing: int = Field(ge=1, le=10)
    defensibility: int = Field(ge=1, le=10)
    solo_dev_feasibility: int = Field(ge=1, le=10)
    revenue_potential: int = Field(ge=1, le=10)
    evidence_quality: int = Field(ge=1, le=10)


class MoatDimension(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Integer 1-10. Previously a Literal["none","weak","strong"] which
    # capped defensibility at ~5 because the rubric flattened moderate
    # and strong moats into the same "weak" bucket. The 1-10 scale lets
    # a genuine distribution-lock or data-advantage moat score 7+ and
    # drive defensibility (and therefore total_score) above 70.
    rating: int = Field(ge=1, le=10)
    justification: str

    # Backward-compat: in-flight workflows whose prompt_template was
    # baked in under the old qualitative rubric will emit "none" / "weak"
    # / "strong". Map them to the corresponding integers on validation
    # so those runs still pass. Remove this coercion once all in-flight
    # workflows have drained (search for "MOAT_STRING_COMPAT" to find).
    @field_validator("rating", mode="before")
    @classmethod
    def _coerce_legacy_string_rating(cls, v):
        if isinstance(v, str):
            legacy_map = {"none": 1, "weak": 3, "strong": 7}
            return legacy_map.get(v.strip().lower(), v)
        return v


class Moats(BaseModel):
    model_config = ConfigDict(extra="allow")

    network_effects: MoatDimension
    switching_costs: MoatDimension
    data_advantage: MoatDimension
    brand_or_trust: MoatDimension
    distribution_lock: MoatDimension


class MvpSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Round 3: tightened min_length on critical free-text fields. The prompt
    # already asks Claude for substantive answers, but the schema previously
    # accepted empty strings — letting the builder receive a vague spec.
    what_to_build: str = Field(min_length=20)
    core_user_journey: str = Field(min_length=20)
    tech_stack: str = Field(min_length=3)
    build_time_weeks: int = Field(ge=1)
    first_customers: list[str] = Field(min_length=1)
    validation_approach: str = Field(min_length=15)
    out_of_scope: list[str] = Field(min_length=1)
    success_metric: str = Field(min_length=15)
    risky_assumption: str = Field(min_length=15)


class SynthesisRanking(BaseModel):
    model_config = ConfigDict(extra="allow")

    rank: int = Field(ge=1)
    name: str
    one_liner: str
    scores: Scores
    moats: Moats
    # Round 3: enforce a minimum quality bar on the weighted total. The
    # weighting formula has a theoretical max of 100; 20 is roughly "all
    # dimensions = 4/10". Anything below that means Claude couldn't find
    # a real opportunity and should retry rather than display garbage.
    total_score: float = Field(ge=20.0, le=100.0)
    head_to_head: str
    surviving_risks: list[str] = Field(default_factory=list)
    mvp_spec: MvpSpec


class SynthesisResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Round 3: bumped from 1 to 3. The prompt asks for top 5; allowing fewer
    # than 3 means contrarian killed too many ideas — that should trigger a
    # retry (or the recovery loop), not a half-empty approval gate.
    final_rankings: list[SynthesisRanking] = Field(min_length=3)
    executive_summary: str


# ─────────────────────────────────────────────────────────────────────
# Step 3 (new, Batch B): freshness_check → FreshnessResult
# ─────────────────────────────────────────────────────────────────────
# Narrow last-30-day incumbent-move scan over contrarian survivors.
# Feeds synthesis with STABLE / WEAKENED_FURTHER / KILLED_POST_CONTRARIAN
# flags so the ranking reflects what's true today, not what was true
# when landscape ran.

FreshnessStatus = Literal[
    "STABLE", "WEAKENED_FURTHER", "KILLED_POST_CONTRARIAN",
]


class FreshnessResultEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=2)
    status: FreshnessStatus
    # null is acceptable when STABLE. Non-STABLE entries MUST cite a
    # specific URL + date per the prompt's quality rule; we enforce
    # non-empty via a model_validator rather than Field(min_length)
    # because the field is allowed to be None for STABLE.
    evidence: str | None = None
    impact: str = Field(min_length=5)

    @model_validator(mode="after")
    def _non_stable_requires_evidence(self):
        if self.status != "STABLE" and (
            self.evidence is None or not self.evidence.strip()
        ):
            raise ValueError(
                f"{self.status} entries must cite specific evidence "
                "(URL + date); got an empty evidence field"
            )
        return self


class FreshnessResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Empty allowed: when contrarian's recovery loop is exhausted and
    # zero opportunities survived, freshness has nothing to scan and
    # should emit `[]` plus an explanatory scan_notes rather than
    # failing schema validation. Synthesis's existing min_length=3 on
    # final_rankings handles the "no viable wedge" terminal case
    # downstream, surfacing it as a clear synthesis failure with the
    # error message rather than a confusing freshness validation error.
    freshness_results: list[FreshnessResultEntry] = Field(default_factory=list)
    scan_notes: str = Field(min_length=10)


# ─────────────────────────────────────────────────────────────────────
# Step 5 (new, Batch B): validation_plan → ValidationPlanResult
# ─────────────────────────────────────────────────────────────────────
# 4-week pre-sale validation playbook for the top 3 ranked
# opportunities. Not fluff — the go_no_go_metric is the decision gate
# the founder uses to commit to (or drop) a build.


class ValidationOutreachTarget(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=2)
    why_them: str = Field(min_length=10)
    reachable_via: str = Field(min_length=5)


class ValidationPlan(BaseModel):
    model_config = ConfigDict(extra="allow")

    rank: int = Field(ge=1)
    name: str = Field(min_length=2)
    # The prompt asks for 5-10 specific targets. min_length=3 is a soft
    # floor that still fails clearly when Claude lists "CPAs" as a
    # single target instead of naming firms.
    specific_outreach_targets: list[ValidationOutreachTarget] = Field(
        min_length=3, max_length=15
    )
    contact_channel: str = Field(min_length=5)
    # Cold message anchor: 80-150 words in the prompt. Enforce a
    # minimum character floor that roughly corresponds to 80 words
    # (avg ~5 chars/word including spaces → ~400 chars). Cap at 1500
    # to catch the "wall of text" failure mode.
    cold_message_script: str = Field(min_length=300, max_length=1500)
    disqualification_criteria: list[str] = Field(min_length=2, max_length=5)
    go_no_go_metric: str = Field(min_length=15)
    expected_signal_timeline: str = Field(min_length=40)


class ValidationPlanResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Prompt asks for top 3. Allow 2-5 to absorb edge cases where
    # synthesis surfaced exactly 3 but one was clearly weak, or where
    # deep_research_mode produced 7 rankings and the top 5 all deserve
    # a plan. Fewer than 2 means something went wrong upstream.
    validation_plans: list[ValidationPlan] = Field(min_length=2, max_length=5)
    cross_cutting_notes: str = Field(min_length=10)


# ─────────────────────────────────────────────────────────────────────
# Side hustle pipeline schemas (Round 2)
# ─────────────────────────────────────────────────────────────────────
#
# Schemas mirror the JSON contracts in the 4 research prompts defined
# in SIDE_HUSTLE_PIPELINE in app/workflows/templates.py. Every model
# uses ConfigDict(extra="allow") so prompt-level field additions don't
# break in-flight workflows; critical lists use min_length to catch
# silent empty-array failures.
#
# Names are prefixed with ``SideHustle`` to avoid collisions with the
# startup pipeline schemas, which reuse some bare names like Scores,
# FailedPredecessor, and EvidenceStrength.


# Reusing the TimingSignalType literal from the startup pipeline
# (same 6 categories). If the two pipelines ever need to diverge, this
# can be split into its own literal.


SideHustleSourceType = Literal[
    "stripe_screenshot",
    "indie_hackers_mrr",
    "reddit_with_proof",
    "youtube_dashboard",
    "other",
]


AutomationRealnessCheck = Literal[
    "fully_automated",
    "mostly_automated_monitoring",
    "manual_with_assist",
    "fake_automation",
]


# ─────────────────────────────────────────────────────────────────────
# Step 0 side hustle: research_side_hustles → SideHustleResearchResult
# ─────────────────────────────────────────────────────────────────────


class SideHustleIncomeEvidence(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_url: str = Field(min_length=5)
    source_type: SideHustleSourceType
    claimed_income: str = Field(min_length=3)


class SideHustleOpportunity(BaseModel):
    model_config = ConfigDict(extra="allow")

    # max_length=200 is a loose cap to catch absurdly long "names" that
    # would indicate Claude confused the name field with a description.
    # Tight enough to reject garbage, loose enough to not trip the
    # prompt-schema alignment test's placeholder string.
    name: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=20)
    automation_approach: str = Field(min_length=15)
    timing_signal_type: TimingSignalType
    timing_signal: str = Field(min_length=10)
    income_evidence: SideHustleIncomeEvidence
    income_range: str = Field(min_length=3)
    tools_needed: list[str] = Field(min_length=1)
    non_obviousness_check: Literal["yes", "no"]
    # The prompt says this field is required only when
    # ``non_obviousness_check == "yes"`` (to justify including an
    # otherwise obvious idea). A plain Field declaration can't encode
    # that conditional requirement, so Round 5.A1 adds a model-level
    # validator that enforces it after all field validation runs.
    non_obviousness_justification: str | None = None
    automation_realness_check: AutomationRealnessCheck

    @model_validator(mode="after")
    def _require_justification_when_obvious(self) -> "SideHustleOpportunity":
        """Round 5.A1: when ``non_obviousness_check == "yes"``, the
        prompt requires a non-empty ``non_obviousness_justification``
        explaining why to include an obvious idea (or the idea should
        be dropped and replaced). Without this validator the schema
        silently accepted a ``check="yes"`` opportunity with
        ``justification=None``, letting unjustified obvious ideas
        slip through into downstream steps.
        """
        if self.non_obviousness_check == "yes":
            justification = self.non_obviousness_justification
            if not justification or not justification.strip():
                raise ValueError(
                    "non_obviousness_justification is required when "
                    "non_obviousness_check is 'yes' — the prompt asks "
                    "Claude to either justify why to include an "
                    "obvious idea or drop it and replace with "
                    "something fresher."
                )
        return self


class SideHustleResearchResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Prompt asks for 6-8 opportunities (8-10 in deep mode). min_length=5
    # leaves slack for Claude rounding down while still catching a
    # silent empty-array failure.
    opportunities: list[SideHustleOpportunity] = Field(min_length=5)
    sources_consulted: list[str] = Field(min_length=3)


# ─────────────────────────────────────────────────────────────────────
# Step 1 side hustle: evaluate_feasibility → SideHustleFeasibilityResult
# ─────────────────────────────────────────────────────────────────────


# Same rationale as BillingModel: these enums rejected valid labels
# the moment the pipeline ran outside its original SaaS/consumer-n8n
# sweet spot. N8nNodeAvailability broke on a specialty-food-distributor
# run when Claude classified a node as "community" / "third_party" /
# "paid_add_on" instead of the 4 canonical buckets. LegalComplianceCategory
# was built for consumer-side-hustle TOS/CFAA/FTC/GDPR, but
# food-distribution sits squarely on FDA_LABELING / HACCP / USDA_MEAT /
# ALLERGEN_DISCLOSURE, and insurance sits on STATE_INSURANCE_LICENSE /
# RESPA / TCPA. Both now accept any short string; the prompts still
# document the canonical vocabulary as soft guidance.
N8nNodeAvailability = str
LegalComplianceCategory = str


class SideHustleScores(BaseModel):
    """Six feasibility dimensions from the Round 1 score-anchor prompt.

    Each score is an integer 1-10. The anchors in the prompt define
    what each value means; the synthesis step later applies weights.
    """

    model_config = ConfigDict(extra="allow")

    revenue_potential: int = Field(ge=1, le=10)
    n8n_specific_feasibility: int = Field(ge=1, le=10)
    time_to_first_dollar: int = Field(ge=1, le=10)
    maintenance_effort: int = Field(ge=1, le=10)
    legal_safety: int = Field(ge=1, le=10)
    scalability: int = Field(ge=1, le=10)


class N8nNodeInventoryEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    node: str = Field(min_length=3)
    availability: str = Field(min_length=3, max_length=50)
    notes: str | None = None


class SideHustleLegalRisk(BaseModel):
    model_config = ConfigDict(extra="allow")

    category: str = Field(min_length=3)
    regulator_or_platform: str = Field(min_length=2)
    recent_enforcement: str = Field(min_length=10)
    source: str = Field(min_length=5)


class SideHustleLegalChecklist(BaseModel):
    model_config = ConfigDict(extra="allow")

    compliance_categories: list[LegalComplianceCategory] = Field(default_factory=list)
    specific_risks: list[SideHustleLegalRisk] = Field(default_factory=list)


class SideHustleEvaluation(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=2)
    scores: SideHustleScores
    total_score: int = Field(ge=6, le=60)
    n8n_node_inventory: list[N8nNodeInventoryEntry] = Field(min_length=1)
    legal_checklist: SideHustleLegalChecklist
    monthly_costs: str = Field(min_length=3)
    automation_bottleneck: str = Field(min_length=10)
    verdict: str = Field(min_length=15)


class SideHustleFeasibilityResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Research produces 10-12 opportunities, but evaluate_feasibility
    # caps at the top 8 to stay within Claude's per-response output
    # budget. Some of those 8 may be dropped (automation_realness_check
    # was fake_automation but snuck through). Set min_length=3 so the
    # contrarian step has enough to work with.
    evaluations: list[SideHustleEvaluation] = Field(min_length=3)


# ─────────────────────────────────────────────────────────────────────
# Step 2 side hustle: contrarian_analysis → SideHustleContrarianResult
# ─────────────────────────────────────────────────────────────────────


SaturationLevel = Literal["low", "medium", "high"]


class SideHustleFailedPredecessor(BaseModel):
    """Named predecessor who tried this hustle and failed.

    Round 1 prompt requires name + year + reason + source URL; all are
    mandatory here. Vague claims like "many people failed" don't satisfy
    this schema.

    Round 6 followup: relaxed min_length on year and source. Claude
    sometimes writes "N/A" or "unknown" when it genuinely can't find
    the year a predecessor shut down or can't locate a URL. Failing
    the entire contrarian analysis over one predecessor's missing
    year is worse than accepting "N/A" and letting the verdict
    reasoning explain the gap.
    """

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=2)
    year: str = Field(min_length=1)
    reason: str = Field(min_length=5)
    source: str = Field(min_length=1)


class PlatformCrackdown(BaseModel):
    model_config = ConfigDict(extra="allow")

    platform: str = Field(min_length=2)
    action: str = Field(min_length=3)
    when: str = Field(min_length=1)
    source: str = Field(min_length=1)


class Saturation(BaseModel):
    model_config = ConfigDict(extra="allow")

    search_summary: str = Field(min_length=15)
    saturation_level: SaturationLevel


class IncomeReality(BaseModel):
    model_config = ConfigDict(extra="allow")

    primary_source_links: list[str] = Field(default_factory=list)
    typical_reported_income: str = Field(min_length=3)
    evidence_strength: EvidenceStrength


class FailureStory(BaseModel):
    model_config = ConfigDict(extra="allow")

    quit_reason: str = Field(min_length=3)
    source: str = Field(min_length=1)


class SideHustleContrarianAnalysis(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=2)
    failed_predecessors: list[SideHustleFailedPredecessor] = Field(default_factory=list)
    platform_dependency: str = Field(min_length=2)
    platform_crackdown_evidence: list[PlatformCrackdown] = Field(default_factory=list)
    saturation: Saturation
    income_reality: IncomeReality
    failure_stories: list[FailureStory] = Field(default_factory=list)
    kill_scenario: str = Field(min_length=15)
    kill_probability: KillProbability
    verdict: Verdict
    verdict_reasoning: str = Field(min_length=30)


class SideHustleContrarianResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Round 5.A2: lowered from 5 to 3. The contrarian prompt instructs
    # Claude to "kill at least 30%" of incoming opportunities, and
    # feasibility itself has min_length=5. A run where feasibility
    # outputs exactly 5 evaluations and contrarian kills 2 leaves 3
    # survivors — which previously failed schema validation and
    # triggered pointless retries. Matches the startup pipeline's
    # ContrarianResult min_length=3.
    analyses: list[SideHustleContrarianAnalysis] = Field(min_length=3)
    summary: str = Field(min_length=30)


# ─────────────────────────────────────────────────────────────────────
# Step 3 side hustle: synthesis_and_ranking → SideHustleSynthesisResult
# ─────────────────────────────────────────────────────────────────────


SideHustleContrarianVerdict = Literal["survives", "weakened"]


class NodeGraphEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    node: str = Field(min_length=3)
    role: str = Field(min_length=3)


class SideHustleWorkflowSpec(BaseModel):
    """All 8 required fields from the Round 1 synthesis prompt.

    Round 4 made the build step mandate a Webhook trigger (not
    Schedule/Manual) because the test_run step triggers via webhook.
    The spec here enforces the same by requiring trigger_node to be
    a free-text field that the build prompt cross-checks.
    """

    model_config = ConfigDict(extra="allow")

    trigger_node: str = Field(min_length=10)
    node_graph: list[NodeGraphEntry] = Field(min_length=2)
    external_credentials: list[str] = Field(default_factory=list)
    expected_runtime: str = Field(min_length=3)
    frequency: str = Field(min_length=5)
    # Round 1 prompt says "exactly 3 features" for out_of_scope.
    # Enforce that strictly here. If Claude chronically violates,
    # relax to min_length=2, max_length=5 in a hotfix.
    out_of_scope: list[str] = Field(min_length=3, max_length=3)
    success_metric: str = Field(min_length=15)
    risky_assumption: str = Field(min_length=15)


class SideHustleRanking(BaseModel):
    model_config = ConfigDict(extra="allow")

    rank: int = Field(ge=1)
    name: str = Field(min_length=2)
    one_liner: str = Field(min_length=10)
    monthly_income_estimate: str = Field(min_length=3)
    monthly_costs: str = Field(min_length=3)
    contrarian_verdict: SideHustleContrarianVerdict
    # Raw weighted sum before contrarian adjustment. With weights summing
    # to 10.0 across six 1-10 dimensions, max possible is 100 (all 10s),
    # realistic surviving range ~55-80.
    raw_score: float = Field(ge=10.0, le=100.0)
    # Adjusted total after contrarian weighting (×0.8 for 'weakened').
    # Min 8.0 = all-ones * 0.8; max 100.0 ('survives' unchanged).
    total_score: float = Field(ge=8.0, le=100.0)
    head_to_head: str = Field(min_length=15)
    surviving_risks: list[str] = Field(default_factory=list)
    n8n_workflow_spec: SideHustleWorkflowSpec


class SideHustleSynthesisResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Round 1 prompt says top 5 (or fewer if fewer survived). min 2
    # catches the "everything got killed" case; max 7 catches the
    # "Claude ignored the instruction and produced 20" case.
    final_rankings: list[SideHustleRanking] = Field(min_length=2, max_length=7)
    executive_summary: str = Field(min_length=100)


# ─────────────────────────────────────────────────────────────────────
# Apartment search pipeline → ApartmentSynthesisResult
# ─────────────────────────────────────────────────────────────────────

ApartmentSource = Literal[
    # Primary Tier 1 sources (proven WebFetch)
    "craigslist",
    "redfin",
    "zumper",
    "padmapper",
    # Direct landlord / property mgmt (Tier 2)
    "avalonbay",
    "equity_residential",
    "camden",
    "greystar",
    "udr",
    "vanguard",
    "climb",
    "compass",
    # Alt aggregators (Tier 3)
    "rentjungle",
    "forrent",
    "realtor_com",
    "lovely",
    # WebSearch-only / community (Tier 4-5)
    "hotpads",
    "zillow",
    "apartments_com",
    "trulia",
    "rent_com",
    "streeteasy",
    "reddit",
    "twitter",
    "facebook_marketplace",
    "other",
]


class ApartmentScoreBreakdown(BaseModel):
    """Per-criterion score for transparency. 0-100 each; total_score is
    a weighted sum reported by Claude.

    Weights baked into the prompt:
      neighborhood 25, bike_time 20, value (rent vs sqft) 15,
      size 10, amenities 15, vibe 15.
    """

    model_config = ConfigDict(extra="allow")

    neighborhood: float = Field(ge=0, le=100)
    bike_time: float = Field(ge=0, le=100)
    value: float = Field(ge=0, le=100)
    size: float = Field(ge=0, le=100)
    amenities: float = Field(ge=0, le=100)
    vibe: float = Field(ge=0, le=100)


class ApartmentListing(BaseModel):
    """Canonical apartment listing shape returned by the scan_and_rank
    step and persisted to apartment_listings.

    Some fields are intentionally optional — listing pages vary in
    quality. Rent and beds are the only hard filters Claude is told
    not to violate; everything else is best-effort.

    Round 2 (multi-source dedup): the canonical_*, unit, building_name,
    latitude/longitude, and photo_fingerprint_hint fields feed the
    Python dedup logic in apartments_persist._compute_group_id. Claude
    should fill as many as it can extract; missing fields drop the
    listing down the tiered match rule (address → addr+rent+beds →
    coords → URL fallback)."""

    model_config = ConfigDict(extra="allow")

    source: ApartmentSource
    url: str = Field(min_length=10)
    title: str = Field(min_length=3)
    neighborhood: str | None = None
    address: str | None = None
    rent_usd: int = Field(ge=500, le=15000)
    beds: int = Field(ge=1, le=6)
    baths: float = Field(ge=0.5, le=6)
    sqft: int | None = Field(default=None, ge=200, le=5000)
    bike_time_min: int | None = Field(default=None, ge=1, le=120)
    score: float = Field(ge=0, le=100)
    score_breakdown: ApartmentScoreBreakdown
    amenities: list[str] = Field(default_factory=list)
    photos: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=20)
    has_kitchen: bool = True
    notify_worthy: bool = False
    """Claude flags a listing notify_worthy when it scores >=80 AND
    meets every hard requirement (2BR+, kitchen, sqft, rent cap, bike
    time, target neighborhood). The persist job only emails on new
    listings with notify_worthy=true."""

    # ── Dedup signals (multi-source) ─────────────────────────────────
    canonical_address: str | None = None
    """Normalized street address, no unit. E.g. '1650 Clay St'. Gold
    signal for the dedup grouping function."""

    unit: str | None = None
    """Unit / apartment / suite number when visible. Combined with
    canonical_address for the highest-confidence merge key."""

    building_name: str | None = None
    """Named buildings (AvalonBay, NEMA, etc.) where applicable.
    Used as a soft signal when address is hidden."""

    latitude: float | None = Field(default=None, ge=37.6, le=37.9)
    longitude: float | None = Field(default=None, ge=-122.55, le=-122.35)
    """SF-area sanity range. Used in the tiered match when address is
    missing — coords rounded to 4 decimal places (~11m) act as the
    bucket key."""

    photo_fingerprint_hint: str | None = None
    """Short string Claude emits when it recognizes the lead photo as
    identical to another listing's lead photo. NOT a real perceptual
    hash — a human-readable hint like 'identical hero photo to listing
    X' that flags potential cross-posts. Used as a tiebreaker only."""

    also_listed_on: list[str] = Field(default_factory=list)
    """Advisory hint Claude can use to flag suspected crossposts. Every
    URL still ships as its own record (so the API can show them all
    under one canonical group via the deterministic listing_group_id);
    this field is informational and does NOT cause any merging on
    its own. The Python persist step's compute_group_id is the only
    code that actually collapses records."""


class ApartmentSynthesisResult(BaseModel):
    """Output of the scan_and_rank step. Top matches ranked desc by score."""

    model_config = ConfigDict(extra="allow")

    top_matches: list[ApartmentListing] = Field(default_factory=list, max_length=40)
    # sources_scanned is purely informational (shown in scan_summary
    # display). Was originally typed list[ApartmentSource] but that
    # caused workflow failures the moment Claude tried a source we
    # hadn't yet added to the Literal enum (e.g., overnight iteration
    # added avalonbay/rentjungle/etc. via the prompt but forgot the
    # schema update). Free-form str is safer — the actual gate on
    # emitted listings is ApartmentListing.source, which stays
    # constrained for iOS rendering.
    sources_scanned: list[str] = Field(min_length=1)
    scan_summary: str = Field(min_length=20)


# ─────────────────────────────────────────────────────────────────────
# Registry — looked up by name from StepDefinition.output_schema
# ─────────────────────────────────────────────────────────────────────

STEP_OUTPUT_SCHEMAS: dict[str, type[BaseModel]] = {
    "startup_landscape_v1": LandscapeResult,
    "startup_deep_dive_v1": DeepDiveResult,
    "startup_contrarian_v1": ContrarianResult,
    "startup_freshness_v1": FreshnessResult,
    "startup_synthesis_v1": SynthesisResult,
    "startup_validation_v1": ValidationPlanResult,
    # Round 2 side hustle additions
    "side_hustle_research_v1": SideHustleResearchResult,
    "side_hustle_feasibility_v1": SideHustleFeasibilityResult,
    "side_hustle_contrarian_v1": SideHustleContrarianResult,
    "side_hustle_synthesis_v1": SideHustleSynthesisResult,
    # Apartment search pipeline
    "apartment_synthesis_v1": ApartmentSynthesisResult,
}


def get_schema(name: str | None) -> type[BaseModel] | None:
    """Look up a schema by name. Returns None if name is None or unknown."""
    if name is None:
        return None
    return STEP_OUTPUT_SCHEMAS.get(name)
