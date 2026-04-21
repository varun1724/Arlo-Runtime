"""Predefined workflow templates."""

from __future__ import annotations

from copy import deepcopy


def _apply_deep_research_mode(
    steps: list[dict], initial_context: dict
) -> tuple[list[dict], dict]:
    """Round 5: mutate template steps for Claude Max deep-research runs.

    Called by ``create_workflow_from_template`` in
    ``app/api/workflow_routes.py`` when the request sets
    ``deep_research_mode=True``. Returns a new (steps, context) tuple
    without modifying the inputs.

    What changes:
    - ``contrarian_analysis.max_loop_count`` is bumped from 2 to 4 so
      the recovery loop can make more attempts when contrarian kills
      too many ideas.
    - ``contrarian_analysis.timeout_override`` is bumped from 1800s to
      2700s. Round 5.5: the first real deep-mode run hit a hard 30-min
      timeout in contrarian because the broader landscape (15-20 opps)
      means more named-failure / incumbent-threat searches per run.
      45 minutes gives Claude room without the timeout becoming an
      infinite license to spin.
    - ``deep_dive.timeout_override`` is bumped from 1800s to 2700s.
      Round 5.6: second real deep-mode run hit the 30-min wall in
      deep_dive step 1 of 3 retries. 10 opportunities × per-opportunity
      web searches for competitors, market sizing, demand evidence,
      and unit economics takes longer than we originally budgeted.
    - ``landscape_scan.timeout_override`` is bumped from 900s to 1800s
      so the deeper landscape scan has room to breathe.
    - ``synthesis_and_ranking.timeout_override`` is bumped from 1200s
      to 1800s for the same reason — more opportunities to rank in
      deep mode.
    - ``deep_mode="true"`` is injected into ``initial_context`` so the
      prompts that check for this key can broaden their search scope.
    """
    new_steps = deepcopy(steps)
    for step in new_steps:
        name = step.get("name")
        # Shared across startup + side hustle pipelines
        if name == "contrarian_analysis":
            step["max_loop_count"] = 4  # was 2
            step["timeout_override"] = 2700  # was 1800; 45 min for deep mode
        elif name == "synthesis_and_ranking":
            step["timeout_override"] = 1800  # was 1200; more opps to rank
        # Startup pipeline only
        elif name == "landscape_scan":
            step["timeout_override"] = 1800  # was 900
        elif name == "deep_dive":
            step["timeout_override"] = 2700  # was 1800; 45 min for deep mode
        # Batch B new steps (startup pipeline only)
        elif name == "freshness_check":
            # Deep mode produces more survivors → more per-opportunity
            # 30-day news queries. Bump from 900s default to 1500s.
            step["timeout_override"] = 1500
        elif name == "validation_plan":
            # Deep mode ranks more opportunities (top 7 vs top 5); the
            # plan step addresses top 3-5 of those, so the scaling is
            # modest. Bump from 900s to 1200s.
            step["timeout_override"] = 1200
        # Round 6.B1: side hustle pipeline. Same proportional bumps —
        # research goes broader (15-20 opps vs 10-12) and feasibility
        # has more per-opportunity competitor + unit-economics work,
        # so the timeouts need the same headroom that landscape_scan
        # and deep_dive get on the startup side.
        elif name == "research_side_hustles":
            step["timeout_override"] = 2400  # was 1800; deeper/broader search
        elif name == "evaluate_feasibility":
            step["timeout_override"] = 2700  # was 1800; more opps + deeper checks
    new_context = {**initial_context, "deep_mode": "true"}
    return new_steps, new_context


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
                "You are a senior startup research analyst hunting for NON-OBVIOUS opportunities in "
                "the {domain} market. Your goal is to surface ideas that 90% of researchers would miss.\n\n"
                "Focus areas: {focus_areas}\n"
                "Constraints: {constraints}\n"
                "Previous attempt killed all ideas: {previous_attempt_killed_all}\n"
                "Deep research mode: {deep_mode}\n\n"
                "KNOWN FACTS FROM PRIOR PIPELINE RUNS — read these first. They contain "
                "regulatory dates, funded competitors, recent incumbent moves, and 'dead "
                "playbook' patterns already learned from earlier runs. Use them to (a) skip "
                "rediscovering the same facts via web search, (b) avoid surfacing opportunities "
                "that match a dead_playbooks pattern, and (c) weight timing and defensibility "
                "more accurately. If a fact applies to your domain, cite it by name in the "
                "relevant opportunity's timing_signal or evidence:\n"
                "{known_facts}\n\n"
                "DEEP RESEARCH MODE: If 'Deep research mode' is 'true', the user is on a "
                "Claude Max subscription and wants a more thorough pass. Aim for the HIGH END "
                "of every count below (15-20 opportunities instead of 10-15), lean more heavily "
                "on contrarian sources, and don't pull punches on depth.\n\n"
                "RECOVERY MODE: If 'Previous attempt killed all ideas' is 'true', this is a "
                "looped retry. The earlier landscape was too narrow and the contrarian step rejected "
                "every opportunity. You MUST broaden the search this time:\n"
                "- Look at adjacent niches and unconventional angles\n"
                "- Lean even harder on contrarian sources (Reddit, HN, niche subreddits)\n"
                "- Lower the bar on 'obviousness' — find opportunities that may not look like winners\n"
                "  on first read but have a real underlying timing signal\n"
                "- Avoid the well-known categories that VCs are already chasing\n"
                "If the value above is '{{unknown}}' or anything other than 'true', this is a fresh "
                "first attempt — proceed normally.\n\n"
                "INSTRUCTIONS:\n"
                "1. Use web search across DIVERSE source types. Don't just read industry reports — "
                "the best opportunities hide where analysts don't look. Search:\n"
                "   a) Mainstream sources (for market sizing only):\n"
                "      - Gartner, CB Insights, Grand View Research\n"
                "      - Recent funding announcements (Crunchbase, TechCrunch, last 12-18 months)\n"
                "   b) Contrarian sources (for non-obvious opportunities):\n"
                "      - Reddit niche subreddits where target users complain about workflow pain\n"
                "      - Hacker News 'Ask HN' and 'Show HN' threads\n"
                "      - GitHub trending repos and issue trackers showing unmet needs\n"
                "      - Product Hunt launches in the last 90 days\n"
                "      - YC Request for Startups, indie hacker forums, micro-SaaS communities\n"
                "      - Job postings revealing hidden infrastructure problems companies are hiring for\n\n"
                "2. Identify 10-15 distinct opportunity areas. Bias toward non-obvious. For each, "
                "explicitly tag the TIMING SIGNAL TYPE — choose ONE of these categories:\n"
                "   - REGULATORY_SHIFT: new law/standard creates a forced buying moment\n"
                "   - TECHNOLOGY_UNLOCK: a capability that wasn't possible 24 months ago\n"
                "   - BEHAVIORAL_CHANGE: user habits shifted (remote work, AI adoption, etc.)\n"
                "   - COST_COLLAPSE: something previously expensive became cheap\n"
                "   - DISTRIBUTION_UNLOCK: new channel that reaches customers cheaply\n"
                "   - INCUMBENT_FAILURE: a big player got worse, abandoned a segment, or got sued\n"
                "   If you can't tag a clear timing signal, the opportunity is probably stale — drop it.\n\n"
                "3. Provide for EACH opportunity:\n"
                "   - A clear name and 2-sentence description\n"
                "   - timing_signal_type (one of the 6 categories above)\n"
                "   - timing_signal: the specific evidence (article, regulation, product launch, etc.)\n"
                "   - At least one named company or data point as evidence\n"
                "   - non_obviousness_check: would 90% of analysts list this opportunity? (yes/no)\n"
                "     If yes, you must justify why it's still worth listing OR replace it.\n\n"
                "4. Map the overall market landscape:\n"
                "   - Total market size with source\n"
                "   - Growth rate with source\n"
                "   - Key players and their positions\n"
                "   - Major trends driving change\n\n"
                "QUALITY STANDARDS:\n"
                "- Every market size claim must cite a source by name\n"
                "- Every opportunity must reference at least one real company or data point\n"
                "- Do NOT fabricate data. If you can't find reliable data, say so.\n"
                "- Use web search for EVERY major claim — do not rely on training data alone\n"
                "- At least 5 of the 10-15 opportunities should be NON-OBVIOUS (non_obviousness_check = no)\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "market_size": "string — total market size with source",\n'
                '  "growth_rate": "string — CAGR or growth rate with source",\n'
                '  "landscape_summary": "string — 3-4 paragraph market overview",\n'
                '  "key_players": [{{"name": "string", "description": "string", "estimated_revenue_or_funding": "string"}}],\n'
                '  "opportunities": [\n'
                '    {{\n'
                '      "name": "string",\n'
                '      "description": "string",\n'
                '      "timing_signal_type": "REGULATORY_SHIFT|TECHNOLOGY_UNLOCK|BEHAVIORAL_CHANGE|COST_COLLAPSE|DISTRIBUTION_UNLOCK|INCUMBENT_FAILURE",\n'
                '      "timing_signal": "string — specific evidence with source",\n'
                '      "evidence": "string — named company or data point",\n'
                '      "non_obviousness_check": "yes|no",\n'
                '      "non_obviousness_justification": "string — only required if non_obviousness_check is yes"\n'
                '    }}\n'
                '  ],\n'
                '  "macro_trends": ["string — trend with supporting data"],\n'
                '  "sources_consulted": ["string — name of report/article/forum/repo searched"]\n'
                '}}'
            ),
            "output_key": "landscape",
            "timeout_override": 900,
            "max_retries": 2,
            "output_schema": "startup_landscape_v1",
            "model_override": "claude-opus-4-7",
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
                "Deep research mode: {deep_mode}\n\n"
                "DEEP RESEARCH MODE: If 'Deep research mode' is 'true', the user is on Claude Max "
                "and wants more thorough coverage. Select 10 opportunities instead of 7-8. "
                "Run more competitor searches per opportunity. Dig deeper on unit economics.\n\n"
                "INSTRUCTIONS:\n"
                "1. Select the 7-8 most promising opportunities from the landscape scan. Bias toward "
                "ones with non_obviousness_check = 'no' (the non-obvious ones).\n\n"
                "2. For EACH opportunity, use web search to find:\n\n"
                "   a) COMPETITORS: Name every funded startup in this exact niche.\n"
                "      - Company name, founding year, HQ\n"
                "      - Total funding raised and last round (search Crunchbase, TechCrunch)\n"
                "      - Current status (active, acquired, shut down)\n"
                "      - What they do specifically\n"
                "      - IMPORTANT: If you find ZERO competitors, do NOT skip — instead classify why:\n"
                "        * 'overlooked' = real demand exists but nobody has built it (GREEN FLAG)\n"
                "        * 'no_demand' = nobody built it because nobody wants it (RED FLAG)\n"
                "        * 'too_hard' = tried and failed due to technical/regulatory barriers\n"
                "        * 'too_small' = market is real but too small to attract VC competitors\n"
                "      Provide evidence for whichever classification you pick.\n\n"
                "   b) MARKET SIZING: Find at least 2 independent market size estimates.\n"
                "      - Cite the research firm and report name\n"
                "      - Note TAM vs SAM vs SOM where possible\n\n"
                "   c) DEMAND EVIDENCE (tiered): Classify each demand signal you find as one of:\n"
                "      - HOT: paying customers actively complaining about a gap (Reddit threads with\n"
                "        '$X/mo for this would be a no-brainer', G2 reviews citing missing features,\n"
                "        people DIY-ing the solution with spreadsheets)\n"
                "      - WARM: active discussion or upvoted threads about the problem, but no\n"
                "        explicit purchase intent yet (HN comments, subreddit posts)\n"
                "      - COLD: theoretical interest only (analyst reports, 'this would be cool' tweets)\n"
                "      Aim for at least 2 HOT or WARM signals per opportunity. If you can only find\n"
                "      COLD signals, mark evidence_strength accordingly.\n\n"
                "   d) UNIT ECONOMICS: Build a structured economics estimate (don't just say 'pricing\n"
                "      varies'). For each opportunity, estimate:\n"
                "      - typical_price_point: e.g. '$29-99/month', '$0.10/API call', '$2000 one-time'\n"
                "      - billing_model: subscription | usage | one_time | freemium | marketplace_take\n"
                "      - cac_channel: most likely customer acquisition channel (SEO, cold outbound,\n"
                "        partnerships, communities, paid ads, viral). Be specific.\n"
                "      - gross_margin_signal: high (>80%, pure software) | medium (50-80%, has API\n"
                "        or infra costs) | low (<50%, services/marketplace)\n"
                "      Base on observed competitor pricing where possible.\n\n"
                "   e) EARLY FAILURE SIGNAL: Find at least ONE specific risk or red flag for each\n"
                "      opportunity now (don't wait for the contrarian step). What's the most\n"
                "      concerning thing you noticed during research?\n\n"
                "   f) FOUNDER/TEAM PATTERNS: For each opportunity, briefly note who founded the\n"
                "      2-3 best-funded competitors and look for a pattern. Common archetypes:\n"
                "      - DOMAIN_EXPERT: founders worked in the industry 5+ years before starting\n"
                "      - TECHNICAL: engineering/research background, sometimes from the relevant\n"
                "        platform (e.g. ex-Google for cloud tools, ex-Stripe for payments)\n"
                "      - REPEAT: prior exit or successful previous startup\n"
                "      - FIRST_TIME: first-time founders, often younger\n"
                "      - MIXED: a clear blend (e.g. domain expert + technical co-founder)\n"
                "      Summarize the dominant pattern in 1-2 sentences. This signals which kinds\n"
                "      of founders are succeeding in this niche, and helps the user judge fit.\n\n"
                "3. Do NOT skip web search for any opportunity. Each one needs fresh data.\n\n"
                "QUALITY STANDARDS:\n"
                "- Name real companies with real funding amounts\n"
                "- Cross-reference market sizes across multiple sources\n"
                "- Tier every demand signal as HOT/WARM/COLD\n"
                "- Every opportunity gets an early failure signal — no opportunity is risk-free\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "deep_dive_opportunities": [\n'
                '    {{\n'
                '      "name": "string",\n'
                '      "description": "string — 3-5 sentences",\n'
                '      "competitors": [{{"name": "string", "funding": "string", "founded": "string", "status": "string", "what_they_do": "string"}}],\n'
                '      "no_competitors_classification": "overlooked|no_demand|too_hard|too_small|null — only set if competitors array is empty",\n'
                '      "no_competitors_evidence": "string — only required if no_competitors_classification is set",\n'
                '      "market_size_estimates": [{{"source": "string", "estimate": "string", "year": "string"}}],\n'
                '      "demand_signals": [\n'
                '        {{"tier": "HOT|WARM|COLD", "source": "string — URL/forum/quote", "signal": "string — what was said or seen"}}\n'
                '      ],\n'
                '      "unit_economics": {{\n'
                '        "typical_price_point": "string",\n'
                '        "billing_model": "subscription|usage|one_time|freemium|marketplace_take",\n'
                '        "cac_channel": "string — specific channel",\n'
                '        "gross_margin_signal": "high|medium|low"\n'
                '      }},\n'
                '      "founder_patterns": "string — 1-2 sentence summary of the dominant founder archetype in this niche (DOMAIN_EXPERT, TECHNICAL, REPEAT, FIRST_TIME, or MIXED) and what it implies",\n'
                '      "early_failure_signal": "string — most concerning red flag noticed during research",\n'
                '      "evidence_strength": "strong|moderate|weak",\n'
                '      "initial_assessment": "string — 2-3 sentence preliminary take"\n'
                '    }}\n'
                '  ],\n'
                '  "dropped_opportunities": [{{"name": "string", "reason": "string — why this was cut from the deep dive"}}]\n'
                '}}'
            ),
            "output_key": "deep_dive",
            "condition": {"field": "landscape", "operator": "not_empty"},
            "timeout_override": 1800,
            "max_retries": 2,
            "output_schema": "startup_deep_dive_v1",
            "model_override": "claude-opus-4-7",
        },
        # ──────────────────────────────────────────────────
        # Step 2: Contrarian analysis — why would these FAIL?
        # ──────────────────────────────────────────────────
        {
            "name": "contrarian_analysis",
            "job_type": "research",
            "prompt_template": (
                "You are a skeptical venture capital partner reviewing startup opportunities. "
                "Your job is to STRESS TEST every opportunity — find the reasons each one could fail. "
                "Vague risks are useless; every claim needs a specific name, date, or source.\n\n"
                "DEEP DIVE RESEARCH:\n{deep_dive}\n\n"
                "INSTRUCTIONS:\n"
                "For EACH opportunity in the deep dive, use web search to investigate:\n\n"
                "1. NAMED FAILURE PATTERNS: Find SPECIFIC startups that died in this space.\n"
                "   - Required: company name + year shut down/pivoted + specific reason\n"
                "   - Do NOT say 'many startups failed' — name them or omit the claim\n"
                "   - Search: '[domain] startup shutdown', '[domain] post-mortem', failory.com,\n"
                "     'lessons learned [niche]', acquired/dead startup databases\n"
                "   - If you genuinely cannot find any failures after searching, say so explicitly\n"
                "     (this is itself meaningful — either too new or nobody tried)\n\n"
                "2. INCUMBENT THREAT (5-year look-back required): How could big players kill this?\n"
                "   - Identify the 3-5 most likely incumbents (Google, Microsoft, Amazon, Meta, Apple,\n"
                "     Salesforce, Adobe, Stripe, OpenAI, Anthropic, dominant vertical players)\n"
                "   - For each, search '[Incumbent] + [domain]' for the LAST 24 MONTHS of activity\n"
                "   - Cite specific announcements, product launches, acquisitions, or job postings\n"
                "   - 'Could build it as a feature' is too speculative — find evidence they're already\n"
                "     moving in this direction OR explain why they structurally won't\n\n"
                "3. MARKET HEADWINDS:\n"
                "   - Is the market actually growing or is the projection stale? Cross-check.\n"
                "   - Is there CAC evidence that makes this unviable? (Compare to LTV from unit_economics)\n"
                "   - Are user behaviors shifting AWAY from this category?\n\n"
                "4. REGULATORY CHECKLIST: First, self-identify if this domain is REGULATED:\n"
                "   - Fintech / payments / lending / crypto → CFPB, SEC, state money transmitter laws\n"
                "   - Healthcare / medical / wellness data → HIPAA, FDA, state telehealth laws\n"
                "   - Education / K-12 → FERPA, COPPA, state-level requirements\n"
                "   - Children's products → COPPA, age verification\n"
                "   - EU users → GDPR, AI Act, DSA\n"
                "   - Hiring / HR / employment → EEOC, state AI hiring laws (NYC, Illinois, etc.)\n"
                "   - Insurance, real estate, legal, tax → state-by-state licensing\n"
                "   For each opportunity in a regulated domain, search for 'recent enforcement [domain]'\n"
                "   and 'pending regulation [domain]' and report concrete findings.\n"
                "   For non-regulated domains, set regulatory_risk to 'none_identified'.\n\n"
                "5. TECHNICAL RISKS:\n"
                "   - Is the core technology actually ready? Cite the limiting factor.\n"
                "   - Are there unsolved hard problems (latency, accuracy, cost-per-call)?\n"
                "   - Could the solution be commoditized within 12 months?\n\n"
                "6. KILL SCENARIO PROBABILITY: Beyond the kill_scenario string, assign a probability:\n"
                "   - LOW: <25% chance this kills the startup in year 1\n"
                "   - MEDIUM: 25-60% chance\n"
                "   - HIGH: >60% chance — should probably be a 'killed' verdict\n\n"
                "7. VERDICT: Classify each opportunity:\n"
                "   - SURVIVES: Holds up under scrutiny, kill probability LOW\n"
                "   - WEAKENED: Still viable but with significant caveats, kill probability MEDIUM\n"
                "   - KILLED: Fatal flaws found, kill probability HIGH\n\n"
                "Be ruthlessly honest. Vague risks help nobody. Every claim needs a name, a date, or a URL.\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "contrarian_analyses": [\n'
                '    {{\n'
                '      "name": "string",\n'
                '      "failed_predecessors": [{{"company": "string", "year": "string", "what_happened": "string", "lesson": "string"}}],\n'
                '      "incumbent_threats": [\n'
                '        {{"incumbent": "string", "evidence": "string — specific announcement/launch/posting in last 24 months", "source": "string — URL or article name"}}\n'
                '      ],\n'
                '      "market_headwinds": ["string — specific headwind with source"],\n'
                '      "regulatory_risk": {{\n'
                '        "is_regulated_domain": true,\n'
                '        "regulatory_bodies": ["string — e.g. CFPB, HIPAA, GDPR"],\n'
                '        "specific_risks": ["string — concrete enforcement actions or pending rules"],\n'
                '        "compliance_burden": "low|medium|high"\n'
                '      }},\n'
                '      "technical_risks": ["string — specific risk with evidence"],\n'
                '      "kill_scenario": "string — the most likely way this startup dies",\n'
                '      "kill_probability": "low|medium|high",\n'
                '      "verdict": "survives|weakened|killed",\n'
                '      "verdict_reasoning": "string — 3-5 sentences explaining the verdict"\n'
                '    }}\n'
                '  ],\n'
                '  "summary": "string — overall assessment of which opportunities survived scrutiny"\n'
                '}}'
            ),
            "output_key": "contrarian",
            "condition": {"field": "deep_dive", "operator": "not_empty"},
            "timeout_override": 1800,
            "max_retries": 2,
            "output_schema": "startup_contrarian_v1",
            "model_override": "claude-opus-4-7",
            # Round 3: recovery loop. If contrarian leaves fewer than 3
            # surviving (verdict in [survives, weakened]) opportunities,
            # loop back to landscape_scan. The landscape prompt detects
            # the previous_attempt_killed_all flag and broadens its search.
            "loop_to": 0,
            "max_loop_count": 2,
            "loop_condition": {
                "field": "contrarian",
                "operator": "survivor_count_below",
                "value": "3",
            },
        },
        # ──────────────────────────────────────────────────
        # Step 3: Freshness decay check
        # ──────────────────────────────────────────────────
        # The landscape + deep_dive + contrarian research can span 30-60
        # minutes of wall-clock; in fast-moving categories (AI tooling,
        # dev infrastructure) incumbents ship meaningful competitive
        # moves on that timescale. Run one narrow 30-day news pass over
        # the survivors before synthesis so the ranking reflects what's
        # true today, not what was true when landscape ran.
        {
            "name": "freshness_check",
            "job_type": "research",
            "prompt_template": (
                "You are a research analyst doing a final 30-day freshness pass on the "
                "opportunities that survived contrarian review. The earlier research may "
                "have data that's weeks stale — your job is to catch recent incumbent "
                "moves that would materially change a surviving opportunity's verdict.\n\n"
                "CONTRARIAN OUTPUT:\n{contrarian}\n\n"
                "INSTRUCTIONS:\n"
                "For EACH opportunity with verdict 'survives' or 'weakened', use web "
                "search restricted to the LAST 30 DAYS to check for:\n"
                "1. New product launches, GA announcements, or strategic acquisitions by "
                "the named incumbents from the contrarian analysis.\n"
                "2. Funding rounds that give an incumbent a war chest aimed at this wedge.\n"
                "3. Regulatory enforcement updates that change the underlying timing signal "
                "(e.g., an enforcement date slipped, a standard got adopted earlier than "
                "expected, a rule got rescinded).\n"
                "4. Anything else that wasn't true when the landscape/deep_dive ran but is "
                "true now.\n\n"
                "CLASSIFY each opportunity:\n"
                "- STABLE: no material change in the last 30 days. Original verdict holds.\n"
                "- WEAKENED_FURTHER: material move narrows the window but doesn't kill.\n"
                "  Synthesis should deduct 5-10 points from its total_score.\n"
                "- KILLED_POST_CONTRARIAN: incumbent move eliminates the wedge. Synthesis "
                "  MUST drop this from final_rankings.\n\n"
                "QUALITY RULES:\n"
                "- Every non-STABLE classification MUST cite a specific URL + date of the "
                "news item that triggered the downgrade. No handwaving.\n"
                "- Default to STABLE if you can't find specific 30-day evidence. Do not "
                "downgrade based on speculation.\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "freshness_results": [\n'
                '    {{\n'
                '      "name": "string — opportunity name exactly as in contrarian",\n'
                '      "status": "STABLE|WEAKENED_FURTHER|KILLED_POST_CONTRARIAN",\n'
                '      "evidence": "string — source URL + date + one-sentence summary, or null if STABLE",\n'
                '      "impact": "string — one sentence on how this changes the verdict"\n'
                '    }}\n'
                '  ],\n'
                '  "scan_notes": "string — 1-2 sentences on what you searched and what you found overall"\n'
                '}}'
            ),
            "output_key": "freshness",
            "condition": {"field": "contrarian", "operator": "not_empty"},
            "timeout_override": 900,
            "max_retries": 1,
            "output_schema": "startup_freshness_v1",
            # Freshness is a narrow targeted web-search pass (~5-10 queries
            # over a known shortlist). Opus earns its price here because
            # the "is this news material?" judgment calls matter.
            "model_override": "claude-opus-4-7",
        },
        # ──────────────────────────────────────────────────
        # Step 4: Final synthesis and ranking
        # ──────────────────────────────────────────────────
        {
            "name": "synthesis_and_ranking",
            "job_type": "research",
            "prompt_template": (
                "You are a startup strategist producing a final investment-grade analysis for a "
                "SOLO DEVELOPER. Synthesize all previous research into a definitive, comparative ranking.\n\n"
                "LANDSCAPE:\n{landscape}\n\n"
                "DEEP DIVE:\n{deep_dive}\n\n"
                "CONTRARIAN ANALYSIS:\n{contrarian}\n\n"
                "FRESHNESS CHECK (last-30-day incumbent moves):\n{freshness}\n\n"
                "Deep research mode: {deep_mode}\n\n"
                "DEEP RESEARCH MODE: If 'Deep research mode' is 'true', the user is on Claude Max. "
                "Rank 7 opportunities in final_rankings instead of 3-5, and write MVP specs for "
                "all of them (not just the top 5).\n\n"
                "INSTRUCTIONS:\n"
                "1. Drop every opportunity that either (a) got a 'killed' verdict in the "
                "contrarian step, or (b) was marked KILLED_POST_CONTRARIAN by the freshness "
                "check. Both are exclusion signals of equal weight. Include only the rest "
                "('survives' or 'weakened' in contrarian AND not KILLED_POST_CONTRARIAN in "
                "freshness).\n\n"
                "2. Score each surviving opportunity on five dimensions (integer 1-10). Use these "
                "ANCHORS so scores are comparable across runs — do not invent your own scale:\n\n"
                "   market_timing (is NOW the right moment?)\n"
                "     1 = market is dead, declining, or 5+ years too early\n"
                "     5 = stable market, no obvious tailwind or headwind\n"
                "     8 = clear timing signal in last 12 months (regulation, tech unlock, behavior shift)\n"
                "     10 = inflection point happening RIGHT NOW with multiple converging signals\n\n"
                "   defensibility (DERIVED — do not score directly; see moat derivation in step 3)\n"
                "     1 = pure commodity, anyone can clone in a weekend\n"
                "     5 = some workflow lock-in or modest switching cost\n"
                "     8 = real moat in at least one dimension (network, data, distribution)\n"
                "     10 = strong moats in 2+ dimensions, proven hard to displace\n\n"
                "   solo_dev_feasibility (can ONE person build a real MVP in <8 weeks?)\n"
                "     1 = needs a team, hardware, or 6+ months of work\n"
                "     5 = doable but tight; requires niche expertise\n"
                "     8 = standard web/API stack, 4-6 weeks for a competent solo dev\n"
                "     10 = trivially buildable with off-the-shelf tools in <2 weeks\n\n"
                "   revenue_potential (path to $10K+ MRR within 12 months)\n"
                "     1 = no clear willingness to pay, tiny market, or pure hobby\n"
                "     5 = plausible $1-3K MRR with significant effort\n"
                "     8 = clear comparable players hitting $10K+ MRR with similar scope\n"
                "     10 = obvious paying demand, short sales cycle, $20K+ MRR realistic\n\n"
                "   evidence_quality (how strong is the supporting data from prior steps?)\n"
                "     1 = mostly speculation, no named sources\n"
                "     5 = a few cited sources, some demand signals\n"
                "     8 = multiple independent sources, named competitors with funding, real demand\n"
                "     10 = paying customers visibly complaining, multiple $10M+ funded competitors\n\n"
                "3. For each surviving opportunity, build a MOATS taxonomy. Rate each moat "
                "type on an integer 1-10 scale (NOT qualitative none/weak/strong) with a "
                "one-sentence justification. Use these anchors:\n"
                "   1 = none — commodity in this dimension, zero lock-in\n"
                "   3 = weak — token friction, any competitor removes it in a week\n"
                "   5 = moderate — workflow lock-in or modest switching cost\n"
                "   7 = strong — real moat that takes months to replicate\n"
                "   10 = durable — structurally hard to copy (regulatory license, exclusive\n"
                "        distribution partnership, proprietary data flywheel with 12+ months\n"
                "        of accumulated advantage, patented tech)\n\n"
                "   Rate each of:\n"
                "   - network_effects: does value grow with more users? (1-10)\n"
                "   - switching_costs: how painful to leave once adopted? (1-10)\n"
                "   - data_advantage: does proprietary data improve the product over time? (1-10)\n"
                "   - brand_or_trust: does brand reputation create a buying preference? (1-10)\n"
                "   - distribution_lock: privileged access to a channel competitors can't reach? (1-10)\n\n"
                "   DEFENSIBILITY DERIVATION: set the defensibility dimension score (used in the\n"
                "   total_score formula) as follows: take the TOP TWO moat ratings, average\n"
                "   them, and round to the nearest integer. This rewards concentrated moat\n"
                "   strength — having one strong moat (7) plus one moderate (5) averages to 6,\n"
                "   which is the right signal for a genuinely defensible solo-dev play. Having\n"
                "   five weak moats (all 3) averages to 3, correctly reflecting commodity risk.\n"
                "   Do NOT default every moat to 3 out of conservatism; rate honestly against\n"
                "   the anchors. A product with an exclusive association endorsement or a\n"
                "   regulated-license buyer relationship genuinely scores 8+ on distribution_lock.\n\n"
                "4. Compute a WEIGHTED total score on a 0-100 scale using these weights "
                "for a solo dev (weights sum to 10.0, so max = 10 * 10 = 100):\n"
                "   total_score = (solo_dev_feasibility * 3.0) + (revenue_potential * 3.0) + \n"
                "                 (market_timing * 2.0) + (defensibility * 1.5) + (evidence_quality * 0.5)\n"
                "   Round to one decimal. Solo dev feasibility and revenue potential matter most.\n"
                "   FRESHNESS DEDUCTION: if the opportunity was marked WEAKENED_FURTHER by the\n"
                "   freshness check, deduct 5-10 points from total_score (depending on how\n"
                "   severe the incumbent move was). Cite the deduction in head_to_head or\n"
                "   surviving_risks. Opportunities marked STABLE get no deduction.\n"
                "   Do NOT inflate dimension scores to hit a target total — score each dimension\n"
                "   honestly against its anchor, then let the formula produce whatever total it\n"
                "   produces. A realistic surviving opportunity will typically land in the 55-80\n"
                "   range; scores above 85 should be rare.\n\n"
                "5. RANK opportunities by weighted total_score (highest first). For each ranked "
                "opportunity, also write a 'head_to_head' field explaining WHY it beats the opportunity "
                "ranked one position below it (the lowest-ranked one explains why it still made the cut).\n"
                "   This forces real comparison instead of isolated scoring.\n\n"
                "6. For the top 5, write a STRICT MVP specification. An MVP here means:\n"
                "   'Deployable software with at least one real user-facing feature that solves the "
                "core problem end-to-end.' NOT a landing page. NOT a mockup. NOT a waitlist.\n\n"
                "   Each MVP spec must include:\n"
                "   - what_to_build: concrete features (not vague descriptions)\n"
                "   - core_user_journey: the ONE workflow the MVP must demonstrate end-to-end\n"
                "   - tech_stack: specific frameworks/services\n"
                "   - build_time_weeks: realistic estimate for solo dev (be honest, not optimistic)\n"
                "   - first_customers: 3 specific customer types reachable without paid ads\n"
                "   - validation_approach: how to validate paying demand BEFORE building\n"
                "   - out_of_scope: 3 features explicitly NOT in the MVP (prevents scope creep)\n"
                "   - success_metric: how you'll know post-launch if the MVP is working\n"
                "   - risky_assumption: the ONE belief that, if wrong, kills the idea\n\n"
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
                '      "moats": {{\n'
                '        "network_effects": {{"rating": 4, "justification": "string"}},\n'
                '        "switching_costs": {{"rating": 6, "justification": "string"}},\n'
                '        "data_advantage": {{"rating": 7, "justification": "string"}},\n'
                '        "brand_or_trust": {{"rating": 3, "justification": "string"}},\n'
                '        "distribution_lock": {{"rating": 8, "justification": "string"}}\n'
                '      }},\n'
                '      "total_score": 72.0,\n'
                '      "head_to_head": "string — why this beats the next-ranked opportunity",\n'
                '      "surviving_risks": ["string — risks that remain after contrarian analysis"],\n'
                '      "mvp_spec": {{\n'
                '        "what_to_build": "string — specific features",\n'
                '        "core_user_journey": "string — the one end-to-end workflow",\n'
                '        "tech_stack": "string",\n'
                '        "build_time_weeks": 4,\n'
                '        "first_customers": ["string — specific reachable customer types"],\n'
                '        "validation_approach": "string — how to validate paying demand pre-build",\n'
                '        "out_of_scope": ["string — feature 1 NOT in MVP", "string — feature 2", "string — feature 3"],\n'
                '        "success_metric": "string — how to know post-launch if it is working",\n'
                '        "risky_assumption": "string — the one belief that if wrong kills it"\n'
                '      }}\n'
                '    }}\n'
                '  ],\n'
                '  "executive_summary": "string — 2-3 paragraph final recommendation with reasoning"\n'
                '}}'
            ),
            "output_key": "synthesis",
            "condition": {"field": "contrarian", "operator": "not_empty"},
            "timeout_override": 1200,
            "max_retries": 2,
            "output_schema": "startup_synthesis_v1",
            # Synthesis is aggregation + reasoning over ~150k tokens of
            # already-researched output; it doesn't need Opus's raw depth.
            # Sonnet follows instructions reliably on structured output at
            # ~1/5 the input cost and ~1/5 the output cost.
            "model_override": "claude-opus-4-7",
        },
        # ──────────────────────────────────────────────────
        # Step 5: Pre-sale validation plan for top 3 picks
        # ──────────────────────────────────────────────────
        # The synthesis produces a ranking; the actual next action for
        # the user is not "build the MVP" but "validate paying demand
        # before building." This step turns the ranking into a concrete
        # 4-week pre-sale playbook so the approval gate presents the
        # user with a ready-to-execute plan, not just a rank-ordered list.
        {
            "name": "validation_plan",
            "job_type": "research",
            "prompt_template": (
                "You are a GTM strategist producing a 4-week PRE-SALE validation plan for "
                "the top 3 opportunities in the synthesis. The plan's goal is to confirm "
                "paying demand BEFORE the founder writes production code — via pre-sales, "
                "letters of intent, or annual-plan deposits.\n\n"
                "SYNTHESIS:\n{synthesis}\n\n"
                "For EACH of the top 3 ranked opportunities, produce a validation plan with:\n\n"
                "1. specific_outreach_targets: 5-10 NAMED companies or individuals reachable\n"
                "   WITHOUT paid ads. For each, include:\n"
                "   - name: company name OR an individual's name + role\n"
                "   - why_them: one-sentence match against the opportunity's ICP\n"
                "   - reachable_via: LinkedIn DM / community post / warm intro / newsletter reply\n"
                "   Do NOT list 'CPA firms' — name 3-5 specific firms. Specificity is the\n"
                "   whole point.\n\n"
                "2. contact_channel: the PRIMARY channel for outreach (one of: LinkedIn DM,\n"
                "   Slack community, Reddit subreddit post, cold email, warm intro via X).\n\n"
                "3. cold_message_script: 80-150 word opener. Must:\n"
                "   - Lead with a specific pain from the deep_dive research (not generic)\n"
                "   - Reference a named competitor or specific workflow\n"
                "   - End with a binary ask ('would you pay $X/mo for this before I build it?')\n"
                "   - NOT start with 'Hi, hope you're well' or any other generic greeting\n\n"
                "4. disqualification_criteria: 3 specific conditions that should make the\n"
                "   founder DROP this idea. Each must be a testable fact, e.g., '<3 of 10\n"
                "   contacted respond within 7 days' or 'nobody agrees to a $99 annual\n"
                "   pre-sale deposit.'\n\n"
                "5. go_no_go_metric: the SINGLE number at end-of-week-4 that triggers\n"
                "   build-or-drop. Format: '≥N <thing>, else drop.' Example: '≥5 signed\n"
                "   letters of intent at $99/mo annual pre-pay, else drop.'\n\n"
                "6. expected_signal_timeline: 3-4 short sentences describing what you expect\n"
                "   by end of week 1, week 2, and week 4. Ground expectations in realistic\n"
                "   response rates for the channel (e.g., cold LinkedIn ~8-12%, warm intro\n"
                "   ~40-60%).\n\n"
                "QUALITY RULES:\n"
                "- No handwaving. 'Reach out to CPAs' is not acceptable. 'DM these 7 named\n"
                "  CPAs sourced from the deep_dive research' is.\n"
                "- Every pre-sale ask must be a concrete dollar amount, not 'some amount.'\n"
                "- The go_no_go_metric must be passable or failable — not 'get feedback.'\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "validation_plans": [\n'
                '    {{\n'
                '      "rank": 1,\n'
                '      "name": "string — must match a name from synthesis.final_rankings",\n'
                '      "specific_outreach_targets": [\n'
                '        {{"name": "string", "why_them": "string", "reachable_via": "string"}}\n'
                '      ],\n'
                '      "contact_channel": "string",\n'
                '      "cold_message_script": "string — 80-150 words",\n'
                '      "disqualification_criteria": ["string — testable fact"],\n'
                '      "go_no_go_metric": "string — single binary metric",\n'
                '      "expected_signal_timeline": "string — week-by-week expectations"\n'
                '    }}\n'
                '  ],\n'
                '  "cross_cutting_notes": "string — 1-2 sentences on anything the founder '
                'should know before starting all three validations in parallel"\n'
                '}}'
            ),
            "output_key": "validation_plans",
            "condition": {"field": "synthesis", "operator": "not_empty"},
            "timeout_override": 900,
            "max_retries": 1,
            "output_schema": "startup_validation_v1",
            "context_inputs": ["synthesis"],
            # Validation plans are concrete GTM reasoning — Sonnet is
            # strong here and already has the synthesis context cached.
            "model_override": "claude-opus-4-7",
        },
        # ──────────────────────────────────────────────────
        # Step 6: User approval gate
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
                "Build an MVP for the startup opportunity selected by the user.\n\n"
                "SELECTED OPPORTUNITY:\n{selected_idea}\n\n"
                "SCOPE RULES — READ CAREFULLY:\n"
                "1. Build EXACTLY the opportunity above. The user has already selected it from a "
                "ranked list during the approval gate, so do not second-guess the choice.\n"
                "2. Use ONLY this opportunity's mvp_spec as your specification. In particular:\n"
                "   - what_to_build → these are your features\n"
                "   - core_user_journey → this is the ONE workflow that MUST work end-to-end\n"
                "   - tech_stack → use this stack unless there is a hard technical reason not to\n"
                "   - out_of_scope → these features are FORBIDDEN. Do not add them even if tempting.\n"
                "   - success_metric → instrument the code so this metric can be measured post-launch\n"
                "   - risky_assumption → the build should make this assumption testable as fast as possible\n\n"
                "3. MVP DEFINITION (non-negotiable): 'Deployable software with at least one real "
                "user-facing feature that solves the core problem end-to-end.' This means:\n"
                "   - NOT a landing page with a waitlist\n"
                "   - NOT a mockup or design file\n"
                "   - NOT a coming-soon page\n"
                "   - YES a working app/API/CLI that a real user could use today\n\n"
                "REQUIREMENTS (every file must exist or the build is rejected):\n"
                "- Complete project with all dependencies installed\n"
                "- Core features implemented and WORKING (not stubs, not TODOs)\n"
                "- The core_user_journey from the spec must work end-to-end\n"
                "- API endpoints if it's a backend service\n"
                "- Basic UI if applicable\n"
                "- README.md with: what it does, how to set up, how to run, environment variables needed\n"
                "- Dockerfile for deployment\n"
                "- .env.example with all required environment variables documented\n"
                "- BUILD_DECISIONS.md (REQUIRED — build is rejected if missing) explaining: "
                "(a) why you chose the tech stack you used, "
                "(b) any tradeoffs you made, (c) what you intentionally did NOT build (echo the "
                "out_of_scope list from the spec), (d) how a future user would test the risky_assumption\n\n"
                "Make it real. Someone should be able to clone this repo and have a working product "
                "in 5 minutes. If it can't pass that test, it isn't an MVP — it's a prototype."
            ),
            "output_key": "mvp_result",
            "condition": {"field": "synthesis", "operator": "not_empty"},
            "timeout_override": 2400,
            "max_retries": 1,
            "context_inputs": ["selected_idea"],
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
                "You are a side hustle automation researcher hunting for NON-OBVIOUS "
                "opportunities that can be largely or fully automated with n8n. Your "
                "goal is to surface ideas that 90% of researchers would miss.\n\n"
                "Focus: {focus}\n"
                "Budget: {budget}\n"
                "Skills: {skills}\n"
                "Constraints: {constraints}\n"
                "Deep research mode: {deep_mode}\n\n"
                "KNOWN FACTS FROM PRIOR PIPELINE RUNS — read these first. They contain\n"
                "regulatory dates, funded competitors, recent incumbent moves, and 'dead\n"
                "playbook' patterns already learned from earlier runs across startup AND\n"
                "side-hustle domains. Use them to (a) skip rediscovering the same facts\n"
                "via web search, (b) avoid hustles that match a dead_playbooks pattern\n"
                "(e.g., 'thin AI wrapper over QBO' won't survive here either), (c) weight\n"
                "income_evidence and timing signals more accurately. If a fact applies to\n"
                "your focus area, cite it by name in the relevant opportunity:\n"
                "{known_facts}\n\n"
                "DEEP RESEARCH MODE: If 'Deep research mode' is 'true', the user is on a "
                "Claude Max subscription and wants a more thorough pass. Aim for 8-10 "
                "opportunities (instead of 6-8), lean more heavily on contrarian sources, "
                "and dig deeper into income evidence. Include at least 6 NON-OBVIOUS "
                "opportunities (not 4). DO NOT exceed 10 — downstream feasibility evaluation "
                "has a hard output token budget and will truncate if you exceed it.\n\n"
                "INSTRUCTIONS:\n"
                "1. Use web search across DIVERSE source types. Don't just read "
                "'passive income' blogs — they're saturated and the good ideas are "
                "already gone. Search:\n"
                "   a) Mainstream sources (for sizing only):\n"
                "      - Grand View Research, IBISWorld, Statista reports on relevant markets\n"
                "      - Recent crunchbase / product hunt launches in the niche\n"
                "   b) CONTRARIAN sources (for non-obvious opportunities):\n"
                "      - Reddit niche subreddits where people post revenue screenshots "
                "(r/juststart, r/SideProject, r/SaaS, r/entrepreneur, domain-specific subs)\n"
                "      - IndieHackers.com public revenue pages (sort by verified MRR)\n"
                "      - Twitter 'build in public' threads with actual Stripe/payment screenshots\n"
                "      - YouTube Shorts titled 'how I make $X/month automated' (bias toward channels "
                "with under 10K subs — those are closer to ground truth)\n"
                "      - GitHub trending repos in automation/scraping/integration space\n"
                "      - Hacker News 'Ask HN' and 'Show HN' threads about automated revenue\n"
                "      - Job postings asking for 'n8n automation consultant' — reveals what "
                "businesses are willing to pay to automate\n\n"
                "2. Identify 6-8 distinct opportunities. Bias toward non-obvious. For "
                "each, explicitly tag the TIMING SIGNAL TYPE — choose ONE of these 6 "
                "categories (mirrors the startup pipeline taxonomy):\n"
                "   - REGULATORY_SHIFT: new law/rule creates a forced workflow need\n"
                "   - TECHNOLOGY_UNLOCK: a capability (new API, cheaper GPU, LLM) that wasn't "
                "possible 24 months ago\n"
                "   - BEHAVIORAL_CHANGE: user habits shifted (creator economy, remote work, "
                "newsletter adoption)\n"
                "   - COST_COLLAPSE: something previously expensive became cheap "
                "(LLM inference, cloud hosting, API access)\n"
                "   - DISTRIBUTION_UNLOCK: new channel reaching customers cheaply "
                "(TikTok Shop, Substack, WhatsApp Business API)\n"
                "   - INCUMBENT_FAILURE: a big player got worse, abandoned a segment, "
                "raised prices, or got sued\n"
                "   If you can't tag a clear timing signal, the opportunity is probably "
                "stale — drop it.\n\n"
                "3. For each opportunity, provide:\n"
                "   - name: 2-5 word label\n"
                "   - description: 2-3 sentences on what the hustle is and how it works "
                "end-to-end\n"
                "   - automation_approach: specifically how n8n would automate this. "
                "Name real n8n node types if possible (HTTP Request, Webhook, Schedule "
                "Trigger, IF, Code, Set).\n"
                "   - timing_signal_type: one of the 6 categories above\n"
                "   - timing_signal: the specific evidence (article, regulation, launch)\n"
                "   - income_evidence: at least ONE cited revenue claim with URL. Must be "
                "a verifiable source: a Stripe screenshot, IndieHackers MRR page, Reddit "
                "post with proof, or YouTube video with visible payout dashboard. NOT 'people "
                "say' or 'gurus claim'.\n"
                "   - income_range: realistic monthly income as a range (e.g. '$200-800')\n"
                "   - tools_needed: APIs, services, accounts required (be specific: "
                "'OpenAI API key', 'Twitter developer account', 'Stripe Connect', etc.)\n"
                "   - non_obviousness_check: would 90% of 'passive income' bloggers list "
                "this? (yes|no)\n"
                "   - non_obviousness_justification: only required if non_obviousness_check "
                "is 'yes' — explain why it's still worth listing OR it should be replaced "
                "with something fresher.\n"
                "   - automation_realness_check: many side hustle gurus call things "
                "'automated' when every transaction still needs a human. Is this actually "
                "automatable, or does it secretly require manual judgment per item?\n"
                "     - Valid values: 'fully_automated' | 'mostly_automated_monitoring' | "
                "'manual_with_assist' | 'fake_automation'\n"
                "     - 'fake_automation' opportunities should be dropped — they're not what "
                "we're looking for.\n\n"
                "QUALITY STANDARDS:\n"
                "- Every income claim must cite a URL. No 'some users report' or 'experts say'.\n"
                "- Every opportunity must reference at least one real tool or platform by name.\n"
                "- At least 4 of the 6-8 opportunities must be NON-OBVIOUS "
                "(non_obviousness_check = 'no').\n"
                "- Do NOT include opportunities with automation_realness_check = 'fake_automation'.\n"
                "- Use web search for EVERY major claim — do not rely on training data alone.\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "opportunities": [\n'
                '    {{\n'
                '      "name": "string",\n'
                '      "description": "string",\n'
                '      "automation_approach": "string — specifically how n8n would automate this",\n'
                '      "timing_signal_type": "REGULATORY_SHIFT|TECHNOLOGY_UNLOCK|BEHAVIORAL_CHANGE|COST_COLLAPSE|DISTRIBUTION_UNLOCK|INCUMBENT_FAILURE",\n'
                '      "timing_signal": "string — specific evidence with source",\n'
                '      "income_evidence": {{\n'
                '        "source_url": "string — URL to a verifiable revenue claim",\n'
                '        "source_type": "stripe_screenshot|indie_hackers_mrr|reddit_with_proof|youtube_dashboard|other",\n'
                '        "claimed_income": "string — e.g. $1,200/month net"\n'
                '      }},\n'
                '      "income_range": "string",\n'
                '      "tools_needed": ["string"],\n'
                '      "non_obviousness_check": "yes|no",\n'
                '      "non_obviousness_justification": "string — only required if check is yes",\n'
                '      "automation_realness_check": "fully_automated|mostly_automated_monitoring|manual_with_assist|fake_automation"\n'
                '    }}\n'
                '  ],\n'
                '  "sources_consulted": ["string — name/URL of report, forum, channel, repo searched"]\n'
                '}}'
            ),
            "output_key": "side_hustle_research",
            "timeout_override": 1800,
            "max_retries": 2,
            "output_schema": "side_hustle_research_v1",
            "model_override": "claude-opus-4-7",
        },
        # ──────────────────────────────────────────────────
        # Step 1: Evaluate feasibility
        # ──────────────────────────────────────────────────
        {
            "name": "evaluate_feasibility",
            "job_type": "research",
            "prompt_template": (
                "You are evaluating automated side hustle opportunities. Score each "
                "one rigorously using the ANCHORS below so scores are comparable "
                "across runs. Do NOT invent your own scale. Verify every claim with "
                "web search — the prior step's 'income_evidence' is a starting "
                "point, not gospel.\n\n"
                "RESEARCH:\n{side_hustle_research}\n\n"
                "Deep research mode: {deep_mode}\n\n"
                "DEEP RESEARCH MODE: If 'Deep research mode' is 'true', the user is on Claude "
                "Max — invest the EXTRA effort in deeper RESEARCH (more web searches per "
                "opportunity, full 24-month enforcement lookback for legal_checklist) but "
                "DO NOT inflate the output. Keep verdict to 2-3 sentences max, monthly_costs to "
                "one tight line, and n8n_node_inventory to nodes you actually need (5-8 nodes, "
                "not an exhaustive catalog). The output JSON must stay under ~6000 tokens "
                "total or it gets truncated mid-write.\n\n"
                "SCORE ANCHORS (integer 1-10 per dimension):\n\n"
                "revenue_potential — realistic monthly net after costs:\n"
                "  1  = <$100/mo, or no clear path to paying customers\n"
                "  5  = $100-500/mo with significant effort\n"
                "  8  = $1-3K/mo realistic based on comparable operators\n"
                "  10 = $5K+/mo realistic with multiple comparable operators proven\n\n"
                "n8n_specific_feasibility — can n8n actually build this?\n"
                "  1  = needs custom code / infrastructure n8n can't orchestrate\n"
                "  5  = core workflow works in n8n but hits nodes that don't exist or "
                "require community packages of unknown quality\n"
                "  8  = doable with standard n8n nodes (HTTP Request, Schedule, Code, "
                "IF, Set) plus one or two first-party integrations\n"
                "  10 = trivially buildable with built-in nodes only; no custom code\n\n"
                "time_to_first_dollar — how quickly revenue starts:\n"
                "  1  = 3+ months (requires audience, SEO, or credibility building)\n"
                "  5  = 3-6 weeks (needs some setup + outreach)\n"
                "  8  = 1-2 weeks (deploy → first customer soon after)\n"
                "  10 = days (known paying demand, just need to flip the switch)\n\n"
                "maintenance_effort — ongoing hands-off-ness:\n"
                "  1  = daily manual review required per transaction\n"
                "  5  = weekly check-ins, occasional manual intervention\n"
                "  8  = mostly hands-off; monthly monitoring\n"
                "  10 = fully autonomous; only touch it when something breaks\n\n"
                "legal_safety — risk of TOS/regulatory issues:\n"
                "  1  = clearly violates a platform TOS, a law, or requires a license "
                "you don't have\n"
                "  5  = gray area with enforcement risk (scraping, CAN-SPAM edge cases)\n"
                "  8  = legal as long as standard best practices are followed\n"
                "  10 = zero regulatory surface — you're the customer, not the operator "
                "of regulated activity\n\n"
                "scalability — can income grow without proportional effort?\n"
                "  1  = hard cap on income (e.g. 1 human per transaction)\n"
                "  5  = linear scaling with spend (ads) or effort (outreach)\n"
                "  8  = sublinear scaling; doubling income requires <2x effort\n"
                "  10 = genuinely passive scaling (compounding audience, network effects)\n\n"
                "IMPORTANT OUTPUT SIZE CONSTRAINT: Your entire JSON response must fit "
                "in a single message — no 'continuing from the cut' or batch splitting. "
                "If the research step produced more than 8 opportunities, evaluate ONLY "
                "the top 8 (by your quick assessment of research quality and timing signal "
                "strength). List any dropped ones in a 'dropped' array with just name + "
                "one-line reason. This is critical — exceeding the output limit corrupts "
                "the JSON and wastes 3 retry attempts.\n\n"
                "For EACH evaluated opportunity, provide:\n\n"
                "1. n8n_node_inventory: the 3-4 MOST IMPORTANT nodes only (not every node). "
                "Each entry: node type + availability (built_in/first_party/community/custom_code) "
                "+ short note. This is the signal for n8n_specific_feasibility.\n\n"
                "2. legal_checklist: list ONLY the compliance categories that actually apply "
                "to this specific opportunity (not all 7). For each that applies, cite one "
                "enforcement action. If none apply, set compliance_categories to [] and "
                "specific_risks to [].\n"
                "   Categories: PLATFORM_TOS, CFAA, FTC_AFFILIATE, CAN_SPAM, GDPR, "
                "STATE_BUSINESS_LICENSE, TAX_THRESHOLD\n\n"
                "3. monthly_costs: one line, e.g. 'OpenAI ~$20 + n8n VPS ~$10 + proxy ~$15 = $45/mo'\n\n"
                "4. automation_bottleneck: one sentence — the ONE hardest step to automate.\n\n"
                "5. total_score: sum of all six dimensions (unweighted — synthesis applies weights).\n\n"
                "6. verdict: exactly 2 sentences. No more.\n\n"
                "OUTPUT: Respond with ONLY valid JSON. Do NOT wrap inner "
                "arrays or objects in ```json code fences — the outer "
                "document is already JSON, fences inside it are a parse "
                "error. If you want to format the response, use a single "
                "fence around the WHOLE document, never around inner values.\n"
                '{{\n'
                '  "evaluations": [\n'
                '    {{\n'
                '      "name": "string",\n'
                '      "scores": {{\n'
                '        "revenue_potential": 8,\n'
                '        "n8n_specific_feasibility": 7,\n'
                '        "time_to_first_dollar": 9,\n'
                '        "maintenance_effort": 6,\n'
                '        "legal_safety": 8,\n'
                '        "scalability": 7\n'
                '      }},\n'
                '      "total_score": 45,\n'
                '      "n8n_node_inventory": [\n'
                '        {{"node": "n8n-nodes-base.scheduleTrigger", "availability": "built_in", "notes": "string"}}\n'
                '      ],\n'
                '      "legal_checklist": {{\n'
                '        "compliance_categories": ["PLATFORM_TOS|CFAA|FTC_AFFILIATE|CAN_SPAM|GDPR|STATE_BUSINESS_LICENSE|TAX_THRESHOLD"],\n'
                '        "specific_risks": [\n'
                '          {{"category": "string", "regulator_or_platform": "string", "recent_enforcement": "string — 24 month lookback", "source": "string — URL"}}\n'
                '        ]\n'
                '      }},\n'
                '      "monthly_costs": "string — itemized",\n'
                '      "automation_bottleneck": "string",\n'
                '      "verdict": "string — 2-3 sentences"\n'
                '    }}\n'
                '  ]\n'
                '}}'
            ),
            "output_key": "feasibility",
            "condition": {"field": "side_hustle_research", "operator": "not_empty"},
            "timeout_override": 1800,
            "max_retries": 2,
            "output_schema": "side_hustle_feasibility_v1",
            "context_inputs": ["side_hustle_research"],
            "model_override": "claude-opus-4-7",
        },
        # ──────────────────────────────────────────────────
        # Step 2: Contrarian analysis
        # ──────────────────────────────────────────────────
        {
            "name": "contrarian_analysis",
            "job_type": "research",
            "prompt_template": (
                "You are a skeptical VC partner stress-testing automated side hustle "
                "opportunities. Your job is to find the reasons each one could fail "
                "or get shut down. Vague risks are useless — every claim needs a "
                "specific name, date, or URL.\n\n"
                "FEASIBILITY EVALUATION:\n{feasibility}\n\n"
                "Deep research mode: {deep_mode}\n\n"
                "DEEP RESEARCH MODE: If 'Deep research mode' is 'true', the user is on Claude "
                "Max. Find at least 2 named failed predecessors per opportunity (not just 1), "
                "extend the platform crackdown lookback from 24 to 36 months, and require "
                "primary-source income evidence for any 'survives' verdict (no moderate-strength "
                "evidence allowed in the top tier in deep mode).\n\n"
                "INSTRUCTIONS:\nFor EACH opportunity, use web search to investigate:\n\n"
                "1. NAMED FAILED PREDECESSORS: Find SPECIFIC people or businesses that "
                "tried this exact side hustle and failed.\n"
                "   - Required fields per predecessor: name (handle/company), year they "
                "quit or shut down, specific reason (cite a post-mortem URL if you can).\n"
                "   - Do NOT say 'many people failed' or 'it's crowded' — name them or "
                "omit the claim.\n"
                "   - Search: 'reddit [hustle name] failed', 'why I quit [hustle]', "
                "'[hustle] burnout', indie hackers shutdown stories, failory.com if "
                "relevant.\n"
                "   - If you genuinely cannot find any named failures after searching, "
                "say so explicitly — that itself is meaningful (too new or too niche).\n\n"
                "2. PLATFORM CRACKDOWN EVIDENCE (required for any opportunity that "
                "depends on a specific platform — scraping, API use, marketplace selling):\n"
                "   - Cite at least ONE specific enforcement action in the last 24 months "
                "against automators in this space. Banned account, API quota cut, TOS update "
                "that explicitly targets this pattern, or cease-and-desist letter.\n"
                "   - Include the source URL.\n"
                "   - If the opportunity doesn't depend on any single platform (e.g. "
                "self-hosted Discord bot for paying customers), set platform_dependency "
                "to 'none' and skip.\n\n"
                "3. SATURATION (required: specific search result count, not adjectives):\n"
                "   - Run an actual web search like "
                "'\"[hustle name]\" tutorial 2025' or '[tool] automation guide' and report "
                "the APPROXIMATE NUMBER of tutorial results in the last 12 months.\n"
                "   - Format: 'X YouTube videos in last 6 months', 'Y Reddit threads in "
                "r/SideProject in last 3 months', 'Z Medium articles, most older than 2 years'.\n"
                "   - Interpret: 50+ recent tutorials = saturated; 10-50 = growing awareness "
                "(good timing); <10 = either too early or genuinely non-obvious.\n"
                "   - Do NOT say 'low/medium/high' without a number backing it.\n\n"
                "4. INCOME REALITY CHECK (required: primary-source evidence, not hearsay):\n"
                "   - Search for people reporting ACTUAL income from this exact hustle.\n"
                "   - Primary sources: Stripe screenshots, IndieHackers MRR pages, "
                "YouTube payout dashboards, Reddit threads with imgur proof.\n"
                "   - Secondary sources (weaker): Reddit comments with no proof, "
                "blog posts, gurus selling courses about this.\n"
                "   - Tag evidence_strength as 'strong' (primary source found), "
                "'moderate' (credible but unverified), or 'weak' (gurus/hearsay only).\n"
                "   - If evidence_strength = 'weak', this should weaken the verdict "
                "significantly.\n\n"
                "5. FAILURE STORIES (required: at least one):\n"
                "   - Search for people who tried and quit this hustle. What specifically "
                "made them give up? Time investment exceeded reward? Platform ban? "
                "Market dried up? Legal cease-and-desist?\n"
                "   - If you can't find a single failure story, that's a RED FLAG (either "
                "survivorship bias is hiding failures, OR the hustle is too new to have "
                "enough history).\n\n"
                "6. KILL SCENARIO PROBABILITY: Beyond the kill_scenario string, assign a "
                "probability:\n"
                "   - LOW: <25% chance this kills the hustle within 12 months\n"
                "   - MEDIUM: 25-60% chance\n"
                "   - HIGH: >60% chance — should usually be a 'killed' verdict\n\n"
                "7. VERDICT: Classify each opportunity:\n"
                "   - SURVIVES: Holds up under scrutiny, kill probability LOW\n"
                "   - WEAKENED: Still viable but with significant caveats, kill "
                "probability MEDIUM\n"
                "   - KILLED: Fatal flaws, kill probability HIGH, or evidence_strength weak + "
                "no named predecessors (i.e. we can't even verify anyone has done it)\n\n"
                "Be ruthlessly honest. A pipeline that ships 'survives' for every hustle "
                "is useless. A good contrarian pass should kill at least 30% of incoming "
                "opportunities.\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "analyses": [\n'
                '    {{\n'
                '      "name": "string",\n'
                '      "failed_predecessors": [\n'
                '        {{"name": "string — handle or company", "year": "string", "reason": "string", "source": "string — URL"}}\n'
                '      ],\n'
                '      "platform_dependency": "string — platform name, or \'none\'",\n'
                '      "platform_crackdown_evidence": [\n'
                '        {{"platform": "string", "action": "string — ban/TOS update/API cut", "when": "string — date", "source": "string — URL"}}\n'
                '      ],\n'
                '      "saturation": {{\n'
                '        "search_summary": "string — X tutorials in last Y months per platform",\n'
                '        "saturation_level": "low|medium|high"\n'
                '      }},\n'
                '      "income_reality": {{\n'
                '        "primary_source_links": ["string — URLs to Stripe/MRR/dashboard screenshots"],\n'
                '        "typical_reported_income": "string — what real operators are making",\n'
                '        "evidence_strength": "strong|moderate|weak"\n'
                '      }},\n'
                '      "failure_stories": [\n'
                '        {{"quit_reason": "string", "source": "string — URL"}}\n'
                '      ],\n'
                '      "kill_scenario": "string — the most likely way this hustle dies",\n'
                '      "kill_probability": "low|medium|high",\n'
                '      "verdict": "survives|weakened|killed",\n'
                '      "verdict_reasoning": "string — 3-5 sentences"\n'
                '    }}\n'
                '  ],\n'
                '  "summary": "string — overall assessment including how many survived"\n'
                '}}'
            ),
            "output_key": "contrarian",
            "condition": {"field": "feasibility", "operator": "not_empty"},
            "timeout_override": 1800,
            "max_retries": 2,
            "output_schema": "side_hustle_contrarian_v1",
            "context_inputs": ["feasibility"],
            "model_override": "claude-opus-4-7",
        },
        # ──────────────────────────────────────────────────
        # Step 3: Freshness decay check (Batch D parity with startup)
        # ──────────────────────────────────────────────────
        # Runs a narrow 30-day news pass on surviving hustles. Side
        # hustle categories are especially prone to "guru saturation"
        # (a hustle getting blasted across YouTube/IH in the month between
        # research and synthesis, collapsing margins) and to platform
        # policy changes (API rate-limit bumps, ToS tightening) that
        # invalidate the automation approach overnight.
        {
            "name": "freshness_check",
            "job_type": "research",
            "prompt_template": (
                "You are a side-hustle analyst doing a final 30-day freshness pass on "
                "hustles that survived contrarian review. Side-hustle categories go stale "
                "fast — your job is to catch recent moves that would kill or weaken a "
                "survivor BEFORE synthesis ranks it.\n\n"
                "CONTRARIAN OUTPUT:\n{contrarian}\n\n"
                "INSTRUCTIONS:\n"
                "For EACH hustle with verdict 'survives' or 'weakened', use web search "
                "restricted to the LAST 30 DAYS to check for:\n"
                "1. GURU SATURATION — was this hustle featured in a viral YouTube short, "
                "Twitter thread, or newsletter in the last 30 days? Saturation collapses "
                "margins within weeks as imitators flood the channel.\n"
                "2. PLATFORM POLICY CHANGES — did an API's ToS tighten, a rate limit drop, "
                "pricing change, or a platform (Upwork, Fiverr, Reddit, Twitter/X, Meta) "
                "restrict the automation pattern the hustle depends on?\n"
                "3. NEW COMPETITORS — did a funded startup launch a product that replaces "
                "this manual+n8n workflow with a turnkey SaaS? (e.g. a $29/mo tool that "
                "does what you planned to charge $500/mo for)\n"
                "4. REGULATORY MOVES — new FTC guidance on affiliate disclosure, new state "
                "data-privacy rules, any piece that changes the legal_checklist from "
                "feasibility.\n\n"
                "CLASSIFY each hustle:\n"
                "- STABLE: no material change in the last 30 days. Original verdict holds.\n"
                "- WEAKENED_FURTHER: material move narrows the window but doesn't kill.\n"
                "  Synthesis should deduct 5-10 points from its total_score.\n"
                "- KILLED_POST_CONTRARIAN: recent move eliminates the hustle. Synthesis "
                "  MUST drop this from final_rankings.\n\n"
                "QUALITY RULES:\n"
                "- Every non-STABLE classification MUST cite a specific URL + date. No "
                "handwaving.\n"
                "- Default to STABLE if you can't find specific 30-day evidence.\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "freshness_results": [\n'
                '    {{\n'
                '      "name": "string — hustle name exactly as in contrarian",\n'
                '      "status": "STABLE|WEAKENED_FURTHER|KILLED_POST_CONTRARIAN",\n'
                '      "evidence": "string — source URL + date + one-sentence summary, or null if STABLE",\n'
                '      "impact": "string — one sentence on how this changes the verdict"\n'
                '    }}\n'
                '  ],\n'
                '  "scan_notes": "string — 1-2 sentences on what you searched and what you found overall"\n'
                '}}'
            ),
            "output_key": "freshness",
            "condition": {"field": "contrarian", "operator": "not_empty"},
            "timeout_override": 900,
            "max_retries": 1,
            "output_schema": "startup_freshness_v1",
            "context_inputs": ["contrarian"],
            "model_override": "claude-opus-4-7",
        },
        # ──────────────────────────────────────────────────
        # Step 4: Synthesis and ranking
        # ──────────────────────────────────────────────────
        {
            "name": "synthesis_and_ranking",
            "job_type": "research",
            "prompt_template": (
                "You are producing a final investment-grade ranking of automated side "
                "hustles for a solo operator. Synthesize all previous research into a "
                "definitive, COMPARATIVE ranking.\n\n"
                "RESEARCH:\n{side_hustle_research}\n\n"
                "FEASIBILITY:\n{feasibility}\n\n"
                "CONTRARIAN:\n{contrarian}\n\n"
                "FRESHNESS CHECK (last-30-day saturation + policy moves):\n{freshness}\n\n"
                "Deep research mode: {deep_mode}\n\n"
                "DEEP RESEARCH MODE: If 'Deep research mode' is 'true', the user is on Claude "
                "Max. Rank up to 7 opportunities in final_rankings (instead of capping at 5), "
                "and write a full n8n_workflow_spec for ALL of them (not just the top 5). The "
                "executive_summary should also be 3-4 paragraphs instead of 2-3, with explicit "
                "comparison across the top 3 picks.\n\n"
                "INSTRUCTIONS:\n\n"
                "1. Drop every hustle that either (a) got a 'killed' verdict in contrarian, "
                "OR (b) was marked KILLED_POST_CONTRARIAN by the freshness check. Both are "
                "equal-weight exclusion signals. Include only 'survives' or 'weakened' in "
                "contrarian AND not KILLED_POST_CONTRARIAN in freshness.\n\n"
                "2. WEIGHTED SCORING on a 0-100 scale — apply these weights to each "
                "surviving opportunity's feasibility scores. Weights sum to 10.0 so the "
                "weighted sum of six 1-10 dimensions maxes at 100. Solo operators care "
                "most about revenue potential and time to first dollar; long-term "
                "scalability matters less because the operator can always build a "
                "second workflow.\n\n"
                "   raw_score   = (revenue_potential × 2.5)\n"
                "               + (time_to_first_dollar × 2.5)\n"
                "               + (n8n_specific_feasibility × 1.5)\n"
                "               + (maintenance_effort × 1.5)\n"
                "               + (legal_safety × 1.5)\n"
                "               + (scalability × 0.5)\n\n"
                "   Maximum possible: 100. Round to 1 decimal place.\n\n"
                "   Apply a contrarian adjustment AFTER the weighted sum to produce\n"
                "   total_score:\n"
                "   - 'survives' verdict: total_score = raw_score\n"
                "   - 'weakened' verdict: total_score = raw_score × 0.8\n\n"
                "   FRESHNESS DEDUCTION: if the hustle was marked WEAKENED_FURTHER by the\n"
                "   freshness check, deduct 5-10 additional points from total_score AFTER\n"
                "   the contrarian adjustment (severity depends on how damaging the 30-day\n"
                "   move was). Cite the deduction in head_to_head or surviving_risks. STABLE\n"
                "   hustles get no freshness deduction.\n"
                "   Do NOT inflate dimension scores to hit a target total — score each\n"
                "   dimension honestly, then let the formula produce whatever total it\n"
                "   produces. A realistic surviving opportunity typically lands 55-80.\n\n"
                "3. RANK opportunities by adjusted total_score (highest first). For each "
                "ranked entry, also write a 'head_to_head' field explaining WHY it beats "
                "the opportunity ranked one position below it. The lowest-ranked entry "
                "explains why it still made the cut instead of being dropped. This forces "
                "real comparison instead of isolated scoring.\n\n"
                "4. For the top 5 (or fewer if fewer survived), write a STRICT n8n_workflow_spec. "
                "A spec here must be concrete enough that an engineer could build it without "
                "needing to talk to you:\n\n"
                "   - trigger_node: specific node type + config. For side hustle builds, "
                "this MUST be 'n8n-nodes-base.webhook' (not Schedule or Manual) because "
                "the test_run step triggers via webhook. Include the desired path slug "
                "(kebab-case).\n"
                "   - node_graph: ordered list of node types describing the data flow. "
                "Each entry should name a specific node type and its role.\n"
                "   - external_credentials: every OAuth app, API key, or account the user "
                "must configure in n8n before activation. List them explicitly — 'Stripe "
                "API key', 'OpenAI API key', 'Twitter OAuth 2 app', etc.\n"
                "   - expected_runtime: realistic per-execution duration (e.g. '3-8 seconds').\n"
                "   - frequency: how often the workflow should run (e.g. 'every 6 hours via "
                "external cron hitting the webhook').\n"
                "   - out_of_scope: exactly 3 features explicitly NOT in the v1. This "
                "prevents Claude from over-engineering the workflow JSON during the build "
                "step.\n"
                "   - success_metric: how to know post-deploy whether the automation is "
                "working. Must be OBSERVABLE (e.g. 'at least 5 qualified leads added to "
                "airtable per day' not 'users are happy').\n"
                "   - risky_assumption: the ONE belief that, if wrong, kills this side "
                "hustle. Phrase it as a testable statement (e.g. 'people will pay $15/month "
                "for an alert when any RV in a 100-mile radius drops by 20%+').\n\n"
                "5. executive_summary: 2-3 paragraph overall recommendation. Include:\n"
                "   - how many opportunities survived contrarian (out of how many started)\n"
                "   - the single most important reason the rank-1 pick beats rank-2\n"
                "   - what the user should budget for monthly API/tool costs across the "
                "top 3\n"
                "   - any cross-cutting risks that apply to multiple opportunities at once\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "final_rankings": [\n'
                '    {{\n'
                '      "rank": 1,\n'
                '      "name": "string",\n'
                '      "one_liner": "string — one sentence pitch",\n'
                '      "monthly_income_estimate": "string — realistic range",\n'
                '      "monthly_costs": "string — itemized tools",\n'
                '      "contrarian_verdict": "survives|weakened",\n'
                '      "raw_score": 72.0,\n'
                '      "total_score": 57.6,\n'
                '      "head_to_head": "string — why this beats the next-ranked opportunity",\n'
                '      "surviving_risks": ["string — risks that remain after contrarian"],\n'
                '      "n8n_workflow_spec": {{\n'
                '        "trigger_node": "n8n-nodes-base.webhook with path: \'slug\'",\n'
                '        "node_graph": [\n'
                '          {{"node": "n8n-nodes-base.webhook", "role": "trigger"}},\n'
                '          {{"node": "n8n-nodes-base.httpRequest", "role": "fetch data"}}\n'
                '        ],\n'
                '        "external_credentials": ["string — each credential to configure"],\n'
                '        "expected_runtime": "string — seconds or minutes per run",\n'
                '        "frequency": "string — how often it runs",\n'
                '        "out_of_scope": ["string — feature 1 NOT in v1", "string — feature 2", "string — feature 3"],\n'
                '        "success_metric": "string — observable post-deploy measure",\n'
                '        "risky_assumption": "string — the one testable belief"\n'
                '      }}\n'
                '    }}\n'
                '  ],\n'
                '  "executive_summary": "string — 2-3 paragraphs"\n'
                '}}'
            ),
            "output_key": "synthesis",
            "condition": {"field": "contrarian", "operator": "not_empty"},
            "timeout_override": 1800,
            "max_retries": 2,
            "output_schema": "side_hustle_synthesis_v1",
            "context_inputs": ["side_hustle_research", "feasibility", "contrarian", "freshness"],
            # Synthesis is aggregation + scoring over already-researched
            # output. Sonnet follows the formula reliably at ~1/5 the
            # input cost vs Opus.
            "model_override": "claude-opus-4-7",
        },
        # ──────────────────────────────────────────────────
        # Step 5: Subscription pre-sale validation plan (Batch D)
        # ──────────────────────────────────────────────────
        # Side-hustle analogue of the startup validation_plan step. The
        # synthesis produces a ranking; the actual next action is not
        # "build the n8n workflow" but "confirm people will pay a
        # recurring subscription for it." This step turns the top 3
        # ranked hustles into a concrete pre-subscription playbook.
        {
            "name": "validation_plan",
            "job_type": "research",
            "prompt_template": (
                "You are a GTM strategist producing a 3-week PRE-SUBSCRIPTION validation "
                "plan for the top 3 ranked side hustles in the synthesis. The goal is to "
                "confirm recurring paying demand BEFORE the operator wires the n8n workflow "
                "— via paid beta, annual-plan deposits, or a founding-customer list.\n\n"
                "SYNTHESIS:\n{synthesis}\n\n"
                "For EACH of the top 3 ranked hustles, produce a validation plan with:\n\n"
                "1. specific_outreach_targets: 5-10 NAMED communities, forums, subreddits, "
                "Slack/Discord servers, or newsletter audiences where the target buyer "
                "actually hangs out. For each, include:\n"
                "   - name: community or channel name\n"
                "   - why_them: one-sentence match against the hustle's buyer ICP\n"
                "   - reachable_via: how you post or DM there without getting banned (e.g. "
                "    'post in r/Entrepreneur weekly Monday thread, value-add first', "
                "    'comment on IndieHackers revenue posts')\n"
                "   Do NOT list 'small business owners' as a target — name specific communities.\n\n"
                "2. contact_channel: the PRIMARY channel for outreach (Reddit subreddit, "
                "Slack community, Twitter/X thread, newsletter DM, cold email).\n\n"
                "3. cold_message_script: 80-150 word opener. Must:\n"
                "   - Name the specific workflow pain from the feasibility research\n"
                "   - Reference a named competitor pricing or a DIY solution people use today\n"
                "   - End with a binary ask ('would you pay $X/mo if this existed before I "
                "     built it?')\n"
                "   - NOT start with 'Hi, hope you're well' or any generic greeting.\n\n"
                "4. disqualification_criteria: 3 specific conditions that should make the "
                "operator DROP this hustle. Each must be a testable fact, e.g. 'fewer than "
                "5 DMs reply in 7 days' or 'nobody agrees to $49/mo annual pre-pay.'\n\n"
                "5. go_no_go_metric: the SINGLE subscription-count threshold at end-of-week-3 "
                "that triggers build-or-drop. Format: '≥N paying subscribers at $X/mo, else "
                "drop.' Example: '≥5 founding customers at $99/mo annual pre-pay, else drop.'\n\n"
                "6. expected_signal_timeline: 3-4 short sentences on what you expect by end "
                "of week 1, week 2, and week 3. Ground in realistic reply rates (cold DM "
                "~5-10%, community post ~20-40% engagement-rate).\n\n"
                "QUALITY RULES:\n"
                "- No handwaving. 'Reach out in Facebook groups' is not acceptable. 'Post a "
                "weekly value-add in these 7 named groups' is.\n"
                "- Every pre-sale ask must be a concrete dollar amount AND cadence "
                "(monthly or annual pre-pay).\n"
                "- The go_no_go_metric must be binary — not 'get positive feedback.'\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "validation_plans": [\n'
                '    {{\n'
                '      "rank": 1,\n'
                '      "name": "string — must match a name from synthesis.final_rankings",\n'
                '      "specific_outreach_targets": [\n'
                '        {{"name": "string", "why_them": "string", "reachable_via": "string"}}\n'
                '      ],\n'
                '      "contact_channel": "string",\n'
                '      "cold_message_script": "string — 80-150 words",\n'
                '      "disqualification_criteria": ["string — testable fact"],\n'
                '      "go_no_go_metric": "string — binary subscriber-count threshold",\n'
                '      "expected_signal_timeline": "string — week-by-week expectations"\n'
                '    }}\n'
                '  ],\n'
                '  "cross_cutting_notes": "string — 1-2 sentences on anything the operator '
                'should know before starting all three validations in parallel"\n'
                '}}'
            ),
            "output_key": "validation_plans",
            "condition": {"field": "synthesis", "operator": "not_empty"},
            "timeout_override": 900,
            "max_retries": 1,
            "output_schema": "startup_validation_v1",
            "context_inputs": ["synthesis"],
            "model_override": "claude-opus-4-7",
        },
        # ──────────────────────────────────────────────────
        # Step 6: User picks a hustle
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
        # Round 4: this step MUST produce a Webhook trigger node in its
        # workflow.json because the test_run step triggers execution via
        # the webhook URL. A Schedule Trigger or Manual Trigger won't
        # work because n8n's public REST API has no general-purpose
        # "execute this workflow" endpoint.
        {
            "name": "build_n8n_workflow",
            "job_type": "builder",
            "prompt_template": (
                "Build an n8n workflow automation for a side hustle.\n\n"
                "SELECTED OPPORTUNITY:\n{selected_hustle}\n\n"
                "INSTRUCTIONS:\n"
                "1. Create a valid n8n workflow JSON file called `workflow.json` in the "
                "current directory. The workflow must follow n8n's workflow format with "
                "proper nodes and connections.\n\n"
                "2. CRITICAL: the workflow MUST use a Webhook trigger node "
                "(`n8n-nodes-base.webhook`) as its entry point — NOT a Schedule Trigger "
                "or Manual Trigger. The parent system triggers this workflow by POSTing "
                "to the webhook URL for the test run, and n8n's REST API does not expose "
                "a general-purpose 'execute workflow' endpoint. Without a webhook trigger, "
                "the test run will fail with 'no webhook URL available'.\n\n"
                "3. The webhook trigger's `parameters.path` should be a short descriptive "
                "slug unique to this side hustle (e.g. 'reddit-deal-scanner', "
                "'price-arbitrage-notify'). Use kebab-case.\n\n"
                "4. Include these n8n node types as appropriate after the trigger:\n"
                "   - HTTP Request for API calls\n"
                "   - Code node for custom JavaScript logic\n"
                "   - IF node for conditional branching\n"
                "   - Set node for data transformation\n"
                "   - Any other standard n8n nodes needed\n\n"
                "5. Create a README.md explaining:\n"
                "   - What this side hustle automation does\n"
                "   - Expected income and costs\n"
                "   - What accounts/credentials the user needs to set up in n8n\n"
                "   - The webhook URL format and what payload it expects\n"
                "   - How to configure and customize the workflow\n"
                "   - Any manual steps required\n\n"
                "6. Create a BUILD_DECISIONS.md explaining:\n"
                "   - Why you chose the specific node topology you did\n"
                "   - Any tradeoffs you made\n"
                "   - What features you intentionally did NOT build (out-of-scope)\n"
                "   - How a user would test whether this side hustle actually makes money\n\n"
                "7. Create a `test_payload.json` file containing a minimal JSON object that "
                "can be POSTed to the webhook URL to exercise the workflow end-to-end. "
                "This is what the test_run step will send. Make it realistic (not empty) "
                "so the test actually runs through the full node graph.\n\n"
                "8. Create any supporting files (scripts, config templates, etc.) as needed.\n\n"
                "9. Write arlo_manifest.json including a 'workflow_json' key that contains "
                "the full contents of workflow.json (the n8n workflow definition).\n\n"
                "IMPORTANT: workflow.json must be valid n8n workflow JSON that can be "
                "imported directly via n8n's REST API (n8n v2.15.0). It must have:\n"
                "   - a `name` string\n"
                "   - a `nodes` array (non-empty, including exactly one "
                "n8n-nodes-base.webhook trigger)\n"
                "   - a `connections` object (can be empty {} if there's only one node)\n"
                "   - a `settings` object (empty {} is acceptable — n8n 2.x REJECTS "
                "workflow creation without this field with a 400 error)\n"
                "DO NOT omit the `settings` field. n8n v1 tolerated missing settings; "
                "v2 does not.\n\n"
                "--- ACTIVATION ERRORS FROM PREVIOUS DEPLOY (if any) ---\n"
                "{deploy_result}\n\n"
                "If the above contains 'activation_error', you MUST fix the specific node "
                "configuration issues described in the n8n error. The error names the exact "
                "nodes and parameters that are misconfigured. Fix ONLY those nodes' parameters "
                "— do not redesign the workflow topology or change the trigger type.\n"
                "If deploy_result shows '{{unknown}}' or is empty, ignore this section and "
                "build fresh."
            ),
            "output_key": "build_result",
            "condition": {"field": "synthesis", "operator": "not_empty"},
            "timeout_override": 2400,
            "max_retries": 1,
            "context_inputs": ["selected_hustle", "deploy_result"],
            "required_artifacts": [
                "workflow.json",
                "README.md",
                "BUILD_DECISIONS.md",
                "test_payload.json",
            ],
        },
        # ──────────────────────────────────────────────────
        # Step 6: Deploy workflow to n8n
        # ──────────────────────────────────────────────────
        # Round 4: the prompt is now a small static JSON instruction
        # blob (no template substitution). The executor reads the
        # previous builder step's result_data directly from the
        # database via from_previous_build=true. This eliminates the
        # old class of bugs where embedding {build_result} via
        # str.format_map corrupted the JSON on any embedded quote or
        # backslash in the builder output.
        {
            "name": "deploy_to_n8n",
            "job_type": "n8n",
            "prompt_template": (
                '{"action": "create", "activate": true, "from_previous_build": true}'
            ),
            "output_key": "deploy_result",
            "condition": {"field": "build_result", "operator": "not_empty"},
            # Round 6 followup (Batch D updated): activation validation
            # loop. If n8n rejects activation (e.g. "Node X: missing
            # required parameters"), the executor stores the error in
            # deploy_result instead of failing the job. This loop
            # sends the workflow back to build_n8n_workflow so Claude
            # can fix the flagged nodes. Max 3 total builds.
            #
            # Batch D: build_n8n_workflow moved from step 5 to step 7
            # after inserting freshness_check and validation_plan.
            "loop_to": 7,
            "max_loop_count": 3,
            "loop_condition": {
                "field": "deploy_result",
                "operator": "contains",
                "value": "activation_error",
            },
        },
        # ──────────────────────────────────────────────────
        # Step 9: Test run (approval-gated)
        # ──────────────────────────────────────────────────
        # Round 4: same static-JSON pattern as the deploy step. The
        # executor reads webhook_url + n8n_workflow_id from the
        # previous deploy step's result_data via from_previous_deploy=true.
        {
            "name": "test_run",
            "job_type": "n8n",
            "prompt_template": (
                '{"action": "execute", "from_previous_deploy": true}'
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
                "1. Only include niches with 'survives' or 'weakened' verdicts.\n\n"
                "2. WEIGHTED SCORING on a 0-100 scale — apply these weights to the "
                "six dimensions scored in the evaluation step. Weights sum to 10.0 "
                "so six 1-10 scores max at 100. Pay rate and demand volume dominate "
                "because a solo freelancer needs real money coming in, not just ease "
                "of scraping.\n\n"
                "   raw_score   = (hourly_rate × 2.5)\n"
                "               + (demand_volume × 2.5)\n"
                "               + (competition × 1.5)\n"
                "               + (skill_match × 1.5)\n"
                "               + (remote_friendly × 1.0)\n"
                "               + (monitorability × 1.0)\n\n"
                "   Maximum possible: 100. Round to 1 decimal place.\n\n"
                "   Apply the contrarian adjustment AFTER the weighted sum to produce\n"
                "   total_score:\n"
                "   - 'survives' verdict: total_score = raw_score\n"
                "   - 'weakened' verdict: total_score = raw_score × 0.8\n\n"
                "   Do NOT inflate dimension scores to hit a target — score honestly\n"
                "   against the anchors from the evaluation step, then let the formula\n"
                "   produce the total. A realistic surviving niche lands 55-80.\n\n"
                "3. Rank by adjusted total_score (highest first).\n\n"
                "4. For the top 3, provide a DETAILED monitoring specification:\n"
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
                '      "contrarian_verdict": "survives|weakened",\n'
                '      "raw_score": 72.0,\n'
                '      "total_score": 72.0,\n'
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
                "IMPORTANT: Use real n8n node types. The workflow must be importable into n8n.\n\n"
                "--- ACTIVATION ERRORS FROM PREVIOUS DEPLOY (if any) ---\n"
                "{deploy_result}\n\n"
                "If the above contains 'activation_error', you MUST fix the specific node "
                "configuration issues described in the n8n error. Fix ONLY those nodes' "
                "parameters — do not redesign the workflow topology.\n"
                "If deploy_result shows '{{unknown}}' or is empty, ignore this section."
            ),
            "output_key": "build_result",
            "condition": {"field": "synthesis", "operator": "not_empty"},
            "timeout_override": 2400,
            "max_retries": 1,
            "context_inputs": ["synthesis", "deploy_result"],
        },
        # ──────────────────────────────────────────────────
        # Step 6: Deploy to n8n
        # ──────────────────────────────────────────────────
        {
            "name": "deploy_scanner",
            "job_type": "n8n",
            # Round 6 followup: fixed from old-style {build_result}
            # interpolation to the Round 4 from_previous_build pattern.
            # The old prompt corrupted JSON on any quote/backslash in
            # the builder output.
            "prompt_template": (
                '{"action": "create", "activate": true, "from_previous_build": true}'
            ),
            "output_key": "deploy_result",
            "condition": {"field": "build_result", "operator": "not_empty"},
            # Round 6 followup: activation validation loop (same
            # pattern as side hustle deploy_to_n8n).
            "loop_to": 5,
            "max_loop_count": 3,
            "loop_condition": {
                "field": "deploy_result",
                "operator": "contains",
                "value": "activation_error",
            },
        },
    ],
}

