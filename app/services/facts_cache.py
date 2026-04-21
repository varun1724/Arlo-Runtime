"""Cross-run facts cache.

A read-only JSON file (default ``/workspaces/cross_run_facts.json``)
lets the user stash facts that every pipeline run should know without
re-discovering from web search — regulatory deadlines, funded
competitors, recent incumbent moves, and "dead playbook" patterns.

The cache is injected into ``initial_context["known_facts"]`` at
workflow creation and referenced from the landscape_scan prompt. A
missing file, empty JSON, or parse error all degrade gracefully to
an empty block so first-run installs don't break.

File format::

    {
      "regulatory_events": [
        {"name": "FSMA 204 Jan 2026", "impact": "..."},
        ...
      ],
      "incumbent_moves": [
        {"incumbent": "Intuit", "event": "Agentic AI launch", "date": "2025-07"},
        ...
      ],
      "funded_competitors": [
        {"name": "Anrok", "funding": "$525M", "vertical": "sales tax"},
        ...
      ],
      "dead_playbooks": [
        {"pattern": "thin AI wrapper over QBO",
         "reason": "Intuit ships it natively",
         "learned_from": "2026-04-21 accounting run"},
        ...
      ]
    }

Arbitrary additional top-level keys are rendered verbatim — the four
above are just the canonical buckets. The formatter passes through
any list of dict-shaped entries.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("arlo.facts_cache")


# Env-overridable so tests can point at a temp file. Production default
# is the shared workspaces volume mounted into every worker container.
DEFAULT_FACTS_PATH = os.environ.get(
    "ARLO_FACTS_CACHE_PATH", "/workspaces/cross_run_facts.json"
)


def load_facts(path: str | None = None) -> dict:
    """Load the facts file from disk. Returns an empty dict on any
    failure mode (missing file, parse error, permissions) — the cache
    is best-effort; a broken file must never block workflow creation.
    """
    target = Path(path or DEFAULT_FACTS_PATH)
    if not target.exists():
        return {}
    try:
        raw = target.read_text(encoding="utf-8")
        if not raw.strip():
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            logger.warning(
                "Facts cache at %s is not a JSON object (got %s); ignoring",
                target, type(data).__name__,
            )
            return {}
        return data
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to load facts cache at %s: %s", target, e)
        return {}


def format_facts_for_prompt(facts: dict) -> str:
    """Render a facts dict into a prompt-ready block. Empty dict → empty
    string (NOT the literal 'none known') so the prompt can render a
    clean "no prior facts available" message at its own discretion.

    Each top-level key becomes a section header and each entry in the
    section is rendered as a bullet. Entries are dicts; values are
    joined into a single line separated by ` | `. Non-dict entries are
    stringified.
    """
    if not facts:
        return ""

    lines: list[str] = []
    for section, entries in facts.items():
        if not isinstance(entries, list) or not entries:
            continue
        header = section.replace("_", " ").upper()
        lines.append(f"## {header}")
        for entry in entries:
            if isinstance(entry, dict):
                parts = [f"{k}: {v}" for k, v in entry.items() if v not in (None, "", [])]
                lines.append(f"- {' | '.join(parts)}")
            else:
                lines.append(f"- {entry}")
        lines.append("")  # blank line between sections

    return "\n".join(lines).strip()


def get_facts_block(path: str | None = None) -> str:
    """Convenience: load + format in one call. Returns the empty string
    if the cache is missing or empty — callers can check truthiness to
    decide whether to render a "no prior facts" clause.
    """
    return format_facts_for_prompt(load_facts(path))
