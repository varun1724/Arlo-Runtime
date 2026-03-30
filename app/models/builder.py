from __future__ import annotations

from pydantic import BaseModel


class BuilderArtifact(BaseModel):
    path: str
    artifact_type: str
    description: str


class BuilderResult(BaseModel):
    summary: str
    artifacts: list[BuilderArtifact]
    build_commands_run: list[str]
    notes: str | None = None
