"""Predefined workflow templates."""

STARTUP_IDEA_PIPELINE = {
    "template_id": "startup_idea_pipeline",
    "name": "Startup Idea Pipeline (Deep Research)",
    "description": "Multi-pass deep research → Contrarian analysis → Synthesis & ranking → Approval → Build MVP",
    "required_context": ["domain"],
    "optional_context": ["focus_areas", "constraints"],
    "steps": [
        # ──────────────────────────────────────────────────
        # Step 0: Broad landscape scan
        # ──────────────────────────────────────────────────
        {
            "name": "landscape_scan",
            "job_type": "research",
            "prompt_template": (
                "You are a senior startup research analyst. Conduct a broad landscape scan of the "
                "{domain} market.\n\n"
                "Focus areas: {focus_areas}\n"
                "Constraints: {constraints}\n\n"
                "INSTRUCTIONS:\n"
                "1. Use web search extensively. Search for:\n"
                "   - Industry reports and market sizing (Gartner, CB Insights, Grand View Research, etc.)\n"
                "   - Recent funding announcements in this space (last 12-18 months)\n"
                "   - Emerging trends and technology shifts\n"
                "   - Regulatory or macro factors affecting this market\n\n"
                "2. Identify 10-15 distinct opportunity areas. For each, provide:\n"
                "   - A clear name and 2-sentence description\n"
                "   - Why this opportunity exists NOW (timing signal)\n"
                "   - At least one named company or data point as evidence\n\n"
                "3. Map the overall market landscape:\n"
                "   - Total market size with source\n"
                "   - Growth rate with source\n"
                "   - Key players and their positions\n"
                "   - Major trends driving change\n\n"
                "QUALITY STANDARDS:\n"
                "- Every market size claim must cite a source by name\n"
                "- Every opportunity must reference at least one real company or data point\n"
                "- Do NOT fabricate data. If you can't find reliable data, say so.\n"
                "- Use web search for EVERY major claim — do not rely on training data alone\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "market_size": "string — total market size with source",\n'
                '  "growth_rate": "string — CAGR or growth rate with source",\n'
                '  "landscape_summary": "string — 3-4 paragraph market overview",\n'
                '  "key_players": [{{"name": "string", "description": "string", "estimated_revenue_or_funding": "string"}}],\n'
                '  "opportunities": [{{"name": "string", "description": "string", "timing_signal": "string", "evidence": "string"}}],\n'
                '  "macro_trends": ["string — trend with supporting data"],\n'
                '  "sources_consulted": ["string — name of report/article/database searched"]\n'
                '}}'
            ),
            "output_key": "landscape",
            "timeout_override": 1800,
        },
        # ──────────────────────────────────────────────────
        # Step 1: Deep dive on top opportunities
        # ──────────────────────────────────────────────────
        {
            "name": "deep_dive",
            "job_type": "research",
            "prompt_template": (
                "You are a senior startup research analyst. You previously conducted a landscape scan "
                "and identified opportunities. Now go DEEP on the most promising ones.\n\n"
                "PREVIOUS LANDSCAPE SCAN:\n{landscape}\n\n"
                "INSTRUCTIONS:\n"
                "1. Select the 7-8 most promising opportunities from the landscape scan.\n\n"
                "2. For EACH opportunity, use web search to find:\n"
                "   a) COMPETITORS: Name every funded startup in this exact niche. Include:\n"
                "      - Company name, founding year, HQ\n"
                "      - Total funding raised and last round (search Crunchbase, TechCrunch)\n"
                "      - Current status (active, acquired, shut down)\n"
                "      - What they do specifically\n\n"
                "   b) MARKET SIZING: Find at least 2 independent market size estimates.\n"
                "      - Cite the research firm and report name\n"
                "      - Note TAM vs SAM vs SOM where possible\n\n"
                "   c) CUSTOMER EVIDENCE: Search for signals of real demand:\n"
                "      - Product Hunt launches, G2/Capterra reviews\n"
                "      - Reddit/HN discussions about this problem\n"
                "      - Job postings that signal companies hiring for this need\n\n"
                "   d) BUSINESS MODEL: How would a startup here make money?\n"
                "      - Pricing benchmarks from existing players\n"
                "      - Estimated unit economics if data available\n\n"
                "3. Do NOT skip web search for any opportunity. Each one needs fresh data.\n\n"
                "QUALITY STANDARDS:\n"
                "- Name real companies with real funding amounts\n"
                "- If you can't find competitors, that's valuable signal — note it explicitly\n"
                "- Cross-reference market sizes across multiple sources\n"
                "- Flag any opportunity where the evidence is thin\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "deep_dive_opportunities": [\n'
                '    {{\n'
                '      "name": "string",\n'
                '      "description": "string — 3-5 sentences",\n'
                '      "competitors": [{{"name": "string", "funding": "string", "founded": "string", "status": "string", "what_they_do": "string"}}],\n'
                '      "market_size_estimates": [{{"source": "string", "estimate": "string", "year": "string"}}],\n'
                '      "customer_evidence": ["string — specific signals of demand"],\n'
                '      "business_model": "string — how this makes money",\n'
                '      "pricing_benchmarks": "string — what similar products charge",\n'
                '      "evidence_strength": "strong | moderate | weak",\n'
                '      "initial_assessment": "string — 2-3 sentence preliminary take"\n'
                '    }}\n'
                '  ],\n'
                '  "dropped_opportunities": [{{"name": "string", "reason": "string — why this was cut from the deep dive"}}]\n'
                '}}'
            ),
            "output_key": "deep_dive",
            "condition": {"field": "landscape", "operator": "not_empty"},
            "timeout_override": 1800,
        },
        # ──────────────────────────────────────────────────
        # Step 2: Contrarian analysis — why would these FAIL?
        # ──────────────────────────────────────────────────
        {
            "name": "contrarian_analysis",
            "job_type": "research",
            "prompt_template": (
                "You are a skeptical venture capital partner reviewing startup opportunities. "
                "Your job is to STRESS TEST every opportunity — find the reasons each one could fail.\n\n"
                "DEEP DIVE RESEARCH:\n{deep_dive}\n\n"
                "INSTRUCTIONS:\n"
                "For EACH opportunity in the deep dive, use web search to investigate:\n\n"
                "1. FAILURE PATTERNS: Search for startups that have FAILED in this space.\n"
                "   - What companies tried this and shut down? Why?\n"
                "   - What pivots happened? What does that tell us?\n\n"
                "2. INCUMBENT THREAT: How could big players kill this?\n"
                "   - Could Google/Microsoft/Amazon/etc. build this as a feature?\n"
                "   - Are existing platforms expanding into this space?\n"
                "   - Search for recent announcements from incumbents\n\n"
                "3. MARKET HEADWINDS:\n"
                "   - Is the market actually growing or is that projection stale?\n"
                "   - Are there regulatory risks? Search for relevant regulation\n"
                "   - Is there customer acquisition cost evidence that makes this unviable?\n\n"
                "4. TECHNICAL RISKS:\n"
                "   - Is the core technology actually ready?\n"
                "   - Are there unsolved hard problems?\n"
                "   - Could the solution be commoditized quickly?\n\n"
                "5. VERDICT: After this analysis, classify each opportunity:\n"
                "   - SURVIVES: The opportunity holds up under scrutiny\n"
                "   - WEAKENED: Still viable but with significant caveats\n"
                "   - KILLED: Fatal flaws found — should not pursue\n\n"
                "Be ruthlessly honest. It's better to kill a bad idea now than waste months building it.\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "contrarian_analyses": [\n'
                '    {{\n'
                '      "name": "string",\n'
                '      "failed_predecessors": [{{"company": "string", "what_happened": "string", "lesson": "string"}}],\n'
                '      "incumbent_threats": ["string — specific threat with evidence"],\n'
                '      "market_headwinds": ["string — specific headwind"],\n'
                '      "technical_risks": ["string — specific risk"],\n'
                '      "kill_scenario": "string — the most likely way this startup dies",\n'
                '      "verdict": "survives | weakened | killed",\n'
                '      "verdict_reasoning": "string — 3-5 sentences explaining the verdict"\n'
                '    }}\n'
                '  ],\n'
                '  "summary": "string — overall assessment of which opportunities survived scrutiny"\n'
                '}}'
            ),
            "output_key": "contrarian",
            "condition": {"field": "deep_dive", "operator": "not_empty"},
            "timeout_override": 1800,
        },
        # ──────────────────────────────────────────────────
        # Step 3: Final synthesis and ranking
        # ──────────────────────────────────────────────────
        {
            "name": "synthesis_and_ranking",
            "job_type": "research",
            "prompt_template": (
                "You are a startup strategist producing a final investment-grade analysis. "
                "Synthesize all previous research into a definitive ranking.\n\n"
                "LANDSCAPE:\n{landscape}\n\n"
                "DEEP DIVE:\n{deep_dive}\n\n"
                "CONTRARIAN ANALYSIS:\n{contrarian}\n\n"
                "INSTRUCTIONS:\n"
                "1. Only include opportunities that received a 'survives' or 'weakened' verdict.\n"
                "   Drop anything that was 'killed' in the contrarian analysis.\n\n"
                "2. Score each surviving opportunity on these dimensions (1-10):\n"
                "   - market_timing: Is now the right time? (based on trends and evidence)\n"
                "   - defensibility: Can a moat be built? (based on competitor analysis)\n"
                "   - solo_dev_feasibility: Can one person build an MVP? (technical complexity)\n"
                "   - revenue_potential: Can this reach $10K+ MRR within 12 months?\n"
                "   - evidence_quality: How strong is the supporting data?\n\n"
                "3. For the top 5, write a detailed MVP specification:\n"
                "   - What exactly to build (features, not vague descriptions)\n"
                "   - Tech stack recommendation\n"
                "   - Estimated build time for a solo developer\n"
                "   - First 3 customers to target\n"
                "   - How to validate demand before building\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "final_rankings": [\n'
                '    {{\n'
                '      "rank": 1,\n'
                '      "name": "string",\n'
                '      "one_liner": "string — one sentence pitch",\n'
                '      "scores": {{\n'
                '        "market_timing": 8,\n'
                '        "defensibility": 7,\n'
                '        "solo_dev_feasibility": 9,\n'
                '        "revenue_potential": 8,\n'
                '        "evidence_quality": 7\n'
                '      }},\n'
                '      "total_score": 39,\n'
                '      "surviving_risks": ["string — risks that remain after contrarian analysis"],\n'
                '      "mvp_spec": {{\n'
                '        "what_to_build": "string — specific features",\n'
                '        "tech_stack": "string",\n'
                '        "build_time_weeks": 4,\n'
                '        "first_customers": ["string — specific customer types to target"],\n'
                '        "validation_approach": "string — how to validate before building"\n'
                '      }}\n'
                '    }}\n'
                '  ],\n'
                '  "executive_summary": "string — 2-3 paragraph final recommendation with reasoning"\n'
                '}}'
            ),
            "output_key": "synthesis",
            "condition": {"field": "contrarian", "operator": "not_empty"},
            "timeout_override": 1800,
        },
        # ──────────────────────────────────────────────────
        # Step 4: User approval gate
        # ──────────────────────────────────────────────────
        {
            "name": "user_picks_idea",
            "job_type": "research",
            "prompt_template": "Placeholder — this step is gated by requires_approval and never actually runs Claude.",
            "output_key": "_approval_placeholder",
            "requires_approval": True,
        },
        # ──────────────────────────────────────────────────
        # Step 5: Build MVP for chosen idea
        # ──────────────────────────────────────────────────
        {
            "name": "build_mvp",
            "job_type": "builder",
            "prompt_template": (
                "Build an MVP based on this startup research and evaluation.\n\n"
                "FINAL SYNTHESIS AND RANKING:\n{synthesis}\n\n"
                "Build a working, functional MVP for the top-ranked idea. Use the mvp_spec "
                "from the synthesis to guide what to build.\n\n"
                "REQUIREMENTS:\n"
                "- Complete project with all dependencies installed\n"
                "- Core features implemented and working (not stubs)\n"
                "- API endpoints if it's a backend service\n"
                "- Basic UI if applicable\n"
                "- README.md with: what it does, how to set up, how to run, environment variables needed\n"
                "- Dockerfile for deployment\n"
                "- .env.example with all required environment variables documented\n\n"
                "Make it real. Someone should be able to clone this repo and have a working product in 5 minutes."
            ),
            "output_key": "mvp_result",
            "condition": {"field": "synthesis", "operator": "not_empty"},
            "timeout_override": 1200,
        },
    ],
}

