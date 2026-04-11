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

from pydantic import BaseModel, ConfigDict, Field

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

BillingModel = Literal[
    "subscription",
    "usage",
    "one_time",
    "freemium",
    "marketplace_take",
]

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
    billing_model: BillingModel
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

MoatRating = Literal["none", "weak", "strong"]


class Scores(BaseModel):
    model_config = ConfigDict(extra="allow")

    market_timing: int = Field(ge=1, le=10)
    defensibility: int = Field(ge=1, le=10)
    solo_dev_feasibility: int = Field(ge=1, le=10)
    revenue_potential: int = Field(ge=1, le=10)
    evidence_quality: int = Field(ge=1, le=10)


class MoatDimension(BaseModel):
    model_config = ConfigDict(extra="allow")

    rating: MoatRating
    justification: str


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
    # Prompt says only required when non_obviousness_check == "yes";
    # schema can't express that cleanly without a validator so we accept
    # either. Tests verify the field exists when required.
    non_obviousness_justification: str | None = None
    automation_realness_check: AutomationRealnessCheck


class SideHustleResearchResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Round 1 prompt asks for 10-12 opportunities. min_length=8 leaves
    # slack for Claude rounding down while still catching a silent
    # empty-array failure. Can be tuned down to 5 in a hotfix if
    # production runs show 8 is too strict.
    opportunities: list[SideHustleOpportunity] = Field(min_length=8)
    sources_consulted: list[str] = Field(min_length=3)


# ─────────────────────────────────────────────────────────────────────
# Step 1 side hustle: evaluate_feasibility → SideHustleFeasibilityResult
# ─────────────────────────────────────────────────────────────────────


N8nNodeAvailability = Literal[
    "built_in",
    "first_party",
    "community_package",
    "custom_code",
]


LegalComplianceCategory = Literal[
    "PLATFORM_TOS",
    "CFAA",
    "FTC_AFFILIATE",
    "CAN_SPAM",
    "GDPR",
    "STATE_BUSINESS_LICENSE",
    "TAX_THRESHOLD",
]


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
    availability: N8nNodeAvailability
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

    # Research produces 10-12 opportunities with min_length=8, but some
    # may be dropped in feasibility (e.g. automation_realness_check was
    # fake_automation but snuck through). Set min_length=5 so the
    # contrarian step has enough to work with.
    evaluations: list[SideHustleEvaluation] = Field(min_length=5)


# ─────────────────────────────────────────────────────────────────────
# Step 2 side hustle: contrarian_analysis → SideHustleContrarianResult
# ─────────────────────────────────────────────────────────────────────


SaturationLevel = Literal["low", "medium", "high"]


class SideHustleFailedPredecessor(BaseModel):
    """Named predecessor who tried this hustle and failed.

    Round 1 prompt requires name + year + reason + source URL; all are
    mandatory here. Vague claims like "many people failed" don't satisfy
    this schema.
    """

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=2)
    year: str = Field(min_length=4)
    reason: str = Field(min_length=10)
    source: str = Field(min_length=5)


class PlatformCrackdown(BaseModel):
    model_config = ConfigDict(extra="allow")

    platform: str = Field(min_length=2)
    action: str = Field(min_length=5)
    when: str = Field(min_length=4)
    source: str = Field(min_length=5)


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

    quit_reason: str = Field(min_length=10)
    source: str = Field(min_length=5)


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

    # Same rationale as feasibility — need enough survivors for
    # synthesis to make a meaningful ranking.
    analyses: list[SideHustleContrarianAnalysis] = Field(min_length=5)
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
    # Raw weighted sum before contrarian adjustment. Max possible per
    # the Round 1 formula is 65 (all 10s), realistic range ~20-55.
    raw_score: float = Field(ge=6.0, le=65.0)
    # Adjusted total after contrarian weighting (×0.8 for 'weakened').
    # Min 4.8 = all-ones * 0.8; max 65.0.
    total_score: float = Field(ge=4.8, le=65.0)
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
# Registry — looked up by name from StepDefinition.output_schema
# ─────────────────────────────────────────────────────────────────────

STEP_OUTPUT_SCHEMAS: dict[str, type[BaseModel]] = {
    "startup_landscape_v1": LandscapeResult,
    "startup_deep_dive_v1": DeepDiveResult,
    "startup_contrarian_v1": ContrarianResult,
    "startup_synthesis_v1": SynthesisResult,
    # Round 2 side hustle additions
    "side_hustle_research_v1": SideHustleResearchResult,
    "side_hustle_feasibility_v1": SideHustleFeasibilityResult,
    "side_hustle_contrarian_v1": SideHustleContrarianResult,
    "side_hustle_synthesis_v1": SideHustleSynthesisResult,
}


def get_schema(name: str | None) -> type[BaseModel] | None:
    """Look up a schema by name. Returns None if name is None or unknown."""
    if name is None:
        return None
    return STEP_OUTPUT_SCHEMAS.get(name)
