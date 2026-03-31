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

FREELANCE_SCANNER_PIPELINE = {
    "template_id": "freelance_scanner",
    "name": "Freelance Opportunity Scanner",
    "description": "Research freelance niches → Evaluate → Contrarian → Rank → Approve → Build n8n scanner → Deploy",
    "required_context": ["skills"],
    "optional_context": ["location_preference", "min_hourly_rate", "platforms"],
    "steps": [
        # ──────────────────────────────────────────────────
        # Step 0: Research freelance niches
        # ──────────────────────────────────────────────────
        {
            "name": "research_freelance_niches",
            "job_type": "research",
            "prompt_template": (
                "You are a freelance market researcher. Research high-paying freelance "
                "opportunities for someone with these skills.\n\n"
                "Skills: {skills}\n"
                "Location preference: {location_preference}\n"
                "Minimum hourly rate: {min_hourly_rate}\n"
                "Preferred platforms: {platforms}\n\n"
                "INSTRUCTIONS:\n"
                "1. Use web search to find real data on freelance demand for these skills.\n"
                "2. Research these platforms specifically:\n"
                "   - Upwork (search for recent job posts, check RSS feeds availability)\n"
                "   - Toptal, Braintrust, Gun.io (vetted platforms)\n"
                "   - We Work Remotely, RemoteOK, FlexJobs\n"
                "   - LinkedIn freelance/contract postings\n"
                "   - Industry-specific boards (e.g., Wellfound for startups)\n\n"
                "3. For each platform + skill niche combination, find:\n"
                "   - Average hourly rate range (search for real data)\n"
                "   - Approximate number of new postings per week\n"
                "   - Whether the platform has RSS/API/webhook access for monitoring\n"
                "   - Platform fees (% taken from freelancer)\n\n"
                "4. Search Reddit (r/freelance, r/upwork, r/webdev, r/datascience) for:\n"
                "   - Real income reports from freelancers with these skills\n"
                "   - Which platforms they recommend and why\n"
                "   - Common pitfalls and red flags\n\n"
                "5. Identify 8-10 distinct niche opportunities (skill + platform combinations).\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "niches": [\n'
                '    {{\n'
                '      "name": "string — e.g., FastAPI Backend Dev on Toptal",\n'
                '      "platform": "string — platform name",\n'
                '      "platform_url": "string — URL for searching this niche",\n'
                '      "has_rss_or_api": true,\n'
                '      "hourly_rate_range": "string — e.g., $100-$175/hr",\n'
                '      "weekly_postings_estimate": "string — e.g., 15-25 new posts/week",\n'
                '      "platform_fee": "string — e.g., 10% on first $500, 5% after",\n'
                '      "real_freelancer_reports": ["string — specific Reddit/forum quotes about income in this niche"],\n'
                '      "monitoring_method": "string — RSS feed URL, API endpoint, or scrape approach"\n'
                '    }}\n'
                '  ],\n'
                '  "market_overview": "string — 2-3 paragraph summary of the freelance market for these skills",\n'
                '  "sources_consulted": ["string"]\n'
                '}}'
            ),
            "output_key": "niche_research",
            "timeout_override": 1800,
        },
        # ──────────────────────────────────────────────────
        # Step 1: Evaluate niches
        # ──────────────────────────────────────────────────
        {
            "name": "evaluate_niches",
            "job_type": "research",
            "prompt_template": (
                "Evaluate freelance niche opportunities for feasibility and income potential.\n\n"
                "NICHE RESEARCH:\n{niche_research}\n\n"
                "Score each niche on these dimensions (1-10):\n"
                "1. hourly_rate: How high is the pay? (10 = $150+/hr)\n"
                "2. demand_volume: How many new posts per week? (10 = 50+)\n"
                "3. competition: How easy to win work? (10 = low competition)\n"
                "4. skill_match: How well do the required skills match? (10 = perfect match)\n"
                "5. remote_friendly: Can this be done fully remotely? (10 = always remote)\n"
                "6. monitorability: How easy to automate job scanning? (10 = has RSS/API)\n\n"
                "Also identify for each:\n"
                "- Best search keywords to find relevant postings\n"
                "- Red flags to filter out (lowball rates, scam patterns, agencies)\n"
                "- Ideal client profile (startup vs enterprise, industry)\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "evaluations": [\n'
                '    {{\n'
                '      "name": "string",\n'
                '      "platform": "string",\n'
                '      "scores": {{\n'
                '        "hourly_rate": 8,\n'
                '        "demand_volume": 7,\n'
                '        "competition": 6,\n'
                '        "skill_match": 9,\n'
                '        "remote_friendly": 10,\n'
                '        "monitorability": 8\n'
                '      }},\n'
                '      "total_score": 48,\n'
                '      "search_keywords": ["string"],\n'
                '      "red_flags_to_filter": ["string"],\n'
                '      "ideal_client": "string",\n'
                '      "verdict": "string — 2-3 sentence assessment"\n'
                '    }}\n'
                '  ]\n'
                '}}'
            ),
            "output_key": "evaluation",
            "condition": {"field": "niche_research", "operator": "not_empty"},
            "timeout_override": 1800,
        },
        # ──────────────────────────────────────────────────
        # Step 2: Contrarian analysis
        # ──────────────────────────────────────────────────
        {
            "name": "contrarian_analysis",
            "job_type": "research",
            "prompt_template": (
                "You are a skeptic reviewing freelance opportunities. Find the reasons each could fail.\n\n"
                "EVALUATION:\n{evaluation}\n\n"
                "For EACH niche, use web search to investigate:\n\n"
                "1. RACE TO BOTTOM: Is this niche being undercut by cheaper freelancers?\n"
                "   - Search for complaints about rate compression\n"
                "   - Are offshore freelancers flooding this category?\n\n"
                "2. AI DISPLACEMENT: Is AI replacing this work?\n"
                "   - Search for AI tools that automate this skill\n"
                "   - Are clients starting to use AI instead of freelancers?\n\n"
                "3. PLATFORM RISK: Is the platform healthy?\n"
                "   - Recent layoffs, policy changes, fee increases?\n"
                "   - Is the platform gaining or losing market share?\n\n"
                "4. SATURATION: How crowded is this niche?\n"
                "   - Search for \"how many freelancers\" + this skill on the platform\n"
                "   - Proposal-to-hire ratios if available\n\n"
                "5. VERDICT: survives | weakened | killed\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "analyses": [\n'
                '    {{\n'
                '      "name": "string",\n'
                '      "race_to_bottom_risk": "string — specific evidence",\n'
                '      "ai_displacement_risk": "string — specific tools/trends",\n'
                '      "platform_health": "string — recent news about the platform",\n'
                '      "saturation_level": "string — low/medium/high with evidence",\n'
                '      "verdict": "survives | weakened | killed",\n'
                '      "verdict_reasoning": "string"\n'
                '    }}\n'
                '  ]\n'
                '}}'
            ),
            "output_key": "contrarian",
            "condition": {"field": "evaluation", "operator": "not_empty"},
            "timeout_override": 1800,
        },
        # ──────────────────────────────────────────────────
        # Step 3: Synthesis and ranking
        # ──────────────────────────────────────────────────
        {
            "name": "synthesis_and_ranking",
            "job_type": "research",
            "prompt_template": (
                "Synthesize all research into a final ranking of freelance niches to monitor.\n\n"
                "NICHE RESEARCH:\n{niche_research}\n\n"
                "EVALUATION:\n{evaluation}\n\n"
                "CONTRARIAN:\n{contrarian}\n\n"
                "INSTRUCTIONS:\n"
                "1. Only include niches with 'survives' or 'weakened' verdicts.\n"
                "2. Rank by total score weighted by contrarian verdict.\n"
                "3. For the top 3, provide a DETAILED monitoring specification:\n"
                "   - Exact RSS feed URL or API endpoint to poll\n"
                "   - Search query parameters / keywords\n"
                "   - Minimum rate filter\n"
                "   - Negative keyword filters (what to exclude)\n"
                "   - How often to poll (hourly, every 6h, daily)\n"
                "   - Alert format: what info to include in notifications\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "final_rankings": [\n'
                '    {{\n'
                '      "rank": 1,\n'
                '      "name": "string",\n'
                '      "platform": "string",\n'
                '      "one_liner": "string — one sentence summary",\n'
                '      "hourly_rate_range": "string",\n'
                '      "total_score": 48,\n'
                '      "surviving_risks": ["string"],\n'
                '      "monitoring_spec": {{\n'
                '        "feed_url": "string — RSS or API URL to poll",\n'
                '        "search_keywords": ["string"],\n'
                '        "negative_keywords": ["string — filter these out"],\n'
                '        "min_rate_filter": "string — e.g., $75/hr",\n'
                '        "poll_frequency": "string — e.g., every 6 hours",\n'
                '        "alert_fields": ["string — what to include in notifications: title, rate, client, link"]\n'
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
        # Step 4: User picks niche(s)
        # ──────────────────────────────────────────────────
        {
            "name": "user_picks_niche",
            "job_type": "research",
            "prompt_template": "Placeholder — gated by requires_approval.",
            "output_key": "_approval_placeholder",
            "requires_approval": True,
        },
        # ──────────────────────────────────────────────────
        # Step 5: Build scanner n8n workflow
        # ──────────────────────────────────────────────────
        {
            "name": "build_scanner_workflow",
            "job_type": "builder",
            "prompt_template": (
                "Build an n8n workflow that continuously monitors freelance job boards "
                "and sends daily digest alerts.\n\n"
                "MONITORING SPECS:\n{synthesis}\n\n"
                "BUILD REQUIREMENTS:\n"
                "1. Create a valid n8n workflow JSON file called `workflow.json`.\n"
                "2. The workflow must:\n"
                "   - Use a Schedule Trigger (every 6-12 hours)\n"
                "   - Poll RSS feeds or HTTP endpoints from the monitoring specs\n"
                "   - Parse and extract: job title, rate/budget, client info, link, posting date\n"
                "   - Filter by: minimum rate, keyword match, negative keyword exclusion\n"
                "   - Deduplicate against previously seen postings (use a Code node with \n"
                "     a simple in-memory or file-based seen-IDs check)\n"
                "   - Format matching opportunities into a clean digest\n"
                "   - Send via email (use the Send Email node with SMTP or Resend API)\n\n"
                "3. Create a README.md explaining:\n"
                "   - What this scanner monitors\n"
                "   - How to configure email/Slack notifications\n"
                "   - How to customize keywords and filters\n"
                "   - Expected results per day\n\n"
                "4. Create an `arlo_manifest.json` that includes the workflow JSON content.\n\n"
                "IMPORTANT: Use real n8n node types. The workflow must be importable into n8n."
            ),
            "output_key": "build_result",
            "condition": {"field": "synthesis", "operator": "not_empty"},
            "timeout_override": 1200,
        },
        # ──────────────────────────────────────────────────
        # Step 6: Deploy to n8n
        # ──────────────────────────────────────────────────
        {
            "name": "deploy_scanner",
            "job_type": "n8n",
            "prompt_template": (
                '{{"action": "create", "activate": true, "workflow_json_from_build": true, '
                '"build_result": {build_result}}}'
            ),
            "output_key": "deploy_result",
            "condition": {"field": "build_result", "operator": "not_empty"},
        },
    ],
}

STRATEGY_EVOLUTION_PIPELINE = {
    "template_id": "strategy_evolution",
    "name": "Trading Strategy Evolution",
    "description": "Research → Generate → Backtest → Evaluate → Evolve (loop up to 50x) → Approve",
    "required_context": ["starting_capital"],
    "optional_context": ["preferred_instruments", "risk_tolerance", "strategy_family", "seed_strategy"],
    "steps": [
        # ──────────────────────────────────────────────────
        # Step 0: Research strategies
        # ──────────────────────────────────────────────────
        {
            "name": "research_strategies",
            "job_type": "research",
            "prompt_template": (
                "You are a quantitative finance researcher. Research trading strategies that "
                "could beat buy-and-hold (S&P 500) on a risk-adjusted basis.\n\n"
                "Starting capital: {starting_capital}\n"
                "Preferred instruments: {preferred_instruments}\n"
                "Risk tolerance: {risk_tolerance}\n"
                "Strategy family preference: {strategy_family}\n\n"
                "AVAILABLE INSTRUMENTS: SPY, QQQ, IWM, VTI, GLD, TLT, AGG, EFA\n"
                "(stocks, bonds, gold, international — multi-asset rotation is encouraged)\n\n"
                "RESEARCH REQUIREMENTS:\n"
                "1. Use web search to find PROVEN strategies with academic or empirical support.\n"
                "2. Focus on strategies viable at small scale ($1000-$5000).\n"
                "3. PRIORITIZE multi-asset rotation strategies. Proven approaches:\n"
                "   - Keller's VAA (Vigilant Asset Allocation) — breadth momentum, Sharpe 1.0-1.4\n"
                "   - Antonacci's Dual Momentum (GEM) — SPY vs EFA vs AGG, Sharpe 0.85-1.0\n"
                "   - Cross-asset momentum ranking + trend filter + vol targeting, Sharpe 0.95-1.25\n"
                "   - Risk parity with vol targeting, Sharpe 0.80-1.05\n"
                "   - Regime-based rotation using VIX + yield curve, Sharpe 0.85-1.05\n"
                "   - Stacked signal ensemble (multiple weak signals combined), Sharpe 0.95-1.30\n"
                "4. Also search for ADVANCED approaches:\n"
                "   - Cross-asset lead-lag (credit spreads predict equity drops)\n"
                "   - Carry trade signals across countries (affects EFA vs SPY)\n"
                "   - Dispersion/correlation regime detection\n"
                "   - Hierarchical Risk Parity (Lopez de Prado 2016)\n"
                "   - Black-Litterman allocation with momentum views\n"
                "   - Fractal market indicators (Hurst exponent)\n"
                "   - Options-implied vol term structure signals\n"
                "   - Intermarket divergence (when gold and bonds disagree)\n"
                "   - Tax-loss harvesting calendar effects (Dec selling, Jan buying)\n"
                "   - Political/Fed meeting cycle effects on volatility\n"
                "5. For each strategy, find:\n"
                "   - Academic papers or empirical evidence\n"
                "   - Historical Sharpe ratios and returns\n"
                "   - What market conditions it works/fails in\n"
                "   - Implementation complexity\n"
                "5. Identify 5-8 candidate strategies.\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "strategies": [\n'
                '    {{\n'
                '      "name": "string",\n'
                '      "description": "string",\n'
                '      "evidence": ["string — academic/empirical sources"],\n'
                '      "historical_sharpe": "string",\n'
                '      "market_conditions": "string — when it works/fails",\n'
                '      "instruments": ["string — what to trade"],\n'
                '      "timeframe": "string — daily, weekly, monthly",\n'
                '      "complexity": "low | medium | high"\n'
                '    }}\n'
                '  ],\n'
                '  "recommendation": "string — which strategy to try first and why"\n'
                '}}'
            ),
            "output_key": "strategy_research",
            "timeout_override": 1800,
        },
        # ──────────────────────────────────────────────────
        # Step 1: Generate strategy code
        # ──────────────────────────────────────────────────
        {
            "name": "generate_strategy",
            "job_type": "research",
            "prompt_template": (
                "You are a quant developer. Based on this research, write a trading strategy "
                "as Python code.\n\n"
                "RESEARCH:\n{strategy_research}\n\n"
                "PREVIOUS BACKTEST RESULTS (if any):\n{backtest_results}\n\n"
                "SEED STRATEGY (if provided, use this as a starting point and improve it):\n"
                "{seed_strategy}\n\n"
                "Write a MULTI-ASSET strategy class that inherits from BaseStrategy.\n\n"
                "MULTI-ASSET API (you MUST use this):\n"
                "  class MyStrategy(BaseStrategy):\n"
                "      name = 'My Strategy'\n"
                "      multi_asset = True\n\n"
                "      def generate_signals(self, data: dict) -> dict:\n"
                "          # data = {{'SPY': ohlcv_df, 'TLT': ohlcv_df, 'GLD': ohlcv_df, ...}}\n"
                "          # Each df has columns: open, high, low, close, volume\n"
                "          # Return: {{'SPY': signals_df, 'TLT': signals_df, ...}}\n"
                "          # Each signals_df has 'signal' (1=buy, -1=sell, 0=hold) and 'size_pct' columns\n"
                "          # size_pct across all assets should sum to <= 0.95 at any bar\n"
                "          pass\n\n"
                "RULES:\n"
                "1. Set multi_asset = True on the class\n"
                "2. Use self.params dict for all tunable parameters\n"
                "3. Only use data available at each bar (no look-ahead bias)\n"
                "4. Import only: pandas as pd, numpy as np, from app.strategy.base import BaseStrategy\n"
                "5. Rebalance monthly (every ~21 bars). On rebalance: sell old holdings, buy new.\n"
                "6. Use bar i+1 for execution after computing signals on bar i (avoid look-ahead)\n\n"
                "AVAILABLE INSTRUMENTS: SPY, QQQ, IWM, VTI, GLD, TLT, AGG, EFA\n"
                "  Stocks: SPY (US large), QQQ (tech), IWM (small-cap), VTI (total market), EFA (international)\n"
                "  Bonds: TLT (long-term), AGG (aggregate)\n"
                "  Gold: GLD\n\n"
                "AVAILABLE MACRO DATA:\n"
                "- self.macro.get('VIXCLS', date) → VIX fear gauge\n"
                "- self.macro.get('T10Y2Y', date) → yield curve (negative = recession signal)\n"
                "- self.macro.get('FEDFUNDS', date) → Fed funds rate\n"
                "- self.macro.get('BAMLH0A0HYM2', date) → high yield spread (credit stress)\n"
                "- self.sentiment.get('SPY', date) → news sentiment (-1 to +1)\n\n"
                "PROVEN STRATEGIES TO DRAW FROM (Sharpe 0.85-1.4 historically):\n"
                "1. DUAL MOMENTUM (Antonacci): Hold SPY if 12mo return > EFA and > risk-free, else EFA, else AGG\n"
                "2. VIGILANT AA (Keller): Score momentum = 12*(p/p1)+4*(p/p3)+2*(p/p6)+(p/p12). Count positive aggressive assets (breadth). Allocate aggressive/defensive by breadth ratio.\n"
                "3. CROSS-ASSET MOMENTUM: Rank all 8 ETFs by 12-1 momentum. Hold top 3 above 200-day SMA. Risk-parity weight.\n"
                "4. VOL TARGETING (Moreira & Muir 2017): Scale positions by inverse of realized volatility. Target 10% annual vol.\n"
                "5. REGIME ROTATION: Use VIX + yield curve to define 4 regimes. Each regime has preset allocation to stocks/bonds/gold.\n"
                "6. STACKED ENSEMBLE: Combine momentum rank + trend filter + VIX regime + yield curve signal. Weight by rolling Sharpe.\n\n"
                "CREATIVE EDGE SIGNALS (combine with above for alpha):\n"
                "- CREDIT LEAD-LAG: HY spread (BAMLH0A0HYM2) widens 2-4 weeks before equity drops. If HY spread rising fast, reduce equities early.\n"
                "- VIX MEAN REVERSION: Buy equities aggressively when VIX > 35 (panic = opportunity). Reduce when VIX < 12 (complacency).\n"
                "- YIELD CURVE VELOCITY: Rate of change of T10Y2Y matters more than level. Rapidly flattening = more bearish than stable inversion.\n"
                "- SENTIMENT DIVERGENCE: When price momentum is positive but news sentiment turning negative, momentum is about to fail.\n"
                "- CORRELATION REGIME: When stock-bond correlation goes positive (both falling), switch to gold-only.\n"
                "- CALENDAR EFFECTS: Turn-of-month (last+first 3 days) captures ~70% of monthly equity returns.\n\n"
                "COMBINE APPROACHES for highest Sharpe. Example: VAA breadth + vol targeting + credit lead-lag + VIX mean reversion.\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "action": "submit_and_backtest",\n'
                '  "strategy": {{\n'
                '    "name": "string — strategy name",\n'
                '    "strategy_code": "string — full Python code",\n'
                '    "parameters": {{}},\n'
                '    "risk_constraints": {{\n'
                '      "max_drawdown_pct": 0.25,\n'
                '      "max_position_size_pct": 0.25\n'
                '    }},\n'
                '    "symbols": ["SPY", "QQQ", "IWM", "VTI", "GLD", "TLT", "AGG", "EFA"],\n'
                '    "timeframe": "1D",\n'
                '    "description": "string"\n'
                '  }},\n'
                '  "start_date": "2005-01-01",\n'
                '  "end_date": "2024-12-31",\n'
                '  "initial_capital": {starting_capital},\n'
                '  "test_type": "walk_forward"\n'
                '}}'
            ),
            "output_key": "strategy_submission",
            "condition": {"field": "strategy_research", "operator": "not_empty"},
            "timeout_override": 900,
        },
        # ──────────────────────────────────────────────────
        # Step 2: Submit and backtest
        # ──────────────────────────────────────────────────
        {
            "name": "submit_and_backtest",
            "job_type": "trading",
            "prompt_template": "{strategy_submission}",
            "output_key": "backtest_results",
            "condition": {"field": "strategy_submission", "operator": "not_empty"},
        },
        # ──────────────────────────────────────────────────
        # Step 3: Evaluate and evolve
        # ──────────────────────────────────────────────────
        {
            "name": "evaluate_and_evolve",
            "job_type": "research",
            "prompt_template": (
                "You are a quant evaluating backtest results. Analyze these results and "
                "either declare success or evolve the strategy.\n\n"
                "BACKTEST RESULTS:\n{backtest_results}\n\n"
                "CURRENT STRATEGY:\n{strategy_submission}\n\n"
                "QUALIFYING THRESHOLDS:\n"
                "- Sharpe ratio > 0.8 (SPY baseline ~0.5)\n"
                "- Max drawdown < 25% (SPY baseline ~35%)\n"
                "- Walk-forward consistency > 60% of folds profitable\n"
                "- At least 30 total trades\n\n"
                "MULTI-ASSET API (your strategy MUST use this):\n"
                "  class MyStrategy(BaseStrategy):\n"
                "      multi_asset = True\n"
                "      def generate_signals(self, data: dict) -> dict:\n"
                "          # data = {{'SPY': df, 'TLT': df, ...}} each with open/high/low/close/volume\n"
                "          # Return {{'SPY': signals_df, 'TLT': signals_df, ...}}\n"
                "          # signals_df has 'signal' (1/-1/0) and 'size_pct' columns\n"
                "          # Sum of size_pct across all assets <= 0.95 at any bar\n\n"
                "AVAILABLE INSTRUMENTS: SPY, QQQ, IWM, VTI, GLD, TLT, AGG, EFA\n"
                "MACRO: self.macro.get('VIXCLS'|'T10Y2Y'|'FEDFUNDS'|'BAMLH0A0HYM2', date)\n"
                "SENTIMENT: self.sentiment.get('SPY', date)\n\n"
                "PROVEN APPROACHES (combine for best results):\n"
                "1. DUAL MOMENTUM: SPY vs EFA, loser goes to AGG. Sharpe ~0.85-1.0\n"
                "2. VAA BREADTH: Score = 12*(p/p1)+4*(p/p3)+2*(p/p6)+(p/p12). Count positive aggressive assets. Allocate by breadth ratio. Sharpe ~1.0-1.4\n"
                "3. CROSS-ASSET MOMENTUM: Rank all ETFs by 12-1 momentum, hold top 3 above 200d SMA, risk-parity weight. Sharpe ~0.95-1.2\n"
                "4. VOL TARGETING: Scale all positions by target_vol/realized_vol. Adds ~0.10-0.25 Sharpe.\n"
                "5. REGIME ROTATION: VIX<20 + yield>0 = risk-on (stocks). VIX>20 or yield<0 = defensive (bonds/gold).\n"
                "6. STACKED ENSEMBLE: Combine momentum + trend + VIX + yield curve signals, weighted by rolling Sharpe.\n\n"
                "CREATIVE EDGE SIGNALS:\n"
                "- CREDIT LEAD-LAG: HY spread widens before equity drops. If BAMLH0A0HYM2 rising fast, reduce equities.\n"
                "- VIX MEAN REVERSION: VIX > 35 = panic buy opportunity. VIX < 12 = reduce exposure.\n"
                "- YIELD CURVE VELOCITY: Rate of change of T10Y2Y matters more than level.\n"
                "- CORRELATION REGIME: Stock-bond both falling = switch to gold.\n"
                "- CALENDAR: Turn-of-month (last+first 3 trading days) captures ~70% of monthly returns.\n\n"
                "COMMON BUGS TO AVOID:\n"
                "- Always set multi_asset = True on the class\n"
                "- Return dict of DataFrames, not a single DataFrame\n"
                "- Use data[symbol].iloc[i]['close'] not data['close']\n"
                "- Check 'if symbol in data' before accessing\n"
                "- Rebalance monthly (every ~21 bars), not every bar\n"
                "- Use i+1 for execution (avoid look-ahead bias)\n"
                "- Initialize signals for ALL symbols in data, not just the ones you trade\n\n"
                "MUTATION RULE:\n"
                "Every 10 iterations, SWITCH to a fundamentally different strategy family.\n"
                "If Sharpe hasn't improved >0.01 for 5 iterations, switch immediately.\n"
                "Try combining approaches: e.g., VAA breadth + vol targeting + macro overlay.\n\n"
                "ANALYSIS STEPS:\n"
                "1. Does the strategy meet ALL thresholds? If yes, output the strategy as-is.\n"
                "2. If Sharpe is -999, the strategy CODE had a bug. Fix the code, don't tweak parameters.\n"
                "3. If not passing, analyze WHY and modify the strategy.\n"
                "4. Output the MODIFIED strategy for the next backtest.\n\n"
                "OUTPUT: Respond with ONLY valid JSON (same format as strategy_submission):\n"
                '{{\n'
                '  "action": "submit_and_backtest",\n'
                '  "strategy": {{ ... modified strategy ... }},\n'
                '  "start_date": "2005-01-01",\n'
                '  "end_date": "2024-12-31",\n'
                '  "initial_capital": {starting_capital},\n'
                '  "test_type": "walk_forward",\n'
                '  "evolution_notes": "string — what was changed and why"\n'
                '}}'
            ),
            "output_key": "strategy_submission",
            "condition": {"field": "backtest_results", "operator": "not_empty"},
            "timeout_override": 900,
            "loop_to": 2,
            "max_loop_count": 400,
        },
        # No approval gate — winning strategies are auto-saved to
        # /workspaces/winning_strategies/ by the trading executor.
        # The loop runs the full 400 iterations to find as many winners as possible.
    ],
}

TEMPLATES = {
    "startup_idea_pipeline": STARTUP_IDEA_PIPELINE,
    "side_hustle_pipeline": SIDE_HUSTLE_PIPELINE,
    "freelance_scanner": FREELANCE_SCANNER_PIPELINE,
    "strategy_evolution": STRATEGY_EVOLUTION_PIPELINE,
}
