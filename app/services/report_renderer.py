"""Render a synthesis result into HTML email body + plaintext + PDF.

Round 5: the approval-gate notification needs a readable document that
the user can consume on their phone. This module takes the validated
synthesis JSON (shape defined by ``SynthesisResult`` in
``app.workflows.schemas``) and produces three outputs:

1. **HTML body** — inline CSS, mobile-friendly, rendered by any modern
   email client. Each ranking is a card with a prominent "Build this
   one" button that links to the signed approval URL.

2. **Plaintext fallback** — a readable text version for clients that
   don't render HTML (rare but exists). Same content, no markup.

3. **PDF bytes** — the same HTML rendered via ``weasyprint`` for
   archival/offline reading. Attached to the email as a fallback so
   the user can save it even if the email itself gets deleted.

The HTML template is a single string constant at the top of the file
for easy editing. No template engine dependency.
"""

from __future__ import annotations

import html
import logging
import uuid
from typing import Any

logger = logging.getLogger("arlo.report_renderer")


# ─────────────────────────────────────────────────────────────────────
# Inline HTML template with mobile-friendly CSS
# ─────────────────────────────────────────────────────────────────────

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Arlo — Ranked Startup Opportunities</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    color: #1a1a1a;
    background: #f5f5f7;
    margin: 0;
    padding: 16px;
    line-height: 1.5;
  }}
  .container {{ max-width: 680px; margin: 0 auto; }}
  h1 {{ font-size: 22px; margin: 0 0 4px 0; }}
  h2 {{ font-size: 16px; margin: 20px 0 8px 0; color: #555; font-weight: 600; }}
  .meta {{ color: #888; font-size: 12px; margin-bottom: 20px; }}
  .summary {{
    background: #fff;
    padding: 16px;
    border-radius: 10px;
    border-left: 4px solid #4a6cf7;
    margin-bottom: 20px;
    font-size: 14px;
  }}
  .card {{
    background: #fff;
    padding: 18px 16px;
    border-radius: 10px;
    margin-bottom: 14px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  }}
  .rank {{ color: #4a6cf7; font-weight: 700; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .name {{ font-size: 18px; font-weight: 700; margin: 2px 0 4px 0; }}
  .liner {{ color: #555; font-size: 14px; margin-bottom: 12px; }}
  .score-row {{
    background: #f0f2fa;
    border-radius: 6px;
    padding: 10px 12px;
    font-size: 13px;
    margin: 10px 0;
    font-family: 'SF Mono', Monaco, Menlo, monospace;
  }}
  .total-score {{ font-size: 22px; font-weight: 700; color: #4a6cf7; }}
  .field {{ margin: 10px 0; font-size: 14px; }}
  .field-label {{ color: #888; font-size: 11px; text-transform: uppercase; letter-spacing: 0.4px; }}
  .field-value {{ color: #1a1a1a; margin-top: 2px; }}
  ul.risks {{ margin: 6px 0 0 0; padding-left: 20px; font-size: 13px; color: #666; }}
  .button {{
    display: inline-block;
    background: #4a6cf7;
    color: #ffffff !important;
    text-decoration: none;
    padding: 12px 22px;
    border-radius: 8px;
    font-weight: 600;
    margin-top: 14px;
    font-size: 14px;
  }}
  .skip {{
    display: inline-block;
    color: #888 !important;
    text-decoration: none;
    padding: 12px 22px;
    margin-top: 14px;
    font-size: 13px;
  }}
  .footer {{ color: #aaa; font-size: 11px; text-align: center; margin-top: 24px; }}
  .cost {{ color: #888; font-size: 12px; }}
</style>
</head>
<body>
  <div class="container">
    <h1>Research complete — pick an idea to build</h1>
    <div class="meta">Workflow {workflow_id}</div>
    <div class="cost">{cost_line}</div>

    <div class="summary">
      <strong>Executive summary</strong><br>
      {executive_summary}
    </div>

    <h2>Ranked opportunities</h2>
    {rankings_html}

    <div style="text-align: center;">
      <a href="{skip_link}" class="skip">Skip — end workflow without building</a>
    </div>

    <div class="footer">
      Arlo Runtime · Generated {workflow_id}
    </div>
  </div>
</body>
</html>
"""


_CARD_TEMPLATE = """
<div class="card">
  <div class="rank">Rank #{rank}</div>
  <div class="name">{name}</div>
  <div class="liner">{one_liner}</div>

  <div class="score-row">
    <span class="total-score">{total_score:.1f}</span>/100 &nbsp;·&nbsp;
    timing {market_timing}/10 &nbsp;·&nbsp;
    defensibility {defensibility}/10 &nbsp;·&nbsp;
    feasibility {solo_dev_feasibility}/10 &nbsp;·&nbsp;
    revenue {revenue_potential}/10 &nbsp;·&nbsp;
    evidence {evidence_quality}/10
  </div>

  <div class="field">
    <div class="field-label">What to build</div>
    <div class="field-value">{what_to_build}</div>
  </div>

  <div class="field">
    <div class="field-label">Core user journey</div>
    <div class="field-value">{core_user_journey}</div>
  </div>

  <div class="field">
    <div class="field-label">Tech stack · Build time</div>
    <div class="field-value">{tech_stack} · {build_time_weeks} weeks</div>
  </div>

  <div class="field">
    <div class="field-label">Risky assumption</div>
    <div class="field-value">{risky_assumption}</div>
  </div>

  {risks_block}

  <a href="{approval_link}" class="button">Build this one →</a>
</div>
"""


def _esc(value: Any) -> str:
    """HTML-escape a value, safely handling None and non-strings."""
    if value is None:
        return ""
    return html.escape(str(value))


def _render_rankings_html(
    rankings: list[dict],
    approval_links: dict[int, str],
) -> str:
    """Render the list of ranking cards as HTML."""
    cards: list[str] = []
    for ranking in rankings:
        rank = ranking.get("rank")
        if rank is None:
            continue
        scores = ranking.get("scores") or {}
        mvp = ranking.get("mvp_spec") or {}
        risks = ranking.get("surviving_risks") or []
        risks_html = ""
        if risks:
            risks_items = "".join(f"<li>{_esc(r)}</li>" for r in risks[:5])
            risks_html = (
                f'<div class="field">'
                f'<div class="field-label">Surviving risks</div>'
                f'<ul class="risks">{risks_items}</ul>'
                f'</div>'
            )
        approval_link = approval_links.get(int(rank), "#")

        card = _CARD_TEMPLATE.format(
            rank=_esc(rank),
            name=_esc(ranking.get("name", "Unnamed")),
            one_liner=_esc(ranking.get("one_liner", "")),
            total_score=float(ranking.get("total_score") or 0),
            market_timing=_esc(scores.get("market_timing", "?")),
            defensibility=_esc(scores.get("defensibility", "?")),
            solo_dev_feasibility=_esc(scores.get("solo_dev_feasibility", "?")),
            revenue_potential=_esc(scores.get("revenue_potential", "?")),
            evidence_quality=_esc(scores.get("evidence_quality", "?")),
            what_to_build=_esc(mvp.get("what_to_build", "")),
            core_user_journey=_esc(mvp.get("core_user_journey", "")),
            tech_stack=_esc(mvp.get("tech_stack", "")),
            build_time_weeks=_esc(mvp.get("build_time_weeks", "?")),
            risky_assumption=_esc(mvp.get("risky_assumption", "")),
            risks_block=risks_html,
            approval_link=_esc(approval_link),
        )
        cards.append(card)
    return "\n".join(cards)


def _render_text_fallback(
    synthesis: dict,
    approval_links: dict[int, str],
    skip_link: str,
    workflow_cost_usd: float | None,
) -> str:
    """Plain-text version of the report. Mirrors the HTML but without markup."""
    lines: list[str] = []
    lines.append("ARLO — RANKED STARTUP OPPORTUNITIES")
    lines.append("=" * 50)
    if workflow_cost_usd is not None:
        lines.append(f"Research cost (API-equivalent): ${workflow_cost_usd:.4f}")
    lines.append("")
    summary = synthesis.get("executive_summary", "").strip()
    if summary:
        lines.append("EXECUTIVE SUMMARY")
        lines.append("-" * 50)
        lines.append(summary)
        lines.append("")
    lines.append("RANKED OPPORTUNITIES")
    lines.append("-" * 50)
    for r in synthesis.get("final_rankings") or []:
        rank = r.get("rank")
        if rank is None:
            continue
        scores = r.get("scores") or {}
        mvp = r.get("mvp_spec") or {}
        lines.append(f"\n#{rank}: {r.get('name', 'Unnamed')}")
        lines.append(f"   {r.get('one_liner', '')}")
        lines.append(
            f"   Total: {float(r.get('total_score') or 0):.1f}/100 · "
            f"timing {scores.get('market_timing','?')}/10 · "
            f"defensibility {scores.get('defensibility','?')}/10 · "
            f"feasibility {scores.get('solo_dev_feasibility','?')}/10 · "
            f"revenue {scores.get('revenue_potential','?')}/10"
        )
        lines.append(f"   What: {mvp.get('what_to_build', '')}")
        lines.append(f"   Journey: {mvp.get('core_user_journey', '')}")
        lines.append(f"   Stack: {mvp.get('tech_stack', '')} ({mvp.get('build_time_weeks', '?')} weeks)")
        lines.append(f"   Risky assumption: {mvp.get('risky_assumption', '')}")
        risks = r.get("surviving_risks") or []
        if risks:
            lines.append("   Risks:")
            for risk in risks[:5]:
                lines.append(f"     - {risk}")
        approval_link = approval_links.get(int(rank))
        if approval_link:
            lines.append(f"   BUILD THIS ONE: {approval_link}")
    lines.append("")
    lines.append(f"Skip and end workflow: {skip_link}")
    return "\n".join(lines)


def render_synthesis_report(
    synthesis: dict,
    workflow_id: uuid.UUID,
    approval_links: dict[int, str],
    skip_link: str,
    workflow_cost_usd: float | None = None,
) -> tuple[str, str, bytes]:
    """Render the synthesis report into (html_body, text_fallback, pdf_bytes).

    Args:
        synthesis: The parsed SynthesisResult dict (with ``final_rankings``
            and ``executive_summary`` keys).
        workflow_id: The workflow UUID (used for footer / subject line).
        approval_links: ``{rank_number: signed_url}`` mapping. Each ranking
            card gets a "Build this one" button linking to its URL.
        skip_link: Signed URL for the "skip without building" option
            (choice=0).
        workflow_cost_usd: Optional cost so far (nullable; shown only when
            present).

    Returns:
        A tuple ``(html_body, text_fallback, pdf_bytes)`` ready to be
        handed to ``send_email``. PDF bytes start with ``%PDF``.
    """
    rankings = synthesis.get("final_rankings") or []
    cost_line = (
        f"Research cost so far (API-equivalent): ${workflow_cost_usd:.4f}"
        if workflow_cost_usd is not None
        else ""
    )
    executive_summary = synthesis.get("executive_summary", "").strip()

    html_body = _HTML_TEMPLATE.format(
        workflow_id=_esc(workflow_id),
        cost_line=_esc(cost_line),
        executive_summary=_esc(executive_summary).replace("\n", "<br>"),
        rankings_html=_render_rankings_html(rankings, approval_links),
        skip_link=_esc(skip_link),
    )
    text_fallback = _render_text_fallback(synthesis, approval_links, skip_link, workflow_cost_usd)

    # weasyprint is imported lazily so tests that don't need PDF output
    # (e.g. local runs without system deps installed) can still import
    # this module.
    try:
        import weasyprint
        pdf_bytes = weasyprint.HTML(string=html_body).write_pdf()
    except Exception:
        logger.exception("PDF rendering failed; returning empty bytes")
        pdf_bytes = b""

    return html_body, text_fallback, pdf_bytes
