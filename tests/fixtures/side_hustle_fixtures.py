"""Golden sample outputs for each step of the side_hustle_pipeline.

Round 2: mirror of tests/fixtures/startup_pipeline_fixtures.py for
the side hustle research steps. Serves two purposes:

1. **Contract fixtures**: VALID_SIDE_HUSTLE_* is what a healthy Claude
   output looks like. Future prompt edits must keep producing JSON
   that matches this shape, enforced via
   tests/test_side_hustle_prompt_alignment.py.

2. **Test inputs**: MINIMAL_* is the smallest legal JSON that passes
   every min_length/required-field check. INVALID_* are purposeful
   negative cases that each exercise a specific rejection path.

All fixture dicts live at module level so tests can import them
directly. Factory helpers (_minimal_*) build minimally-valid
sub-objects that callers can tile with ``[_minimal_foo(i) for i in
range(N)]`` to hit schema min_length constraints without copy-paste.
"""

from __future__ import annotations

from typing import Any


# ─────────────────────────────────────────────────────────────────────
# Factory helpers
# ─────────────────────────────────────────────────────────────────────


def _minimal_income_evidence() -> dict[str, Any]:
    return {
        "source_url": "https://indiehackers.com/post/example-mrr-page",
        "source_type": "indie_hackers_mrr",
        "claimed_income": "$1,200/mo",
    }


def _minimal_opportunity(name: str = "Minimal Opportunity") -> dict[str, Any]:
    return {
        "name": name,
        "description": "A minimal side hustle with a short description field.",
        "automation_approach": "Use n8n HTTP Request node",
        "timing_signal_type": "TECHNOLOGY_UNLOCK",
        "timing_signal": "An API became available in early 2025",
        "income_evidence": _minimal_income_evidence(),
        "income_range": "$100-500/mo",
        "tools_needed": ["Some API"],
        "non_obviousness_check": "no",
        "automation_realness_check": "fully_automated",
    }


def _minimal_scores() -> dict[str, int]:
    return {
        "revenue_potential": 5,
        "n8n_specific_feasibility": 5,
        "time_to_first_dollar": 5,
        "maintenance_effort": 5,
        "legal_safety": 5,
        "scalability": 5,
    }


def _minimal_node_inventory_entry() -> dict[str, Any]:
    return {
        "node": "n8n-nodes-base.httpRequest",
        "availability": "built_in",
        "notes": None,
    }


def _minimal_legal_checklist() -> dict[str, Any]:
    return {
        "compliance_categories": [],
        "specific_risks": [],
    }


def _minimal_evaluation(name: str = "Minimal Evaluation") -> dict[str, Any]:
    return {
        "name": name,
        "scores": _minimal_scores(),
        "total_score": 30,
        "n8n_node_inventory": [_minimal_node_inventory_entry()],
        "legal_checklist": _minimal_legal_checklist(),
        "monthly_costs": "$0-20",
        "automation_bottleneck": "Rate limits on the upstream API",
        "verdict": "Viable with low setup cost; revenue uncertain.",
    }


def _minimal_saturation() -> dict[str, Any]:
    return {
        "search_summary": "Approximately 12 YouTube tutorials in last 6 months",
        "saturation_level": "medium",
    }


def _minimal_income_reality() -> dict[str, Any]:
    return {
        "primary_source_links": [],
        "typical_reported_income": "~$500/mo",
        "evidence_strength": "moderate",
    }


def _minimal_contrarian_analysis(name: str = "Minimal Hustle") -> dict[str, Any]:
    return {
        "name": name,
        "failed_predecessors": [],
        "platform_dependency": "none",
        "platform_crackdown_evidence": [],
        "saturation": _minimal_saturation(),
        "income_reality": _minimal_income_reality(),
        "failure_stories": [],
        "kill_scenario": "Market dries up as incumbents add the feature natively.",
        "kill_probability": "low",
        "verdict": "survives",
        "verdict_reasoning": (
            "Low platform dependency means incumbent risk is manageable. "
            "Verdict: survives."
        ),
    }


