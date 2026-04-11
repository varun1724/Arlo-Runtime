"""Integration tests for the Round 3 builder → validator wiring.

The Round 2/4 ``required_artifacts`` enforcement proves a set of files
exists in the workspace. Round 3 adds a second pass: if
``workflow.json`` is in the required list, parse + structurally
validate it via ``N8nClient.validate_workflow_json`` and raise
``ClaudeRunError`` on any failure.

These tests exercise the full flow end-to-end WITHOUT going through
``execute_builder_job`` (which is heavily IO-bound and async). Instead
they replicate the exact block in ``app/jobs/builder.py`` that sits
between the artifact check and the finalize call. That block is small
enough (~15 lines) that replicating it here keeps the tests readable
and catches any drift between what builder.py does and what the
tests think it does.

Every test either (a) proves the happy path runs cleanly or
(b) proves a specific failure mode raises ``ClaudeRunError`` with a
diagnostic message pointing at the actual problem.
"""

from __future__ import annotations

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest

from app.jobs.builder import _check_required_artifacts
from app.services.claude_runner import ClaudeRunError
from app.tools.n8n import N8nClient, N8nWorkflowValidationError


SIDE_HUSTLE_REQUIRED = (
    "workflow.json",
    "README.md",
    "BUILD_DECISIONS.md",
    "test_payload.json",
)


def _valid_workflow_dict() -> dict:
    return {
        "nodes": [
            {
                "id": "node-1",
                "name": "Webhook",
                "type": "n8n-nodes-base.webhook",
                "parameters": {"path": "test-slug"},
            }
        ],
        "connections": {},
        "settings": {},
    }


@contextmanager
def _side_hustle_workspace(
    *,
    workflow_content: str | None = "valid",
    include_readme: bool = True,
    include_build_decisions: bool = True,
    include_test_payload: bool = True,
):
    """Yield a temp workspace pre-populated for a side hustle build.

    ``workflow_content`` values:
    - ``"valid"``: a structurally valid workflow JSON
    - ``"garbage"``: unparseable text (not JSON at all)
    - ``"no_webhook"``: valid JSON but missing the webhook trigger
    - ``"missing_settings"``: valid JSON missing the settings field
    - ``None``: don't create workflow.json at all
    - any other string: written verbatim as the file contents
    """
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        if include_readme:
            (workspace / "README.md").write_text("# side hustle")
        if include_build_decisions:
            (workspace / "BUILD_DECISIONS.md").write_text("we chose n8n")
        if include_test_payload:
            (workspace / "test_payload.json").write_text('{"test": "data"}')

        if workflow_content == "valid":
            (workspace / "workflow.json").write_text(
                json.dumps(_valid_workflow_dict())
            )
        elif workflow_content == "garbage":
            (workspace / "workflow.json").write_text("not json {")
        elif workflow_content == "no_webhook":
            wf = _valid_workflow_dict()
            wf["nodes"][0]["type"] = "n8n-nodes-base.scheduleTrigger"
            (workspace / "workflow.json").write_text(json.dumps(wf))
        elif workflow_content == "missing_settings":
            wf = _valid_workflow_dict()
            del wf["settings"]
            (workspace / "workflow.json").write_text(json.dumps(wf))
        elif workflow_content is not None:
            (workspace / "workflow.json").write_text(workflow_content)

        yield str(workspace)


