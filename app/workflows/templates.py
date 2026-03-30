"""Predefined workflow templates."""

STARTUP_IDEA_PIPELINE = {
    "template_id": "startup_idea_pipeline",
    "name": "Startup Idea Pipeline",
    "description": "Deep research → Evaluate & rank → Build MVP for top pick",
    "required_context": ["domain"],
    "optional_context": ["focus_areas"],
    "steps": [
        {
            "name": "deep_research",
            "job_type": "research",
            "prompt_template": (
                "Research startup opportunities in the {domain} space. "
                "Focus on: {focus_areas}. "
                "Find at least 5 concrete opportunities with market data, "
                "competitor analysis, and feasibility assessment. "
                "Be thorough — use web search to find real, current data."
            ),
            "output_key": "research_report",
            "timeout_override": 600,
        },
        {
            "name": "evaluate_and_rank",
            "job_type": "research",
            "prompt_template": (
                "You are a startup advisor. Given this research report:\n\n"
                "{research_report}\n\n"
                "Evaluate and rank the opportunities. For each one:\n"
                "1. Score feasibility (1-10)\n"
                "2. Score market potential (1-10)\n"
                "3. Estimate time-to-MVP (weeks)\n"
                "4. Identify the top 2-3 risks\n\n"
                "Select the single best opportunity and explain why it's the best pick.\n\n"
                "Output your response as JSON with this schema:\n"
                '{{"rankings": [{{"name": "...", "feasibility": 8, "market_potential": 9, '
                '"time_to_mvp_weeks": 4, "risks": ["..."]}}], '
                '"top_pick": {{"name": "...", "reasoning": "...", '
                '"mvp_scope": "brief description of what the MVP should include"}}}}'
            ),
            "output_key": "evaluation_result",
            "condition": {"field": "research_report", "operator": "not_empty"},
        },
        {
            "name": "build_mvp",
            "job_type": "builder",
            "prompt_template": (
                "Build an MVP based on this startup evaluation:\n\n"
                "{evaluation_result}\n\n"
                "Build a working prototype for the top-ranked idea. Include:\n"
                "- Complete project setup with dependencies\n"
                "- Core feature implementation\n"
                "- Basic UI if applicable (API at minimum)\n"
                "- README with setup and run instructions\n"
                "- Dockerfile for easy deployment\n\n"
                "Make it functional — someone should be able to clone this and run it."
            ),
            "output_key": "mvp_result",
            "condition": {"field": "evaluation_result", "operator": "not_empty"},
            "requires_approval": True,
            "timeout_override": 1200,
        },
    ],
}

TEMPLATES = {
    "startup_idea_pipeline": STARTUP_IDEA_PIPELINE,
}
