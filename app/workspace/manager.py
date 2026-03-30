import os
from pathlib import Path

from app.core.config import settings


def create_job_workspace(job_id: str) -> str:
    """Create and return the path to a job workspace directory."""
    path = Path(settings.workspace_root) / f"job-{job_id}"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def validate_workspace_path(path: str) -> bool:
    """Ensure path is under the workspace root. Prevents path traversal."""
    resolved = os.path.realpath(path)
    root = os.path.realpath(settings.workspace_root)
    return resolved.startswith(root + os.sep) or resolved == root


def scan_workspace_artifacts(workspace_path: str) -> list[dict]:
    """Walk the workspace and return a list of files with relative paths and sizes.

    Returns a list of dicts: {"path": "relative/path", "size_bytes": 123, "is_dir": False}
    Skips hidden files/directories (starting with .).
    """
    root = Path(workspace_path)
    if not root.exists():
        return []

    artifacts = []
    for item in sorted(root.rglob("*")):
        # Skip hidden files and common noise
        parts = item.relative_to(root).parts
        if any(part.startswith(".") for part in parts):
            continue
        if any(part in ("__pycache__", "node_modules", ".git") for part in parts):
            continue

        artifacts.append({
            "path": str(item.relative_to(root)),
            "size_bytes": item.stat().st_size if item.is_file() else 0,
            "is_dir": item.is_dir(),
        })

    return artifacts
