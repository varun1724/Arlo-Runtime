import json

import pytest

from app.models.research import ResearchReport


SAMPLE_REPORT = {
    "market_overview": "The pet tech market is valued at $8B and growing at 15% CAGR.",
    "opportunities": [
        {
            "name": "AI-powered pet health monitoring",
            "description": "Wearable devices that track pet vitals and predict health issues.",
            "evidence": [
                "PetPace raised $10M in 2024",
                "Whistle acquired for $117M",
            ],
            "market_size_estimate": "$2.1B by 2027",
            "competition_level": "medium",
            "feasibility": "high",
        }
    ],
    "trends": [
        "Humanization of pets driving premium spending",
        "Telehealth for veterinary care",
    ],
    "risks": [
        "High customer acquisition costs",
        "Regulatory uncertainty for pet health devices",
    ],
    "top_recommendations": [
        {
            "name": "AI-powered pet health monitoring",
            "reasoning": "Large addressable market with proven exits and medium competition.",
        }
    ],
}


@pytest.mark.asyncio
async def test_research_report_parses():
    report = ResearchReport.model_validate(SAMPLE_REPORT)
    assert report.market_overview.startswith("The pet tech")
    assert len(report.opportunities) == 1
    assert report.opportunities[0].competition_level == "medium"
    assert len(report.top_recommendations) == 1


@pytest.mark.asyncio
async def test_research_report_roundtrips_json():
    report = ResearchReport.model_validate(SAMPLE_REPORT)
    json_str = report.model_dump_json()
    parsed = ResearchReport.model_validate_json(json_str)
    assert parsed == report


@pytest.mark.asyncio
async def test_research_report_rejects_invalid():
    with pytest.raises(Exception):
        ResearchReport.model_validate({"market_overview": "test"})
