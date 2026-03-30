import pytest

from app.models.builder import BuilderResult


SAMPLE_RESULT = {
    "summary": "Created a FastAPI project with health endpoint and Docker setup.",
    "artifacts": [
        {
            "path": "app/main.py",
            "artifact_type": "file",
            "description": "FastAPI application entry point with health endpoint",
        },
        {
            "path": "Dockerfile",
            "artifact_type": "file",
            "description": "Docker container configuration",
        },
        {
            "path": "requirements.txt",
            "artifact_type": "file",
            "description": "Python dependencies",
        },
    ],
    "build_commands_run": ["pip install fastapi uvicorn", "pip freeze > requirements.txt"],
    "notes": "Run `docker build -t myapp .` to build the container.",
}


@pytest.mark.asyncio
async def test_builder_result_parses():
    result = BuilderResult.model_validate(SAMPLE_RESULT)
    assert result.summary.startswith("Created")
    assert len(result.artifacts) == 3
    assert result.artifacts[0].path == "app/main.py"
    assert len(result.build_commands_run) == 2
    assert result.notes is not None


@pytest.mark.asyncio
async def test_builder_result_roundtrips_json():
    result = BuilderResult.model_validate(SAMPLE_RESULT)
    json_str = result.model_dump_json()
    parsed = BuilderResult.model_validate_json(json_str)
    assert parsed == result


@pytest.mark.asyncio
async def test_builder_result_notes_optional():
    data = {**SAMPLE_RESULT, "notes": None}
    result = BuilderResult.model_validate(data)
    assert result.notes is None