def _minimal_workflow_spec() -> dict[str, Any]:
    return {
        "trigger_node": "n8n-nodes-base.webhook with path: 'minimal'",
        "node_graph": [
            {"node": "n8n-nodes-base.webhook", "role": "trigger"},
            {"node": "n8n-nodes-base.set", "role": "echo response"},
        ],
        "external_credentials": [],
        "expected_runtime": "1-3 seconds",
        "frequency": "on-demand via webhook",
        "out_of_scope": [
            "database persistence",
            "multi-user auth",
            "analytics dashboard",
        ],
        "success_metric": "At least 1 successful webhook invocation per day",
        "risky_assumption": (
            "Webhook trigger latency stays under 2 seconds at expected volume"
        ),
    }


def _minimal_ranking(rank: int = 1, name: str = "Minimal Pick") -> dict[str, Any]:
    return {
        "rank": rank,
        "name": name,
        "one_liner": "A minimal side hustle pick",
        "monthly_income_estimate": "$500-1000",
        "monthly_costs": "$0-20",
        "contrarian_verdict": "survives",
        "raw_score": 30.0,
        "total_score": 30.0,
        "head_to_head": "Beats next by having lower setup cost.",
        "surviving_risks": [],
        "n8n_workflow_spec": _minimal_workflow_spec(),
    }


# ─────────────────────────────────────────────────────────────────────
# Step 0: research_side_hustles
# ─────────────────────────────────────────────────────────────────────

VALID_SIDE_HUSTLE_RESEARCH: dict = {
    "opportunities": [
        {
            "name": "Reddit Niche Deal Scanner",
            "description": (
                "Scrapes specific subreddits for deal posts, filters them by "
                "category and price threshold, and posts matching items to a "
                "paid Discord or Slack channel run by the operator."
            ),
            "automation_approach": (
                "n8n Schedule Trigger every 15 min → Reddit API (Pushshift) → "
                "IF node filters → Discord webhook post"
            ),
            "timing_signal_type": "DISTRIBUTION_UNLOCK",
            "timing_signal": (
                "Reddit's new API pricing (2023) killed free third-party "
                "scrapers, creating a gap for paid curated feeds. Source: "
                "TechCrunch July 2023."
            ),
            "income_evidence": {
                "source_url": "https://indiehackers.com/post/deal-scanner-mrr",
                "source_type": "indie_hackers_mrr",
                "claimed_income": "$1,400 MRR",
            },
            "income_range": "$500-2,000/mo",
            "tools_needed": ["Reddit API key", "Discord webhook", "Cloud VM"],
            "non_obviousness_check": "no",
            "automation_realness_check": "fully_automated",
        },
        {
            "name": "Creator AI Brand Monitor",
            "description": (
                "Watches Twitter/X and TikTok for mentions of specific "
                "creators by name, detects negative sentiment spikes, and "
                "alerts them in real time via a paid subscription service."
            ),
            "automation_approach": (
                "n8n Webhook receives social stream → Code node runs "
                "sentiment analysis → IF node triggers email/SMS alert"
            ),
            "timing_signal_type": "COST_COLLAPSE",
            "timing_signal": (
                "OpenAI API pricing dropped 80% in late 2024, making "
                "real-time sentiment analysis economically viable for "
                "creators under 100K followers. Source: OpenAI pricing update."
            ),
            "income_evidence": {
                "source_url": "https://twitter.com/example/status/123",
                "source_type": "stripe_screenshot",
                "claimed_income": "$2,100/mo",
            },
            "income_range": "$800-3,500/mo",
            "tools_needed": ["OpenAI API", "TwitterAPI.io", "Stripe"],
            "non_obviousness_check": "no",
            "automation_realness_check": "mostly_automated_monitoring",
        },
        *[_minimal_opportunity(f"Opportunity {i}") for i in range(8)],
    ],
    "sources_consulted": [
        "IndieHackers public MRR pages",
        "r/SideProject revenue screenshots",
        "Product Hunt launches last 90 days",
        "Hacker News Show HN threads",
    ],
}

MINIMAL_SIDE_HUSTLE_RESEARCH: dict = {
    "opportunities": [_minimal_opportunity(f"Opp {i}") for i in range(8)],
    "sources_consulted": ["source 1", "source 2", "source 3"],
}

INVALID_RESEARCH_FEW_OPPS: dict = {
    "opportunities": [_minimal_opportunity(f"Opp {i}") for i in range(5)],
    "sources_consulted": ["source 1", "source 2", "source 3"],
}