STRATEGY_EVOLUTION_PIPELINE = {
    "template_id": "strategy_evolution",
    "name": "Trading Strategy Evolution",
    "description": "Generate → Optimize params (free) → Claude redesign (only on plateau) → loop",
    "required_context": ["starting_capital"],
    "optional_context": ["preferred_instruments", "risk_tolerance", "strategy_family", "seed_strategy", "strategy_research"],
    "steps": [
        # ──────────────────────────────────────────────────
        # Step 0: Generate strategy code (Claude call — ONCE per architecture)
        # Research is pre-cached in workflow context (strategy_research).
        # Claude reads /workspaces/strategy_guide.md for API docs and ideas.
        # ──────────────────────────────────────────────────
        {
            "name": "generate_strategy",
            "job_type": "research",
            "prompt_template": (
                "You are a quant developer. Read /workspaces/strategy_guide.md for the full "
                "multi-asset API docs, signal values, available instruments, macro data accessors, "
                "proven strategy families, and creative edge signals.\n\n"
                "RESEARCH:\n{strategy_research}\n\n"
                "PREVIOUS BACKTEST RESULTS (if any):\n{backtest_results}\n\n"
                "SEED STRATEGY (if provided, improve it):\n{seed_strategy}\n\n"
                "STRATEGY FAMILY: {strategy_family}\n"
                "CAPITAL: {starting_capital}\n\n"
                "Write a multi-asset strategy class (BaseStrategy, multi_asset=True).\n\n"
                "CRITICAL: Include a 'parameter_ranges' field in your output. This defines which "
                "parameters can be tuned and their candidate values. A local optimizer will "
                "automatically test hundreds of parameter combinations WITHOUT calling you again. "
                "Define ranges for EVERY tunable parameter.\n\n"
                "Example parameter_ranges:\n"
                '{{\n'
                '  "lookback": [21, 42, 63, 126, 252],\n'
                '  "sma_period": [50, 100, 150, 200],\n'
                '  "vix_threshold": [15, 20, 25, 30, 35],\n'
                '  "equity_pct_risk_on": [0.7, 0.8, 0.9, 0.95],\n'
                '  "rebalance_days": [15, 21, 42]\n'
                '}}\n\n'
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "action": "submit_and_backtest",\n'
                '  "strategy": {{\n'
                '    "name": "string",\n'
                '    "strategy_code": "string — full Python code",\n'
                '    "parameters": {{}},\n'
                '    "parameter_ranges": {{}},\n'
                '    "risk_constraints": {{"max_drawdown_pct": 0.25, "max_position_size_pct": 0.25}},\n'
                '    "symbols": ["SPY", "QQQ", "IWM", "VTI", "GLD", "TLT", "AGG", "EFA"],\n'
                '    "timeframe": "1D",\n'
                '    "description": "string"\n'
                '  }},\n'
                '  "start_date": "2011-01-01",\n'
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
        # Step 1: Local parameter optimization (NO Claude — runs internally)
        # Generates parameter variants, backtests all via trading engine API,
        # picks the best. Runs up to 30 rounds of 8 variants each (240 backtests).
        # Returns when plateau detected or max rounds hit.
        # ──────────────────────────────────────────────────
        {
            "name": "local_optimize",
            "job_type": "optimize",
            "prompt_template": "{strategy_submission}",
            "output_key": "optimizer_results",
            "condition": {"field": "strategy_submission", "operator": "not_empty"},
        },
        # ──────────────────────────────────────────────────
        # Step 2: Evaluate and redesign (Claude call — ONLY when optimizer plateaus)
        # Sees all optimization results, redesigns strategy architecture.
        # Loops back to Step 1 for more optimization.
        # ──────────────────────────────────────────────────
        {
            "name": "evaluate_and_redesign",
            "job_type": "research",
            "prompt_template": (
                "You are a quant evaluator. Read /workspaces/strategy_guide.md for reference.\n\n"
                "The LOCAL OPTIMIZER tested many parameter combinations and PLATEAUED.\n"
                "Parameter tuning alone cannot improve further — you must REDESIGN the strategy architecture.\n\n"
                "OPTIMIZER RESULTS:\n{optimizer_results}\n\n"
                "CURRENT BEST STRATEGY:\n{strategy_submission}\n\n"
                "THRESHOLDS: return>12%, Sharpe>0.8, DD<20%, consistency>75%, 30+ trades, no fold<-15%.\n\n"
                "ANALYSIS:\n"
                "1. Look at the parameter sensitivity — which params matter most?\n"
                "2. Check worst fold — if below -15%, the crash detector needs structural change.\n"
                "3. If return < 10%, increase equity exposure fundamentally (not just param tuning).\n"
                "4. If Sharpe is -999, fix the code bug.\n\n"
                "REDESIGN the strategy architecture. Change the LOGIC, not just numbers. Examples:\n"
                "- Switch strategy family entirely (momentum → regime → ensemble)\n"
                "- Add/remove signals (add credit lead-lag, VIX mean reversion, etc.)\n"
                "- Change position sizing approach (equal weight → risk parity → concentrated)\n"
                "- Change crash detection method (SMA → multi-signal → VIX-based)\n\n"
                "CRITICAL: Include 'parameter_ranges' for all tunable params in the new design.\n\n"
                "OUTPUT: Respond with ONLY valid JSON:\n"
                '{{\n'
                '  "action": "submit_and_backtest",\n'
                '  "strategy": {{\n'
                '    "name": "string",\n'
                '    "strategy_code": "string — full Python code",\n'
                '    "parameters": {{}},\n'
                '    "parameter_ranges": {{}},\n'
                '    "risk_constraints": {{"max_drawdown_pct": 0.25, "max_position_size_pct": 0.25}},\n'
                '    "symbols": ["SPY", "QQQ", "IWM", "VTI", "GLD", "TLT", "AGG", "EFA"],\n'
                '    "timeframe": "1D",\n'
                '    "description": "string"\n'
                '  }},\n'
                '  "start_date": "2011-01-01",\n'
                '  "end_date": "2024-12-31",\n'
                '  "initial_capital": {starting_capital},\n'
                '  "test_type": "walk_forward",\n'
                '  "evolution_notes": "string — what architectural changes were made and why"\n'
                '}}'
            ),
            "output_key": "strategy_submission",
            "condition": {"field": "optimizer_results", "operator": "not_empty"},
            "timeout_override": 900,
            "loop_to": 1,
            "max_loop_count": 50,
        },
        # Winning strategies are auto-saved by the optimizer to
        # /workspaces/winning_strategies/ when they pass all thresholds.
        # Each Claude redesign cycle triggers ~240 free backtests via the optimizer.
    ],
}

TEMPLATES = {
    "startup_idea_pipeline": STARTUP_IDEA_PIPELINE,
    "side_hustle_pipeline": SIDE_HUSTLE_PIPELINE,
    "freelance_scanner": FREELANCE_SCANNER_PIPELINE,
    "strategy_evolution": STRATEGY_EVOLUTION_PIPELINE,
}