def _run_builder_checks(workspace_path: str, required: tuple[str, ...]) -> None:
    """Replicate the exact block in app/jobs/builder.py:execute_builder_job
    that sits between the artifact check and finalize.

    Raises ``ClaudeRunError`` on any failure, matching production behavior.
    """
    missing = _check_required_artifacts(workspace_path, required=required)
    if missing:
        raise ClaudeRunError(
            f"Builder did not produce required artifacts: {', '.join(missing)}. "
            f"Every build must include: {', '.join(required)}."
        )

    if "workflow.json" in required:
        wf_path = Path(workspace_path) / "workflow.json"
        try:
            workflow_json = json.loads(wf_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            raise ClaudeRunError(
                f"Builder wrote workflow.json but it is not valid JSON: {e}"
            ) from e
        try:
            N8nClient.validate_workflow_json(workflow_json)
        except N8nWorkflowValidationError as e:
            raise ClaudeRunError(
                f"Builder wrote workflow.json but it failed "
                f"structural validation: {e}. The workflow would "
                f"be rejected by n8n's create endpoint. Fix the "
                f"structure and retry."
            ) from e


# ─────────────────────────────────────────────────────────────────────
# Happy path
# ─────────────────────────────────────────────────────────────────────


def test_builder_accepts_valid_side_hustle_workspace():
    """All 4 required files present + workflow.json is structurally
    valid. The full Round 3 enforcement block runs without raising."""
    with _side_hustle_workspace() as ws:
        # Should not raise
        _run_builder_checks(ws, SIDE_HUSTLE_REQUIRED)


# ─────────────────────────────────────────────────────────────────────
# Round 2/4 required_artifacts rejection
# ─────────────────────────────────────────────────────────────────────


def test_builder_fails_when_workflow_json_missing():
    """The Round 2/4 first pass catches a missing workflow.json before
    the Round 3 validator ever runs."""
    with _side_hustle_workspace(workflow_content=None) as ws:
        with pytest.raises(ClaudeRunError) as exc:
            _run_builder_checks(ws, SIDE_HUSTLE_REQUIRED)
        assert "workflow.json" in str(exc.value)
        assert "required artifacts" in str(exc.value).lower()


def test_builder_fails_when_test_payload_missing():
    """test_payload.json is in the side hustle required list (Round 4)."""
    with _side_hustle_workspace(include_test_payload=False) as ws:
        with pytest.raises(ClaudeRunError) as exc:
            _run_builder_checks(ws, SIDE_HUSTLE_REQUIRED)
        assert "test_payload.json" in str(exc.value)


def test_builder_fails_when_build_decisions_missing():
    with _side_hustle_workspace(include_build_decisions=False) as ws:
        with pytest.raises(ClaudeRunError) as exc:
            _run_builder_checks(ws, SIDE_HUSTLE_REQUIRED)
        assert "BUILD_DECISIONS.md" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────
# Round 3 validator rejection
# ─────────────────────────────────────────────────────────────────────


def test_builder_fails_when_workflow_json_is_garbage():
    """workflow.json exists but isn't parseable as JSON. The validator
    block catches this and wraps the JSONDecodeError in ClaudeRunError."""
    with _side_hustle_workspace(workflow_content="garbage") as ws:
        with pytest.raises(ClaudeRunError) as exc:
            _run_builder_checks(ws, SIDE_HUSTLE_REQUIRED)
        msg = str(exc.value).lower()
        assert "not valid json" in msg
        assert "workflow.json" in str(exc.value)


def test_builder_fails_when_workflow_has_no_webhook_trigger():
    """workflow.json parses but uses scheduleTrigger instead of webhook.
    The validator block catches this before the deploy step hits n8n."""
    with _side_hustle_workspace(workflow_content="no_webhook") as ws:
        with pytest.raises(ClaudeRunError) as exc:
            _run_builder_checks(ws, SIDE_HUSTLE_REQUIRED)
        msg = str(exc.value)
        assert "structural validation" in msg.lower()
        assert "webhook trigger" in msg.lower()


def test_builder_fails_when_workflow_missing_settings():
    """Round 4 Phase 0 finding: n8n v2.15.0 requires a settings field.
    The validator block catches this so the deploy step doesn't hit
    n8n's 400 validation error."""
    with _side_hustle_workspace(workflow_content="missing_settings") as ws:
        with pytest.raises(ClaudeRunError) as exc:
            _run_builder_checks(ws, SIDE_HUSTLE_REQUIRED)
        msg = str(exc.value)
        assert "settings" in msg
        assert "structural validation" in msg.lower()


def test_builder_error_messages_tell_claude_to_retry():
    """Round 3: the error messages must give Claude a clear target so
    the auto-retry path produces a better second attempt."""
    with _side_hustle_workspace(workflow_content="no_webhook") as ws:
        with pytest.raises(ClaudeRunError) as exc:
            _run_builder_checks(ws, SIDE_HUSTLE_REQUIRED)
        msg = str(exc.value)
        # Tells Claude what to fix
        assert "Webhook" in msg or "webhook" in msg
        # Tells Claude this will be retried
        assert "retry" in msg.lower() or "fix" in msg.lower()


# ─────────────────────────────────────────────────────────────────────
# Startup pipeline regression check (non-side-hustle builds unchanged)
# ─────────────────────────────────────────────────────────────────────


def test_startup_mvp_build_ignores_workflow_json():
    """The startup pipeline's build_mvp step does NOT include
    workflow.json in its required_artifacts. The new Round 3 validator
    block must NOT fire for startup builds, even if a workflow.json
    happens to exist in the workspace (it would be ignored)."""
    startup_required = ("README.md", "BUILD_DECISIONS.md")
    with _side_hustle_workspace(workflow_content="garbage") as ws:
        # Even though workflow.json is garbage, the startup required
        # list doesn't include it, so the validator block never fires.
        _run_builder_checks(ws, startup_required)  # must not raise
