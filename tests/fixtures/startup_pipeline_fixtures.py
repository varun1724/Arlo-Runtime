"""Golden sample outputs for each step of the startup_idea_pipeline.

These fixtures serve two purposes:

1. They are the **contract** that future prompt edits must continue to
   produce: every prompt iteration must keep producing JSON that matches
   the shape of the VALID_* fixtures here.

2. They are the test inputs for ``tests/test_startup_schemas.py`` and
   ``tests/test_research_validation.py`` — every Pydantic schema in
   ``app/workflows/schemas.py`` must accept its VALID_*, accept its
   MINIMAL_*, and reject every variant in INVALID_*.

When you change a prompt template's JSON output schema in
``app/workflows/templates.py``, update both the matching Pydantic model
in ``app/workflows/schemas.py`` AND the matching VALID_* fixture here.
The ``test_prompt_schema_alignment`` tests will fail if these drift.
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────
# Step 0: landscape_scan
# ─────────────────────────────────────────────────────────────────────

VALID_LANDSCAPE: dict = {
    "market_size": "$12.4B in 2024 per Gartner Developer Tools Forecast (Aug 2024)",
    "growth_rate": "18% CAGR through 2028 per Grand View Research",
    "landscape_summary": (
        "The AI developer tools market is in rapid expansion driven by "
        "LLM cost collapse and enterprise adoption of code assistants. "
        "Cursor, Windsurf, and Codeium are absorbing share from GitHub "
        "Copilot's once-dominant position. Adjacent niches around code "
        "review, test generation, and migration tooling remain relatively "
        "underserved. The next 12 months are expected to see consolidation "
        "in the IDE assistant space and fragmentation into vertical tools."
    ),
    "key_players": [
        {
            "name": "Cursor",
            "description": "AI-first code editor forked from VS Code",
            "estimated_revenue_or_funding": "$100M ARR, $400M Series B (Aug 2024)",
        },
        {
            "name": "GitHub Copilot",
            "description": "Microsoft-owned incumbent code assistant",
            "estimated_revenue_or_funding": "$500M+ ARR estimate",
        },
    ],
    "opportunities": [
        {
            "name": "Automated PR triage for OSS maintainers",
            "description": "AI-powered queue grooming, duplicate detection, and reviewer assignment for high-volume open source repos.",
            "timing_signal_type": "BEHAVIORAL_CHANGE",
            "timing_signal": "OSS maintainers publicly burning out (HN front page Sep 2024, multiple posts/month)",
            "evidence": "BabelJS, Vue, and Rome maintainers all wrote about triage burden in 2024",
            "non_obviousness_check": "no",
        },
        {
            "name": "LLM-based legacy code migration",
            "description": "Translate large COBOL, Perl, and PHP codebases into modern languages with type-safe outputs.",
            "timing_signal_type": "TECHNOLOGY_UNLOCK",
            "timing_signal": "Claude 3.5 Sonnet's long-context performance on code translation crossed usability threshold in mid-2024",
            "evidence": "Mantle (YC W24) raised $5M for COBOL→Java migration",
            "non_obviousness_check": "no",
        },
        {
            "name": "AI-generated test suites for legacy untested code",
            "description": "Point at a repo with low coverage; the tool generates a meaningful test suite with proper assertions.",
            "timing_signal_type": "TECHNOLOGY_UNLOCK",
            "timing_signal": "Codium's funding round and CodeGPT plugin downloads doubling in 2024",
            "evidence": "Codium raised $11M Series A, March 2024",
            "non_obviousness_check": "no",
        },
        {
            "name": "Compliance-aware code review for regulated industries",
            "description": "Code review tool that flags HIPAA, PCI, and GDPR violations inline during PRs.",
            "timing_signal_type": "REGULATORY_SHIFT",
            "timing_signal": "EU AI Act enforcement begins Feb 2025",
            "evidence": "Snyk and Semgrep both shipping AI-powered compliance modules in 2024",
            "non_obviousness_check": "no",
        },
        {
            "name": "Database schema migration assistant",
            "description": "Generates safe, reversible schema migrations from natural-language intent and validates against a staging copy.",
            "timing_signal_type": "COST_COLLAPSE",
            "timing_signal": "Branching DBs (Neon, PlanetScale) made staging copies near-free in 2024",
            "evidence": "Neon's branching is now used by 30%+ of YC startups",
            "non_obviousness_check": "no",
        },
        {
            "name": "AI code review",
            "description": "PR reviewer bot that comments on style, bugs, and architecture.",
            "timing_signal_type": "TECHNOLOGY_UNLOCK",
            "timing_signal": "Claude 3.5 Sonnet release in mid-2024 made review quality usable",
            "evidence": "CodeRabbit, Greptile, and Sentry's autofix all launched in 2024",
            "non_obviousness_check": "yes",
            "non_obviousness_justification": "Crowded space, but vertical specialization (e.g., security-only review) still wide open",
        },
    ],
    "macro_trends": [
        "LLM inference cost dropped ~80% in 2024 (per a16z blog post)",
        "Enterprise AI adoption accelerated post-GPT-4o release",
    ],
    "sources_consulted": [
        "Gartner Developer Tools Forecast 2024",
        "Hacker News 'Show HN' archive (last 90 days)",
        "GitHub trending repos September 2024",
        "Crunchbase developer tools funding rounds 2024",
    ],
}


MINIMAL_LANDSCAPE: dict = {
    "market_size": "Tiny",
    "growth_rate": "Flat",
    "landscape_summary": "Small.",
    "key_players": [
        {"name": "X", "description": "Y", "estimated_revenue_or_funding": "Z"},
    ],
    "opportunities": [
        {
            "name": f"opp{i}",
            "description": "d",
            "timing_signal_type": "TECHNOLOGY_UNLOCK",
            "timing_signal": "ts",
            "evidence": "e",
            "non_obviousness_check": "no",
        }
        for i in range(5)
    ],
    "macro_trends": ["t"],
    "sources_consulted": ["a", "b", "c"],
}


INVALID_LANDSCAPE_FEW_OPPS: dict = {
    **MINIMAL_LANDSCAPE,
    "opportunities": MINIMAL_LANDSCAPE["opportunities"][:4],  # only 4
}

INVALID_LANDSCAPE_BAD_TIMING_TYPE: dict = {
    **MINIMAL_LANDSCAPE,
    "opportunities": [
        {
            **MINIMAL_LANDSCAPE["opportunities"][0],
            "timing_signal_type": "BOGUS_CATEGORY",
        },
        *MINIMAL_LANDSCAPE["opportunities"][1:],
    ],
}

INVALID_LANDSCAPE_MISSING_FIELD: dict = {
    "growth_rate": "Flat",
    "landscape_summary": "Small.",
    "key_players": [{"name": "X", "description": "Y", "estimated_revenue_or_funding": "Z"}],
    "opportunities": MINIMAL_LANDSCAPE["opportunities"],
    "macro_trends": ["t"],
    "sources_consulted": ["a", "b", "c"],
    # missing "market_size"
}


# ─────────────────────────────────────────────────────────────────────
# Step 1: deep_dive
# ─────────────────────────────────────────────────────────────────────

VALID_DEEP_DIVE: dict = {
    "deep_dive_opportunities": [
        {
            "name": "Automated PR triage for OSS maintainers",
            "description": (
                "Tool that watches a repo's PR queue, deduplicates, applies "
                "labels, suggests reviewers, and asks the right clarifying "
                "question before a human looks at it. Reduces maintainer "
                "load 5-10x on high-volume repos."
            ),
            "competitors": [
                {
                    "name": "Stale Bot",
                    "funding": "Open source",
                    "founded": "2017",
                    "status": "active",
                    "what_they_do": "Closes inactive issues automatically",
                },
            ],
            "market_size_estimates": [
                {"source": "GitHub Octoverse 2024", "estimate": "100M+ active OSS repos", "year": "2024"},
                {"source": "Tidelift maintainer report", "estimate": "$10B+ in unpaid maintainer labor", "year": "2023"},
            ],
            "demand_signals": [
                {
                    "tier": "HOT",
                    "source": "https://news.ycombinator.com/item?id=12345",
                    "signal": "BabelJS lead maintainer publicly asked if anyone could build PR triage automation",
                },
                {
                    "tier": "WARM",
                    "source": "r/opensource thread Aug 2024",
                    "signal": "27 comments agreeing PR triage is the worst part of maintainership",
                },
            ],
            "unit_economics": {
                "typical_price_point": "$49-199/month per repo",
                "billing_model": "subscription",
                "cac_channel": "OSS community partnerships and conference sponsorships",
                "gross_margin_signal": "high",
            },
            "early_failure_signal": "OSS maintainers are notoriously price-sensitive; foundation funding may be required",
            "evidence_strength": "moderate",
            "initial_assessment": (
                "Real pain, real demand, weak monetization. Could work as a "
                "B2B tool sold to companies whose employees maintain the repo, "
                "rather than to maintainers directly."
            ),
        },
        {
            "name": "LLM-based legacy code migration",
            "description": (
                "Migrate COBOL/Perl/PHP codebases to modern languages with "
                "type-safe outputs and round-trip testing."
            ),
            "competitors": [
                {
                    "name": "Mantle",
                    "funding": "$5M seed",
                    "founded": "2024",
                    "status": "active",
                    "what_they_do": "COBOL to Java migration",
                },
            ],
            "market_size_estimates": [
                {"source": "IBM mainframe report 2024", "estimate": "220B lines of COBOL still in production", "year": "2024"},
                {"source": "Reuters", "estimate": "$3B annual COBOL maintenance spend (banks alone)", "year": "2023"},
            ],
            "demand_signals": [
                {"tier": "HOT", "source": "Bank IT director quote in Reuters article", "signal": "We would pay $1M for a tool that could migrate this safely"},
                {"tier": "WARM", "source": "Mainframe modernization subreddit", "signal": "Multiple posts/week asking for tooling"},
            ],
            "unit_economics": {
                "typical_price_point": "$10K-100K per project (one-time)",
                "billing_model": "one_time",
                "cac_channel": "Direct enterprise sales to bank/insurance IT",
                "gross_margin_signal": "medium",
            },
            "early_failure_signal": "Solo dev cannot credibly sell to banks; channel mismatch",
            "evidence_strength": "strong",
            "initial_assessment": (
                "Huge real market but bad fit for solo dev. Better as a "
                "consulting + tooling hybrid through a partner channel."
            ),
        },
        {
            "name": "AI-generated test suites",
            "description": "Generate meaningful test suites with proper assertions for legacy untested code.",
            "competitors": [
                {"name": "Codium", "funding": "$11M Series A", "founded": "2022", "status": "active", "what_they_do": "AI test generation IDE plugin"},
                {"name": "Diffblue", "funding": "$22M total", "founded": "2016", "status": "active", "what_they_do": "Java unit test generation"},
            ],
            "market_size_estimates": [
                {"source": "Forrester DevOps 2024", "estimate": "$8B test automation market", "year": "2024"},
                {"source": "Codium pitch deck (leaked)", "estimate": "$2B AI test sub-segment", "year": "2024"},
            ],
            "demand_signals": [
                {"tier": "WARM", "source": "DevOps subreddit", "signal": "Engineers complaining about coverage requirements without time to write tests"},
                {"tier": "WARM", "source": "Codium G2 reviews", "signal": "Strong reviews citing time saved"},
            ],
            "unit_economics": {
                "typical_price_point": "$19-99/month per developer",
                "billing_model": "subscription",
                "cac_channel": "JetBrains/VS Code marketplace organic",
                "gross_margin_signal": "high",
            },
            "early_failure_signal": "Codium is a very well-funded direct competitor",
            "evidence_strength": "strong",
            "initial_assessment": "Crowded but real demand. Vertical focus (e.g., Python+pytest only) might find a niche.",
        },
    ],
    "dropped_opportunities": [
        {
            "name": "AI code review",
            "reason": "Too crowded at the horizontal layer; verticals not differentiated enough yet",
        },
    ],
}


def _minimal_dd_opp(name: str) -> dict:
    return {
        "name": name,
        "description": "d",
        "competitors": [],
        "market_size_estimates": [{"source": "s", "estimate": "e", "year": "y"}],
        "demand_signals": [{"tier": "HOT", "source": "s", "signal": "x"}],
        "unit_economics": {
            "typical_price_point": "$10",
            "billing_model": "subscription",
            "cac_channel": "SEO",
            "gross_margin_signal": "high",
        },
        "early_failure_signal": "competition",
        "evidence_strength": "moderate",
        "initial_assessment": "ok",
    }


MINIMAL_DEEP_DIVE: dict = {
    "deep_dive_opportunities": [_minimal_dd_opp(f"opp{i}") for i in range(3)],
    "dropped_opportunities": [],
}


INVALID_DEEP_DIVE_TOO_FEW: dict = {
    "deep_dive_opportunities": [_minimal_dd_opp("only_one")],
    "dropped_opportunities": [],
}

INVALID_DEEP_DIVE_BAD_TIER: dict = {
    "deep_dive_opportunities": [
        {**_minimal_dd_opp(f"opp{i}"), "demand_signals": [{"tier": "LUKEWARM", "source": "s", "signal": "x"}]}
        for i in range(3)
    ],
    "dropped_opportunities": [],
}

INVALID_DEEP_DIVE_BAD_BILLING: dict = {
    "deep_dive_opportunities": [
        {**_minimal_dd_opp(f"opp{i}"), "unit_economics": {**_minimal_dd_opp(f"opp{i}")["unit_economics"], "billing_model": "barter"}}
        for i in range(3)
    ],
    "dropped_opportunities": [],
}


# ─────────────────────────────────────────────────────────────────────
# Step 2: contrarian_analysis
# ─────────────────────────────────────────────────────────────────────

VALID_CONTRARIAN: dict = {
    "contrarian_analyses": [
        {
            "name": "Automated PR triage for OSS maintainers",
            "failed_predecessors": [
                {
                    "company": "Probot",
                    "year": "2017",
                    "what_happened": "Open-source bot framework, never monetized, lost momentum 2020",
                    "lesson": "Free tools for maintainers don't sustain a business",
                },
            ],
            "incumbent_threats": [
                {
                    "incumbent": "GitHub",
                    "evidence": "GitHub launched Copilot for PRs in beta (Aug 2024)",
                    "source": "https://github.blog/2024-08-15-copilot-for-pull-requests-beta/",
                },
            ],
            "market_headwinds": ["Maintainers are price-sensitive and unpaid"],
            "regulatory_risk": {
                "is_regulated_domain": False,
                "regulatory_bodies": [],
                "specific_risks": [],
                "compliance_burden": "low",
            },
            "technical_risks": ["LLM hallucinations on niche domain code"],
            "kill_scenario": "GitHub bundles equivalent functionality into free Copilot tier",
            "kill_probability": "high",
            "verdict": "weakened",
            "verdict_reasoning": (
                "Real pain but the buyer cannot pay and the natural distributor "
                "(GitHub) is moving in. Salvageable only with a B2B company-pays "
                "angle, which is a different product."
            ),
        },
        {
            "name": "LLM-based legacy code migration",
            "failed_predecessors": [],
            "incumbent_threats": [
                {
                    "incumbent": "IBM",
                    "evidence": "IBM watsonx Code Assistant for Z launched Q4 2023",
                    "source": "https://www.ibm.com/products/watsonx-code-assistant-z",
                },
            ],
            "market_headwinds": [],
            "regulatory_risk": {
                "is_regulated_domain": True,
                "regulatory_bodies": ["FFIEC", "OCC"],
                "specific_risks": ["Banks require audit trails for any code touching production systems"],
                "compliance_burden": "high",
            },
            "technical_risks": ["LLM correctness on financial logic is still unproven at scale"],
            "kill_scenario": "Solo dev cannot credibly sell to enterprise procurement",
            "kill_probability": "high",
            "verdict": "killed",
            "verdict_reasoning": "Wrong fit for solo dev — enterprise sales motion required.",
        },
        {
            "name": "AI-generated test suites",
            "failed_predecessors": [
                {
                    "company": "Diffblue",
                    "year": "2016 founded, still active but slow growth",
                    "what_happened": "Java-only, 8 years and $22M but limited adoption",
                    "lesson": "Test generation has real demand but conversion is hard",
                },
            ],
            "incumbent_threats": [
                {
                    "incumbent": "GitHub Copilot",
                    "evidence": "Copilot can generate tests inline already",
                    "source": "GitHub Copilot docs",
                },
            ],
            "market_headwinds": ["Test generation quality bar is high"],
            "regulatory_risk": {
                "is_regulated_domain": False,
                "regulatory_bodies": [],
                "specific_risks": [],
                "compliance_burden": "low",
            },
            "technical_risks": ["Generated tests often test implementation rather than behavior"],
            "kill_scenario": "Codium captures the market before this can build differentiation",
            "kill_probability": "medium",
            "verdict": "survives",
            "verdict_reasoning": "Vertical focus on Python+pytest with property-based testing could find a real niche.",
        },
    ],
    "summary": "Of 3 deep-dived opportunities, 1 survives, 1 is weakened, and 1 is killed. The survivor (AI test suites) is the only one that fits a solo dev profile.",
}


def _minimal_contrarian_analysis(name: str) -> dict:
    return {
        "name": name,
        "failed_predecessors": [],
        "incumbent_threats": [],
        "market_headwinds": [],
        "regulatory_risk": {
            "is_regulated_domain": False,
            "regulatory_bodies": [],
            "specific_risks": [],
            "compliance_burden": "low",
        },
        "technical_risks": [],
        "kill_scenario": "ks",
        "kill_probability": "low",
        "verdict": "survives",
        "verdict_reasoning": "ok",
    }


MINIMAL_CONTRARIAN: dict = {
    "contrarian_analyses": [_minimal_contrarian_analysis(f"opp{i}") for i in range(3)],
    "summary": "All survive.",
}


INVALID_CONTRARIAN_TOO_FEW: dict = {
    "contrarian_analyses": [_minimal_contrarian_analysis("only_one")],
    "summary": "Only one.",
}

INVALID_CONTRARIAN_BAD_VERDICT: dict = {
    "contrarian_analyses": [
        {**_minimal_contrarian_analysis(f"opp{i}"), "verdict": "maybe"}
        for i in range(3)
    ],
    "summary": "ok",
}

INVALID_CONTRARIAN_BAD_KILL_PROB: dict = {
    "contrarian_analyses": [
        {**_minimal_contrarian_analysis(f"opp{i}"), "kill_probability": "very_high"}
        for i in range(3)
    ],
    "summary": "ok",
}


# ─────────────────────────────────────────────────────────────────────
# Step 3: synthesis_and_ranking
# ─────────────────────────────────────────────────────────────────────


def _moats_block(rating: int = 3) -> dict:
    """Build a uniform moats block for fixtures.

    Default rating is 3 ("weak" on the new 1-10 anchor), matching the
    prior default. Tests that want to cover the full spectrum pass
    explicit integers (1, 5, 7, 10).
    """
    return {
        dim: {"rating": rating, "justification": "j"}
        for dim in (
            "network_effects",
            "switching_costs",
            "data_advantage",
            "brand_or_trust",
            "distribution_lock",
        )
    }


# A reusable "rich" ranking that satisfies the Round 3 min_length and
# total_score >= 20 constraints. Used as the seed for VALID_SYNTHESIS.
def _rich_ranking(rank: int, name: str, one_liner: str, total: float) -> dict:
    return {
        "rank": rank,
        "name": name,
        "one_liner": one_liner,
        "scores": {
            "market_timing": 8,
            "defensibility": 5,
            "solo_dev_feasibility": 9,
            "revenue_potential": 7,
            "evidence_quality": 8,
        },
        "moats": {
            "network_effects": {"rating": 1, "justification": "Test quality doesn't compound across users"},
            "switching_costs": {"rating": 3, "justification": "Generated tests live in the user's repo"},
            "data_advantage": {"rating": 3, "justification": "Could improve generation quality from anonymized usage"},
            "brand_or_trust": {"rating": 3, "justification": "Brand matters for code quality tools"},
            "distribution_lock": {"rating": 1, "justification": "VS Code marketplace is competitive"},
        },
        "total_score": total,
        "head_to_head": "Beats the next-ranked opportunity on solo-dev feasibility and revenue clarity.",
        "surviving_risks": ["Established competitor could pivot into this niche"],
        "mvp_spec": {
            "what_to_build": "CLI tool that scans a project and generates a runnable test suite.",
            "core_user_journey": "Run the CLI on a Python project with no tests; get a runnable test suite that passes immediately.",
            "tech_stack": "Python 3.12, Click, hypothesis, Anthropic API",
            "build_time_weeks": 5,
            "first_customers": [
                "Indie Python developers on GitHub with low coverage",
                "Python data scientists shipping production code",
                "Solo Django/FastAPI builders",
            ],
            "validation_approach": "Pre-launch waitlist with $9/mo deposit, target 30 deposits before building.",
            "out_of_scope": [
                "Other languages",
                "GUI / IDE plugin",
                "CI integration",
            ],
            "success_metric": "100 paying users by month 6, conversion >= 5%.",
            "risky_assumption": "Solo Python devs care enough about test coverage to pay monthly.",
        },
    }


VALID_SYNTHESIS: dict = {
    "final_rankings": [
        _rich_ranking(1, "AI-generated test suites for Python",
                      "pytest test generator that uses property-based testing for legacy Python codebases", 39.0),
        _rich_ranking(2, "AI database migration assistant",
                      "Generates safe reversible Postgres migrations from natural-language intent.", 33.5),
        _rich_ranking(3, "PR triage bot for indie OSS",
                      "Automated PR queue grooming for small open source repositories.", 28.0),
    ],
    "executive_summary": (
        "After contrarian filtering, three opportunities remain viable for a solo "
        "developer. The top pick combines clear paying demand, strong solo-dev "
        "feasibility, and modest defensibility through community focus."
    ),
}


def _minimal_synthesis_ranking(rank: int = 1, total: float = 25.0) -> dict:
    """Smallest legal SynthesisRanking under Round 3 constraints."""
    return {
        "rank": rank,
        "name": "x",
        "one_liner": "y",
        "scores": {
            "market_timing": 5,
            "defensibility": 5,
            "solo_dev_feasibility": 5,
            "revenue_potential": 5,
            "evidence_quality": 5,
        },
        "moats": _moats_block(),
        "total_score": total,
        "head_to_head": "h",
        "surviving_risks": [],
        "mvp_spec": {
            # All free-text fields meet Round 3 min_length constraints.
            "what_to_build": "Build a small CLI utility.",
            "core_user_journey": "Run the CLI and see output.",
            "tech_stack": "Python",
            "build_time_weeks": 4,
            "first_customers": ["c1"],
            "validation_approach": "Pre-launch landing page.",
            "out_of_scope": ["a"],
            "success_metric": "10 paying users in 90 days.",
            "risky_assumption": "Users will pay for this small tool.",
        },
    }


MINIMAL_SYNTHESIS: dict = {
    # Round 3: bumped to 3 rankings to satisfy SynthesisResult.min_length=3
    "final_rankings": [_minimal_synthesis_ranking(rank=i + 1) for i in range(3)],
    "executive_summary": "ok",
}


INVALID_SYNTHESIS_EMPTY_RANKINGS: dict = {
    "final_rankings": [],
    "executive_summary": "All ideas killed.",
}


INVALID_SYNTHESIS_TOO_FEW_RANKINGS: dict = {
    # 2 rankings — below the Round 3 min_length=3 floor
    "final_rankings": [_minimal_synthesis_ranking(rank=1), _minimal_synthesis_ranking(rank=2)],
    "executive_summary": "Only two ideas survived contrarian.",
}


INVALID_SYNTHESIS_LOW_TOTAL_SCORE: dict = {
    # total_score below the Round 3 floor of 20.0
    "final_rankings": [_minimal_synthesis_ranking(rank=i + 1, total=15.0) for i in range(3)],
    "executive_summary": "All ideas are weak.",
}


INVALID_SYNTHESIS_OUT_OF_RANGE_SCORE: dict = {
    "final_rankings": [
        {**_minimal_synthesis_ranking(rank=i + 1),
         "scores": {**_minimal_synthesis_ranking()["scores"], "market_timing": 11}}
        for i in range(3)
    ],
    "executive_summary": "ok",
}


INVALID_SYNTHESIS_MISSING_MVP_FIELD: dict = {
    "final_rankings": [
        {
            **_minimal_synthesis_ranking(rank=i + 1),
            "mvp_spec": {
                k: v
                for k, v in _minimal_synthesis_ranking()["mvp_spec"].items()
                if k != "risky_assumption"
            },
        }
        for i in range(3)
    ],
    "executive_summary": "ok",
}


INVALID_SYNTHESIS_SHORT_RISKY_ASSUMPTION: dict = {
    # risky_assumption too short — Round 3 min_length=15
    "final_rankings": [
        {
            **_minimal_synthesis_ranking(rank=i + 1),
            "mvp_spec": {
                **_minimal_synthesis_ranking()["mvp_spec"],
                "risky_assumption": "yes",
            },
        }
        for i in range(3)
    ],
    "executive_summary": "ok",
}


INVALID_SYNTHESIS_SHORT_CORE_USER_JOURNEY: dict = {
    # core_user_journey too short — Round 3 min_length=20
    "final_rankings": [
        {
            **_minimal_synthesis_ranking(rank=i + 1),
            "mvp_spec": {
                **_minimal_synthesis_ranking()["mvp_spec"],
                "core_user_journey": "click button",
            },
        }
        for i in range(3)
    ],
    "executive_summary": "ok",
}


INVALID_SYNTHESIS_BAD_MOAT_RATING: dict = {
    "final_rankings": [
        {
            **_minimal_synthesis_ranking(rank=i + 1),
            "moats": {
                **_moats_block(),
                "network_effects": {"rating": "extreme", "justification": "j"},
            },
        }
        for i in range(3)
    ],
    "executive_summary": "ok",
}
