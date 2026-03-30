"""Prompt templates for Arlo job types."""

RESEARCH_REPORT_SCHEMA = """{
  "market_overview": "string — 2-4 paragraph overview of the market/domain",
  "opportunities": [
    {
      "name": "string — concise opportunity name",
      "description": "string — 2-3 sentence description",
      "evidence": ["string — specific data points, funding rounds, articles, or trends that support this opportunity"],
      "market_size_estimate": "string — estimated TAM/SAM with source if available",
      "competition_level": "low | medium | high",
      "feasibility": "low | medium | high"
    }
  ],
  "trends": ["string — key market trends driving opportunities"],
  "risks": ["string — risks and challenges in this market"],
  "top_recommendations": [
    {
      "name": "string — name matching one of the opportunities above",
      "reasoning": "string — why this is recommended, referencing evidence"
    }
  ]
}"""


def build_research_prompt(user_prompt: str) -> str:
    """Build the full prompt for a research job.

    The prompt instructs Claude to use web search, gather evidence,
    and produce a structured JSON opportunity report.
    """
    return f"""You are a startup research analyst. Your task is to research a market or domain and produce a structured opportunity report.

TASK: {user_prompt}

INSTRUCTIONS:
1. Use web search to find current, real data about this market/domain.
2. Identify at least 5 startup opportunities with evidence.
3. For each opportunity, provide specific evidence — funding rounds, market reports, competitor analysis, trend data.
4. Assess competition level and feasibility realistically.
5. Identify key market trends and risks.
6. Recommend the top 3 opportunities with clear reasoning.

OUTPUT FORMAT:
You must respond with ONLY valid JSON matching this exact schema (no markdown, no code fences, no explanation outside the JSON):

{RESEARCH_REPORT_SCHEMA}

IMPORTANT:
- Use web search to gather real, current information. Do not fabricate data.
- Market size estimates should cite sources when possible.
- Evidence should be specific and verifiable.
- Respond with ONLY the JSON object. No other text."""


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