INVALID_RESEARCH_MISSING_FIELD: dict = {
    "opportunities": [
        {
            # missing: income_evidence
            "name": "Missing Fields",
            "description": "Opportunity missing the income_evidence field.",
            "automation_approach": "n8n HTTP Request",
            "timing_signal_type": "TECHNOLOGY_UNLOCK",
            "timing_signal": "A thing happened",
            "income_range": "$100-500/mo",
            "tools_needed": ["Some API"],
            "non_obviousness_check": "no",
            "automation_realness_check": "fully_automated",
        },
        *[_minimal_opportunity(f"Opp {i}") for i in range(7)],
    ],
    "sources_consulted": ["source 1", "source 2", "source 3"],
}

INVALID_RESEARCH_BAD_TIMING_TYPE: dict = {
    "opportunities": [
        {
            **_minimal_opportunity("Bad Timing"),
            "timing_signal_type": "NOT_A_REAL_CATEGORY",
        },
        *[_minimal_opportunity(f"Opp {i}") for i in range(7)],
    ],
    "sources_consulted": ["source 1", "source 2", "source 3"],
}


# ─────────────────────────────────────────────────────────────────────
# Step 1: evaluate_feasibility
# ─────────────────────────────────────────────────────────────────────

VALID_SIDE_HUSTLE_FEASIBILITY: dict = {
    "evaluations": [
        {
            "name": "Reddit Niche Deal Scanner",
            "scores": {
                "revenue_potential": 8,
                "n8n_specific_feasibility": 9,
                "time_to_first_dollar": 8,
                "maintenance_effort": 7,
                "legal_safety": 6,
                "scalability": 7,
            },
            "total_score": 45,
            "n8n_node_inventory": [
                {
                    "node": "n8n-nodes-base.scheduleTrigger",
                    "availability": "built_in",
                    "notes": "Every 15 minutes",
                },
                {
                    "node": "n8n-nodes-base.httpRequest",
                    "availability": "built_in",
                    "notes": "Reddit API via Pushshift",
                },
                {
                    "node": "n8n-nodes-base.discord",
                    "availability": "first_party",
                    "notes": "Post to paid Discord",
                },
            ],
            "legal_checklist": {
                "compliance_categories": ["PLATFORM_TOS"],
                "specific_risks": [
                    {
                        "category": "PLATFORM_TOS",
                        "regulator_or_platform": "Reddit",
                        "recent_enforcement": (
                            "Reddit banned Pushshift access in May 2023; paid "
                            "API access is now required"
                        ),
                        "source": "https://techcrunch.com/reddit-api-pricing",
                    }
                ],
            },
            "monthly_costs": (
                "Reddit API $0-15, Cloud VM $5, Discord $0 — total $5-20/mo"
            ),
            "automation_bottleneck": (
                "Filtering relevance — need manual tuning of category keywords "
                "during first few weeks."
            ),
            "verdict": (
                "Strong candidate. Core flow is fully automatable with built-in "
                "n8n nodes. Main risk is Reddit TOS enforcement."
            ),
        },
        *[_minimal_evaluation(f"Eval {i}") for i in range(4)],
    ],
}

MINIMAL_SIDE_HUSTLE_FEASIBILITY: dict = {
    "evaluations": [_minimal_evaluation(f"Eval {i}") for i in range(5)],
}

INVALID_FEASIBILITY_FEW_EVALS: dict = {
    "evaluations": [_minimal_evaluation(f"Eval {i}") for i in range(3)],
}

INVALID_FEASIBILITY_BAD_SCORE: dict = {
    "evaluations": [
        {
            **_minimal_evaluation("Bad Score"),
            "scores": {
                **_minimal_scores(),
                "revenue_potential": 11,  # out of 1-10 range
            },
        },
        *[_minimal_evaluation(f"Eval {i}") for i in range(4)],
    ],
}

INVALID_FEASIBILITY_BAD_LEGAL_CATEGORY: dict = {
    "evaluations": [
        {
            **_minimal_evaluation("Bad Legal"),
            "legal_checklist": {
                "compliance_categories": ["NOT_A_REAL_CATEGORY"],
                "specific_risks": [],
            },
        },
        *[_minimal_evaluation(f"Eval {i}") for i in range(4)],
    ],
}