SIDE_HUSTLE_PIPELINE = {
    "template_id": "side_hustle_pipeline",
    "name": "Side Hustle Automation Pipeline",
    "description": "Research automatable side hustles → Evaluate → Contrarian analysis → Rank → Approve → Build n8n workflow → Deploy",
    "required_context": ["focus"],
    "optional_context": ["budget", "skills", "constraints"],
    "steps": [
        # ──────────────────────────────────────────────────
        # Step 0: Research automatable side hustles
        # ──────────────────────────────────────────────────
        {
            "name": "research_side_hustles",
            "job_type": "research",
            "prompt_template": (
                "You are a side hustle automation researcher. Research computer-based side hustles "
                "that can be largely or fully automated using workflow automation tools like n8n.\n\n"
                "Focus: {focus}\n"
                "Budget: {budget}\n"
                "Skills: {skills}\n"
                "Constraints: {constraints}\n\n"
                "INSTRUCTIONS:\n"
                "1. Use web search to find real, proven side hustles that people are actually doing.\n"
                "2. Focus specifically on hustles that can be AUTOMATED with:\n"
                "   - n8n workflow automation (HTTP requests, scheduling, data transformation)\n"
                "   - Web scraping and data aggregation\n"
                "   - API integrations (social media, email, marketplaces)\n"
                "   - Content curation and republishing\n"
                "   - Lead generation and outreach\n"
                "   - Price monitoring and arbitrage\n"
                "   - Affiliate marketing automation\n\n"
                "3. For each opportunity, find REAL examples:\n"
                "   - People on Reddit/Twitter/YouTube showing income from this\n"
                "   - Tools and services they use\n"
                "   - Realistic monthly income ranges\n"
                "   - How much is automated vs manual\n\n"
                "4. Identify 10-12 distinct opportunities.\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "opportunities": [\n'
                '    {{\n'
                '      "name": "string",\n'
                '      "description": "string — what the side hustle is and how it works",\n'
                '      "automation_approach": "string — specifically how n8n would automate this",\n'
                '      "income_range": "string — realistic monthly income (e.g., $200-800/month)",\n'
                '      "real_examples": ["string — specific Reddit posts, YouTube videos, tweets showing this works"],\n'
                '      "tools_needed": ["string — APIs, services, accounts required"],\n'
                '      "automation_percentage": "string — what % can be automated (e.g., 80% automated, 20% manual review)"\n'
                '    }}\n'
                '  ],\n'
                '  "sources_consulted": ["string — where you searched"]\n'
                '}}'
            ),
            "output_key": "side_hustle_research",
            "timeout_override": 1800,
        },
        # ──────────────────────────────────────────────────
        # Step 1: Evaluate feasibility
        # ──────────────────────────────────────────────────
        {
            "name": "evaluate_feasibility",
            "job_type": "research",
            "prompt_template": (
                "You are evaluating side hustle automation opportunities for feasibility.\n\n"
                "RESEARCH:\n{side_hustle_research}\n\n"
                "For each opportunity, use web search to verify claims and score on:\n"
                "1. revenue_potential (1-10): How realistic is the income range?\n"
                "2. automation_feasibility (1-10): Can n8n actually handle this? Are the APIs available?\n"
                "3. time_to_first_dollar (1-10): How quickly can this generate income? (10 = days, 1 = months)\n"
                "4. maintenance_effort (1-10): How little ongoing work? (10 = fully hands-off)\n"
                "5. legal_safety (1-10): How safe from TOS violations, legal issues?\n"
                "6. scalability (1-10): Can income grow without proportional effort?\n\n"
                "For each, also identify:\n"
                "- The specific n8n nodes/integrations needed\n"
                "- Any API costs or subscription fees required\n"
                "- The critical automation bottleneck (what's hardest to automate)\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "evaluations": [\n'
                '    {{\n'
                '      "name": "string",\n'
                '      "scores": {{\n'
                '        "revenue_potential": 8,\n'
                '        "automation_feasibility": 7,\n'
                '        "time_to_first_dollar": 9,\n'
                '        "maintenance_effort": 6,\n'
                '        "legal_safety": 8,\n'
                '        "scalability": 7\n'
                '      }},\n'
                '      "total_score": 45,\n'
                '      "n8n_nodes_needed": ["string — specific n8n node types"],\n'
                '      "monthly_costs": "string — estimated API/service costs",\n'
                '      "automation_bottleneck": "string — what is hardest to automate",\n'
                '      "verdict": "string — 2-3 sentence assessment"\n'
                '    }}\n'
                '  ]\n'
                '}}'
            ),
            "output_key": "feasibility",
            "condition": {"field": "side_hustle_research", "operator": "not_empty"},
            "timeout_override": 1800,
        },
        # ──────────────────────────────────────────────────
        # Step 2: Contrarian analysis
        # ──────────────────────────────────────────────────
        {
            "name": "contrarian_analysis",
            "job_type": "research",
            "prompt_template": (
                "You are a skeptic reviewing automated side hustle opportunities. "
                "Your job is to find reasons each one could fail or get shut down.\n\n"
                "FEASIBILITY EVALUATION:\n{feasibility}\n\n"
                "For EACH opportunity, use web search to investigate:\n\n"
                "1. PLATFORM RISK: Could the platform change TOS or API access?\n"
                "   - Search for recent API shutdowns or TOS changes affecting automators\n"
                "   - Has this platform cracked down on automation before?\n\n"
                "2. SATURATION: How many people are already doing this?\n"
                "   - Search Reddit, YouTube for tutorials on this exact hustle\n"
                "   - If there are 50 YouTube videos teaching it, it's likely saturated\n\n"
                "3. LEGAL RISK: Could this violate any laws or regulations?\n"
                "   - CAN-SPAM for email, GDPR for data scraping, FTC for affiliate marketing\n\n"
                "4. INCOME REALITY CHECK: Search for people reporting ACTUAL income\n"
                "   - Not what gurus claim, but what regular people report\n"
                "   - Look for failure stories too\n\n"
                "5. VERDICT: survives | weakened | killed\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "analyses": [\n'
                '    {{\n'
                '      "name": "string",\n'
                '      "platform_risks": ["string"],\n'
                '      "saturation_level": "string — low/medium/high with evidence",\n'
                '      "legal_risks": ["string"],\n'
                '      "income_reality": "string — what real people actually report earning",\n'
                '      "verdict": "survives | weakened | killed",\n'
                '      "verdict_reasoning": "string"\n'
                '    }}\n'
                '  ]\n'
                '}}'
            ),
            "output_key": "contrarian",
            "condition": {"field": "feasibility", "operator": "not_empty"},
            "timeout_override": 1800,
        },
        # ──────────────────────────────────────────────────
        # Step 3: Synthesis and ranking
        # ──────────────────────────────────────────────────
        {
            "name": "synthesis_and_ranking",
            "job_type": "research",
            "prompt_template": (
                "Synthesize all research into a final ranking of automatable side hustles.\n\n"
                "RESEARCH:\n{side_hustle_research}\n\n"
                "FEASIBILITY:\n{feasibility}\n\n"
                "CONTRARIAN:\n{contrarian}\n\n"
                "INSTRUCTIONS:\n"
                "1. Only include opportunities with 'survives' or 'weakened' verdicts.\n"
                "2. Rank by total feasibility score, weighted by contrarian verdict.\n"
                "3. For the top 3, provide a DETAILED n8n workflow specification:\n"
                "   - What trigger node to use (schedule, webhook, etc.)\n"
                "   - What processing nodes are needed (HTTP Request, Code, IF, Set, etc.)\n"
                "   - What the data flow looks like step by step\n"
                "   - What external accounts/API keys are needed\n"
                "   - Expected runtime and frequency (e.g., runs every 6 hours)\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "final_rankings": [\n'
                '    {{\n'
                '      "rank": 1,\n'
                '      "name": "string",\n'
                '      "one_liner": "string",\n'
                '      "monthly_income_estimate": "string",\n'
                '      "monthly_costs": "string",\n'
                '      "total_score": 45,\n'
                '      "surviving_risks": ["string"],\n'
                '      "n8n_workflow_spec": {{\n'
                '        "trigger": "string — trigger node type and config",\n'
                '        "steps": ["string — each processing step in order"],\n'
                '        "external_accounts_needed": ["string — accounts/APIs to set up"],\n'
                '        "frequency": "string — how often it runs",\n'
                '        "estimated_runtime": "string — how long each run takes"\n'
                '      }}\n'
                '    }}\n'
                '  ],\n'
                '  "executive_summary": "string — overall recommendation"\n'
                '}}'
            ),
            "output_key": "synthesis",
            "condition": {"field": "contrarian", "operator": "not_empty"},
            "timeout_override": 1800,
        },
        # ──────────────────────────────────────────────────
        # Step 4: User picks a hustle
        # ──────────────────────────────────────────────────
        {
            "name": "user_picks_hustle",
            "job_type": "research",
            "prompt_template": "Placeholder — gated by requires_approval.",
            "output_key": "_approval_placeholder",
            "requires_approval": True,
        },
        # ──────────────────────────────────────────────────
        # Step 5: Build n8n workflow + supporting code
        # ──────────────────────────────────────────────────
        {
            "name": "build_n8n_workflow",
            "job_type": "builder",
            "prompt_template": (
                "Build an n8n workflow automation for a side hustle.\n\n"
                "SYNTHESIS AND WORKFLOW SPEC:\n{synthesis}\n\n"
                "INSTRUCTIONS:\n"
                "1. Create a valid n8n workflow JSON file called `workflow.json` in the current directory.\n"
                "   The workflow must follow n8n's workflow format with proper nodes and connections.\n\n"
                "2. Use the n8n_workflow_spec from the synthesis to guide the workflow design.\n\n"
                "3. Include these n8n node types as appropriate:\n"
                "   - Schedule Trigger or Webhook for triggering\n"
                "   - HTTP Request for API calls\n"
                "   - Code node for custom JavaScript logic\n"
                "   - IF node for conditional branching\n"
                "   - Set node for data transformation\n"
                "   - Any other standard n8n nodes needed\n\n"
                "4. Create a README.md explaining:\n"
                "   - What this side hustle automation does\n"
                "   - Expected income and costs\n"
                "   - What accounts/credentials the user needs to set up in n8n\n"
                "   - How to configure and customize the workflow\n"
                "   - Any manual steps required\n\n"
                "5. Create any supporting files (scripts, config templates, etc.)\n\n"
                "6. Write arlo_manifest.json including a 'workflow_json' key that contains "
                "   the full contents of workflow.json (the n8n workflow definition).\n\n"
                "IMPORTANT: The workflow.json must be valid n8n workflow JSON that can be "
                "imported directly into n8n via its REST API."
            ),
            "output_key": "build_result",
            "condition": {"field": "synthesis", "operator": "not_empty"},
            "timeout_override": 1200,
        },
        # ──────────────────────────────────────────────────
        # Step 6: Deploy workflow to n8n
        # ──────────────────────────────────────────────────
        {
            "name": "deploy_to_n8n",
            "job_type": "n8n",
            "prompt_template": (
                '{{"action": "create", "activate": true, "workflow_json_from_build": true, '
                '"build_result": {build_result}}}'
            ),
            "output_key": "deploy_result",
            "condition": {"field": "build_result", "operator": "not_empty"},
        },
        # ──────────────────────────────────────────────────
        # Step 7: Test run (approval-gated)
        # ──────────────────────────────────────────────────
        {
            "name": "test_run",
            "job_type": "n8n",
            "prompt_template": (
                '{{"action": "execute", "n8n_workflow_id_from_deploy": true, '
                '"deploy_result": {deploy_result}}}'
            ),
            "output_key": "test_result",
            "condition": {"field": "deploy_result", "operator": "not_empty"},
            "requires_approval": True,
        },
    ],
}

TEMPLATES = {
    "startup_idea_pipeline": STARTUP_IDEA_PIPELINE,
    "side_hustle_pipeline": SIDE_HUSTLE_PIPELINE,
}
