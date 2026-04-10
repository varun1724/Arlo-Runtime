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
# Registry — looked up by name from StepDefinition.output_schema
# ─────────────────────────────────────────────────────────────────────

STEP_OUTPUT_SCHEMAS: dict[str, type[BaseModel]] = {
    "startup_landscape_v1": LandscapeResult,
    "startup_deep_dive_v1": DeepDiveResult,
    "startup_contrarian_v1": ContrarianResult,
    "startup_synthesis_v1": SynthesisResult,
}


def get_schema(name: str | None) -> type[BaseModel] | None:
    """Look up a schema by name. Returns None if name is None or unknown."""
    if name is None:
        return None
    return STEP_OUTPUT_SCHEMAS.get(name)