# ─────────────────────────────────────────────────────────────────────
# Step 2: contrarian_analysis
# ─────────────────────────────────────────────────────────────────────

VALID_SIDE_HUSTLE_CONTRARIAN: dict = {
    "analyses": [
        {
            "name": "Reddit Niche Deal Scanner",
            "failed_predecessors": [
                {
                    "name": "@dealbot_dave",
                    "year": "2023",
                    "reason": (
                        "Lost Reddit API access after pricing change and "
                        "couldn't justify the $500/mo commercial tier at his "
                        "subscriber count."
                    ),
                    "source": "https://indiehackers.com/post/dealbot-shutdown",
                }
            ],
            "platform_dependency": "Reddit",
            "platform_crackdown_evidence": [
                {
                    "platform": "Reddit",
                    "action": "Commercial API pricing introduced",
                    "when": "2023-06-01",
                    "source": "https://redditblog.com/2023/api-pricing",
                }
            ],
            "saturation": {
                "search_summary": (
                    "~18 YouTube tutorials in last 6 months, 8 GitHub repos "
                    "starred >100 in 2025"
                ),
                "saturation_level": "medium",
            },
            "income_reality": {
                "primary_source_links": [
                    "https://indiehackers.com/post/deal-scanner-mrr"
                ],
                "typical_reported_income": (
                    "$800-1,500/mo for operators with 6+ month tenure"
                ),
                "evidence_strength": "strong",
            },
            "failure_stories": [
                {
                    "quit_reason": "API pricing killed margins",
                    "source": "https://reddit.com/r/sideproject/example",
                }
            ],
            "kill_scenario": (
                "Reddit raises API pricing further or bans automated "
                "commercial scraping entirely, making the unit economics "
                "unworkable."
            ),
            "kill_probability": "medium",
            "verdict": "weakened",
            "verdict_reasoning": (
                "Real paying customers exist (strong evidence) but platform "
                "dependency on Reddit is a persistent medium-probability kill "
                "risk. Viable for operators who accept that risk."
            ),
        },
        *[_minimal_contrarian_analysis(f"Hustle {i}") for i in range(4)],
    ],
    "summary": (
        "5 hustles analyzed. 1 weakened (Reddit Scanner due to platform "
        "risk), 4 survive. Overall portfolio is biased toward Reddit/creator "
        "automation which carries systemic platform risk."
    ),
}

MINIMAL_SIDE_HUSTLE_CONTRARIAN: dict = {
    "analyses": [_minimal_contrarian_analysis(f"Hustle {i}") for i in range(5)],
    "summary": (
        "All five analyses passed minimum schema checks for structural test "
        "purposes. This is the minimal-legal summary placeholder."
    ),
}

INVALID_CONTRARIAN_FEW_ANALYSES: dict = {
    "analyses": [_minimal_contrarian_analysis(f"Hustle {i}") for i in range(3)],
    "summary": "Too few analyses to pass the min_length=5 check.",
}

INVALID_CONTRARIAN_BAD_VERDICT: dict = {
    "analyses": [
        {**_minimal_contrarian_analysis("Bad Verdict"), "verdict": "maybe"},
        *[_minimal_contrarian_analysis(f"Hustle {i}") for i in range(4)],
    ],
    "summary": "Should fail schema due to bad verdict enum.",
}

INVALID_CONTRARIAN_BAD_KILL_PROB: dict = {
    "analyses": [
        {
            **_minimal_contrarian_analysis("Bad Kill Prob"),
            "kill_probability": "extreme",
        },
        *[_minimal_contrarian_analysis(f"Hustle {i}") for i in range(4)],
    ],
    "summary": "Should fail schema due to bad kill_probability enum.",
}


# ─────────────────────────────────────────────────────────────────────
# Step 3: synthesis_and_ranking
# ─────────────────────────────────────────────────────────────────────

