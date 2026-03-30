"""Prompt templates for Arlo job types."""

RESEARCH_REPORT_SCHEMA = """{
  "market_overview": "string — 3-5 paragraph overview with specific market size numbers, growth rates, and sources",
  "opportunities": [
    {
      "name": "string — concise opportunity name",
      "description": "string — 3-5 sentence description of the opportunity and why it exists now",
      "evidence": [
        "string — each piece of evidence must include: specific data point + source name + URL where possible"
      ],
      "key_competitors": [
        {
          "name": "string — company name",
          "funding": "string — funding amount and stage if known",
          "status": "string — active/acquired/failed/pivoted"
        }
      ],
      "market_size_estimate": "string — TAM/SAM with source citation (e.g., '$4.2B TAM by 2027 — Grand View Research')",
      "competition_level": "low | medium | high",
      "feasibility": "low | medium | high"
    }
  ],
  "trends": ["string — key market trends with supporting data points"],
  "risks": ["string — specific risks with real-world examples of failures"],
  "top_recommendations": [
    {
      "name": "string — name matching one of the opportunities above",
      "reasoning": "string — detailed reasoning referencing specific evidence from above"
    }
  ]
}"""


def build_research_prompt(user_prompt: str) -> str:
    """Build the full prompt for a standalone research job.

    Instructs Claude to do deep, multi-pass web research with real sources.
    """
    return f"""You are a senior startup research analyst. Your task is to produce a deeply researched, evidence-backed market analysis. This research must be thorough enough to withstand scrutiny from experienced investors.

TASK: {user_prompt}

RESEARCH METHODOLOGY — you must follow all of these steps:

1. LANDSCAPE SCAN: Search the web broadly for this market/domain. Look at:
   - Industry reports (Gartner, McKinsey, CB Insights, Grand View Research, etc.)
   - Recent funding announcements (Crunchbase, TechCrunch, PitchBook coverage)
   - Market trend analyses from the last 12 months
   - Analyst commentary and expert opinions

2. DEEP DIVE: For each opportunity you identify, search specifically for:
   - Named companies operating in this space (with funding amounts)
   - Companies that have been acquired (with acquisition prices if public)
   - Companies that have FAILED in this space and why
   - Specific market size estimates from named research firms
   - Growth rate data with time periods

3. CROSS-REFERENCE: For key claims, search for confirming or contradicting evidence:
   - If you cite a market size, find at least one other source
   - If you claim a trend, find specific data points supporting it
   - If you identify low competition, verify by searching for startups in that exact niche

4. IDENTIFY AT LEAST 7 OPPORTUNITIES with real evidence for each.

5. RANK the top 3 with detailed reasoning that references specific evidence.

QUALITY STANDARDS:
- Every market size estimate MUST cite the source by name
- Every opportunity MUST list at least 2 real companies (competitors or adjacent players)
- Evidence MUST include specific numbers (funding amounts, revenue, user counts, growth %)
- Do NOT use vague language like "growing rapidly" — use "growing at 23% CAGR (Source: X)"
- Do NOT fabricate companies, funding rounds, or statistics
- If you cannot find reliable data for a claim, say so explicitly rather than guessing

OUTPUT FORMAT:
Respond with ONLY valid JSON matching this exact schema (no markdown, no code fences):

{RESEARCH_REPORT_SCHEMA}"""


BUILDER_RESULT_SCHEMA = """{
  "summary": "string — 1-2 sentence summary of what was built",
  "artifacts": [
    {
      "path": "string — relative file path within the workspace",
      "artifact_type": "file | directory | config",
      "description": "string — what this file/directory is for"
    }
  ],
  "build_commands_run": ["string — commands that were executed (e.g., npm init, pip install)"],
  "notes": "string | null — any caveats, next steps, or instructions for running the project"
}"""


def build_builder_prompt(user_prompt: str) -> str:
    """Build the full prompt for a builder job.

    The prompt instructs Claude Code to create a project in the current
    working directory and then write a JSON manifest file summarizing what was built.
    """
    return f"""You are a software engineer. Your task is to build a project in the current working directory.

TASK: {user_prompt}

INSTRUCTIONS:
1. Create all necessary files and directories in the current working directory.
2. Set up a complete, working project that can be built and run.
3. Install dependencies using the appropriate package manager (pip, npm, cargo, etc.).
4. Initialize any required config files (package.json, pyproject.toml, Dockerfile, etc.).
5. Make sure the project is functional — it should build and run without errors.
6. Do NOT create files outside the current working directory.

CRITICAL FINAL STEP:
After you have finished building the project, you MUST create a file called `arlo_manifest.json` in the current working directory. This file must contain valid JSON matching this exact schema:

{BUILDER_RESULT_SCHEMA}

- List ALL files you created in the artifacts array (relative paths).
- Include all commands you ran in build_commands_run.
- If there are steps the user needs to take to run the project, put them in notes.
- The arlo_manifest.json file is required. Do not skip this step."""
