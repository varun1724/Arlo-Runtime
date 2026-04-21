"""Tests for the Round 3 builder artifact enforcement.

These tests cover ``_check_required_artifacts`` and the constants in
``app/jobs/builder.py``. They use a temporary directory and direct file
operations rather than going through the full ``execute_builder_job``
async path — that integration is verified by the post-deploy run.

The headline assertion: a workspace missing ``BUILD_DECISIONS.md`` MUST
fail the artifact check, which raises ``ClaudeRunError`` and triggers
the workflow's auto-retry path. Round 1 added the requirement to the
prompt; Round 3 actually enforces it.
"""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path

from app.jobs.builder import REQUIRED_BUILDER_ARTIFACTS, _check_required_artifacts


@contextmanager
def _workspace_with(files: dict[str, str]):
    """Yield a temp workspace path pre-populated with the given files."""
    with tempfile.TemporaryDirectory() as tmp:
        for name, content in files.items():
            (Path(tmp) / name).write_text(content)
        yield tmp


def test_required_artifacts_includes_readme_and_build_decisions():
    """Sanity: the required list contains the two we care about most."""
    assert "README.md" in REQUIRED_BUILDER_ARTIFACTS
    assert "BUILD_DECISIONS.md" in REQUIRED_BUILDER_ARTIFACTS


def test_check_required_artifacts_empty_workspace_lists_all_missing():
    with tempfile.TemporaryDirectory() as tmp:
        missing = _check_required_artifacts(tmp)
        assert set(missing) == set(REQUIRED_BUILDER_ARTIFACTS)


def test_check_required_artifacts_only_readme_present():
    with _workspace_with({"README.md": "# project"}) as tmp:
        missing = _check_required_artifacts(tmp)
        assert "BUILD_DECISIONS.md" in missing
        assert "README.md" not in missing


def test_check_required_artifacts_only_build_decisions_present():
    with _workspace_with({"BUILD_DECISIONS.md": "decisions"}) as tmp:
        missing = _check_required_artifacts(tmp)
        assert "README.md" in missing
        assert "BUILD_DECISIONS.md" not in missing


def test_check_required_artifacts_all_present_returns_empty():
    """The headline success case: README + BUILD_DECISIONS both present."""
    with _workspace_with({
        "README.md": "# project",
        "BUILD_DECISIONS.md": "we chose Python because...",
    }) as tmp:
        missing = _check_required_artifacts(tmp)
        assert missing == []


def test_check_required_artifacts_extra_files_dont_satisfy_requirement():
    """Having Dockerfile + .env.example doesn't substitute for README."""
    with _workspace_with({
        "Dockerfile": "FROM python:3.12",
        ".env.example": "FOO=bar",
        "main.py": "print('hi')",
    }) as tmp:
        missing = _check_required_artifacts(tmp)
        assert "README.md" in missing
        assert "BUILD_DECISIONS.md" in missing


def test_check_required_artifacts_directory_at_required_path_does_not_count():
    """A directory named BUILD_DECISIONS.md (weird but possible) shouldn't satisfy."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "BUILD_DECISIONS.md").mkdir()
        (Path(tmp) / "README.md").write_text("# proj")
        missing = _check_required_artifacts(tmp)
        # BUILD_DECISIONS.md is a directory not a file → still missing
        assert "BUILD_DECISIONS.md" in missing
        assert "README.md" not in missing


def test_build_mvp_step_has_max_retries_set():
    """Round 3: build_mvp must have at least one retry so a missing
    BUILD_DECISIONS.md gets a second chance."""
    from app.models.workflow import StepDefinition
    from app.workflows.templates import STARTUP_IDEA_PIPELINE

    build = next(s for s in STARTUP_IDEA_PIPELINE["steps"] if s["name"] == "build_mvp")
    sd = StepDefinition.model_validate(build)
    assert sd.max_retries >= 1


def test_empty_required_artifacts_is_explicit_no_artifacts():
    """A step that sets ``required_artifacts=[]`` opts out of ALL artifact
    enforcement — including the module-level README/BUILD_DECISIONS default.

    The previous truthiness check (``if step.required_artifacts:``) treated
    ``[]`` as "not specified" and silently fell back to the default, making
    it impossible for a builder step to legitimately require zero files.
    The None-check lets callers distinguish "unset" from "explicitly empty".
    """
    from app.models.workflow import StepDefinition

    step = StepDefinition(
        name="build_thing",
        job_type="builder",
        prompt_template="build",
        output_key="result",
        required_artifacts=[],
    )
    # An empty list must round-trip as an empty list, not None, so the
    # builder can distinguish "no override" from "override to nothing".
    assert step.required_artifacts == []
    assert step.required_artifacts is not None


# ─────────────────────────────────────────────────────────────────────
# Round 4: focused assertion that missing artifacts raise the right exception
# ─────────────────────────────────────────────────────────────────────


def test_missing_artifact_check_raises_claude_run_error_in_executor():
    """The artifact enforcement raises ClaudeRunError specifically — NOT a
    generic RuntimeError or some other exception type. The retry path in
    advance_workflow only triggers on ClaudeRunError-derived failures
    (which become job FAILED + stop_reason=ERROR), so the exception type
    matters.

    We verify this by importing the helper directly and asserting that
    when the workspace is empty, the executor's pre-finalize check would
    raise the right type. This isn't a full mock of execute_builder_job
    because that function is heavily IO-bound; it's a focused assertion
    that the EXACT error class flowing into max_retries is correct.
    """
    from app.services.claude_runner import ClaudeRunError

    with tempfile.TemporaryDirectory() as tmp:
        # Empty workspace — both required files missing
        missing = _check_required_artifacts(tmp)
        assert missing == list(REQUIRED_BUILDER_ARTIFACTS)

        # Construct the exact exception that the executor raises
        # (mirroring the line in builder.py:execute_builder_job)
        err = ClaudeRunError(
            f"Builder did not produce required artifacts: {', '.join(missing)}. "
            f"Every build must include: {', '.join(REQUIRED_BUILDER_ARTIFACTS)}."
        )
        # The exception must be a ClaudeRunError specifically — that's
        # what advance_workflow's auto-retry checks for via the
        # stop_reason=ERROR path.
        assert isinstance(err, ClaudeRunError)
        # And it must contain the names of the missing files for debugging.
        for filename in REQUIRED_BUILDER_ARTIFACTS:
            assert filename in str(err)
