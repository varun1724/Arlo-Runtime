from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ResearchOpportunity(BaseModel):
    name: str
    description: str
    evidence: list[str]
    market_size_estimate: str
    competition_level: Literal["low", "medium", "high"]
    feasibility: Literal["low", "medium", "high"]


class ResearchRecommendation(BaseModel):
    name: str
    reasoning: str


class ResearchReport(BaseModel):
    market_overview: str
    opportunities: list[ResearchOpportunity]
    trends: list[str]
    risks: list[str]
    top_recommendations: list[ResearchRecommendation]