VALID_SIDE_HUSTLE_SYNTHESIS: dict = {
    "final_rankings": [
        {
            "rank": 1,
            "name": "Reddit Niche Deal Scanner",
            "one_liner": (
                "Paid Discord of curated Reddit deals using n8n for scraping "
                "and filtering"
            ),
            "monthly_income_estimate": "$800-2,000",
            "monthly_costs": "$20-50",
            "contrarian_verdict": "weakened",
            "raw_score": 45.0,
            "total_score": 36.0,
            "head_to_head": (
                "Beats rank-2 because strong primary-source income evidence "
                "and a working automation bottleneck that doesn't require "
                "manual judgment per item."
            ),
            "surviving_risks": [
                "Reddit API pricing could rise further",
                "Competition from other curated feeds",
            ],
            "n8n_workflow_spec": {
                "trigger_node": (
                    "n8n-nodes-base.webhook with path: 'deal-scan-trigger'"
                ),
                "node_graph": [
                    {"node": "n8n-nodes-base.webhook", "role": "trigger"},
                    {"node": "n8n-nodes-base.httpRequest", "role": "fetch Reddit"},
                    {"node": "n8n-nodes-base.code", "role": "filter relevance"},
                    {"node": "n8n-nodes-base.discord", "role": "post to channel"},
                ],
                "external_credentials": [
                    "Reddit API key (commercial tier)",
                    "Discord webhook URL",
                ],
                "expected_runtime": "5-8 seconds per run",
                "frequency": "every 15 minutes via external cron hitting the webhook",
                "out_of_scope": [
                    "multi-language support",
                    "custom user categories",
                    "analytics dashboard",
                ],
                "success_metric": (
                    "At least 3 qualified deals posted to the channel per day "
                    "and 5+ subscribers by month 2"
                ),
                "risky_assumption": (
                    "Paying Discord subscribers will pay $10/mo for curated "
                    "deals they could otherwise find on Reddit themselves"
                ),
            },
        },
        _minimal_ranking(rank=2, name="Creator Brand Monitor"),
    ],
    "executive_summary": (
        "2 of 5 analyzed hustles survived contrarian scrutiny. Reddit Niche "
        "Deal Scanner ranks #1 despite its 'weakened' verdict due to "
        "stronger primary-source income evidence than any survivor. Creator "
        "Brand Monitor ranks #2 with cleaner platform story but weaker "
        "demand signals. Recommended monthly budget $20-70 covers both "
        "tools combined. Primary cross-cutting risk: both depend on "
        "third-party APIs that could raise prices or revoke access."
    ),
}

MINIMAL_SIDE_HUSTLE_SYNTHESIS: dict = {
    "final_rankings": [
        _minimal_ranking(rank=1, name="Minimal One"),
        _minimal_ranking(rank=2, name="Minimal Two"),
    ],
    "executive_summary": (
        "A minimal executive summary that is long enough to satisfy the "
        "schema's min_length=100 constraint by writing several short "
        "sentences. It does not need to be informative, only valid."
    ),
}

INVALID_SYNTHESIS_FEW_RANKINGS: dict = {
    "final_rankings": [_minimal_ranking()],
    "executive_summary": (
        "A minimal executive summary that is long enough to satisfy the "
        "schema's min_length=100 constraint by writing several short "
        "sentences. It does not need to be informative, only valid."
    ),
}

INVALID_SYNTHESIS_SPEC_MISSING_FIELD: dict = {
    "final_rankings": [
        {
            **_minimal_ranking(),
            "n8n_workflow_spec": {
                **_minimal_workflow_spec(),
                # Remove required field
                "risky_assumption": None,
            },
        },
        _minimal_ranking(rank=2, name="Two"),
    ],
    "executive_summary": (
        "A minimal executive summary that is long enough to satisfy the "
        "schema's min_length=100 constraint by writing several short "
        "sentences. It does not need to be informative, only valid."
    ),
}

INVALID_SYNTHESIS_SPEC_WRONG_OUT_OF_SCOPE_COUNT: dict = {
    "final_rankings": [
        {
            **_minimal_ranking(),
            "n8n_workflow_spec": {
                **_minimal_workflow_spec(),
                # Round 1 rule: exactly 3 items in out_of_scope
                "out_of_scope": ["only one item"],
            },
        },
        _minimal_ranking(rank=2, name="Two"),
    ],
    "executive_summary": (
        "A minimal executive summary that is long enough to satisfy the "
        "schema's min_length=100 constraint by writing several short "
        "sentences. It does not need to be informative, only valid."
    ),
}
