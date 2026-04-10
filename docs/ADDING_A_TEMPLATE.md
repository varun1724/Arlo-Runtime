# Adding a New Workflow Template

A short, copy-pasteable recipe for adding a new multi-step workflow to
arlo-runtime. Read this if you want to add something like a "blog post
research pipeline" or a "competitive analysis pipeline" alongside the
existing `startup_idea_pipeline`.

The worked example throughout is `STARTUP_IDEA_PIPELINE` in
`app/workflows/templates.py`. Read that file alongside this guide.

## What you'll touch

| File | Why |
|---|---|
| `app/workflows/templates.py` | Define the steps |
| `app/workflows/schemas.py` | Define the Pydantic output schema for each research step |
| `tests/fixtures/startup_pipeline_fixtures.py` (or a sibling file) | VALID/MINIMAL/INVALID payloads |
| `tests/test_startup_schemas.py` (or a sibling file) | Schema unit tests |
| `tests/test_prompt_schema_alignment.py` | Catches drift between prompt and schema |

That's it. Once these five things are in place, the new template is
discoverable via `GET /workflows/templates`, can be created via
`POST /workflows/from-template/{template_id}`, and benefits from every
existing workflow feature: schema validation, retry, context pruning,
recovery loops, cost tracking, friendly error messages.

---

## Step 1 — Define the steps in `templates.py`

Each step is a dict with these keys (only `name`, `job_type`,
`prompt_template`, and `output_key` are strictly required; the rest are
optional but strongly recommended):

```python
{
    "name": "my_step",                         # unique within the pipeline
    "job_type": "research",                    # or "builder"
    "prompt_template": "...",                  # uses {context_key} substitution
    "output_key": "my_step_output",            # where the result lands in context
    "condition": {                             # optional: skip if condition fails
        "field": "previous_step_output",
        "operator": "not_empty",
    },
    "timeout_override": 1800,                  # seconds; defaults to settings.research_timeout_seconds
    "max_retries": 2,                          # auto-retry on failure (Round 2)
    "output_schema": "my_pipeline_v1",         # name in STEP_OUTPUT_SCHEMAS (Round 2)
    "context_inputs": ["previous_step_output"],# whitelist for prompt rendering (Round 2)
    "loop_to": 0,                              # optional: loop back to this step index
    "max_loop_count": 2,                       # max total executions of loop_to (counts initial)
    "loop_condition": {                        # optional: gate the loop on a condition (Round 3)
        "field": "previous_step_output",
        "operator": "survivor_count_below",
        "value": "3",
    },
    "requires_approval": False,                # if True, workflow pauses before this step
}
```

The full template wraps these steps:

```python
MY_NEW_PIPELINE = {
    "template_id": "my_new_pipeline",
    "name": "My New Pipeline",
    "description": "What it does and when to use it",
    "required_context": ["domain"],            # keys the user MUST provide at creation time
    "optional_context": ["focus_areas"],
    "steps": [ ...step dicts... ],
}
```

Then add it to the `TEMPLATES` dict at the bottom of `templates.py`:

```python
TEMPLATES = {
    "startup_idea_pipeline": STARTUP_IDEA_PIPELINE,
    "my_new_pipeline": MY_NEW_PIPELINE,
}
```

**Prompt template tips:**
- Use `{context_key}` for substitution. Missing keys render as
  `{unknown}` (defaultdict fallback in `_render_prompt`).
- Use `{{` and `}}` for literal braces (e.g. JSON examples in the prompt).
- Round 4: dict and list context values are JSON-encoded automatically.
  Plain strings pass through unchanged.
- The example JSON block at the bottom of every research prompt is
  required — it's parsed by the prompt-schema alignment test (see
  Step 5) so the prompt and schema can never drift out of sync.

## Step 2 — Define the Pydantic output schema in `schemas.py`

For every research step that has `output_schema` set, add a matching
Pydantic model in `app/workflows/schemas.py` and register it.

```python
class MyStepOutput(BaseModel):
    model_config = ConfigDict(extra="allow")  # forward compat for new fields

    title: str = Field(min_length=10)
    items: list[str] = Field(min_length=3)    # min_length catches silent empty failures
    score: int = Field(ge=1, le=10)           # bounds validation
    # ... more fields ...
```

Then register at the bottom of the file:

```python
STEP_OUTPUT_SCHEMAS: dict[str, type[BaseModel]] = {
    "startup_landscape_v1": LandscapeResult,
    # ... existing entries ...
    "my_pipeline_v1": MyStepOutput,
}
```

**Naming convention:** always use a `_v1` suffix. When you eventually
need to break the schema, you'll add `_v2` alongside `_v1` so in-flight
workflows don't crash.

**What `extra="allow"` does:** unknown fields are preserved during
validation. This means a future version of the prompt can add fields
without breaking old in-flight workflows. Use it on every model.

**What `min_length` does:** catches the "silent empty output" failure
mode. If Claude returns `{"items": []}`, schema validation fails →
ClaudeRunError → workflow auto-retries (per `max_retries`).

## Step 3 — Add fixtures in `tests/fixtures/`

Create golden samples for each schema. Reuse
`tests/fixtures/startup_pipeline_fixtures.py` as the worked example
(it has VALID, MINIMAL, and INVALID variants for every step).

```python
VALID_MY_STEP: dict = {
    "title": "A real-looking title",
    "items": ["item one", "item two", "item three"],
    "score": 8,
    # ...
}

MINIMAL_MY_STEP: dict = {  # smallest legal payload
    "title": "exactly ten",
    "items": ["a", "b", "c"],
    "score": 1,
}

INVALID_MY_STEP_TOO_FEW_ITEMS: dict = {
    **MINIMAL_MY_STEP,
    "items": ["only one"],  # below min_length=3
}
```

Fixtures double as living documentation of your output contract. Every
prompt edit must keep producing fixture-compatible JSON.

## Step 4 — Schema unit tests in `tests/test_*_schemas.py`

Mirror the pattern in `tests/test_startup_schemas.py`. The minimum:

```python
def test_my_step_valid():
    result = MyStepOutput.model_validate(VALID_MY_STEP)
    assert result.score == 8

def test_my_step_minimal():
    MyStepOutput.model_validate(MINIMAL_MY_STEP)  # must not raise

def test_my_step_rejects_too_few_items():
    with pytest.raises(ValidationError):
        MyStepOutput.model_validate(INVALID_MY_STEP_TOO_FEW_ITEMS)

def test_my_step_allows_extra_fields():
    payload = {**VALID_MY_STEP, "future_field": "preserved"}
    result = MyStepOutput.model_validate(payload)
    assert result.model_dump()["future_field"] == "preserved"
```

## Step 5 — Prompt-schema alignment test in `tests/test_prompt_schema_alignment.py`

This is the test that **catches drift** between your prompt and your
schema. It extracts the JSON example block from your prompt template,
populates it with placeholder values, and validates against your
Pydantic model.

Open `tests/test_prompt_schema_alignment.py` and add:

```python
def test_my_step_prompt_example_matches_schema():
    _alignment_check(
        "my_step",                  # step name
        MyStepOutput,               # the Pydantic class
        repeat_list_items={
            "items": 3,             # if the schema needs min_length, repeat the example item
        },
    )
```

This test fails immediately if you change a field name in either the
prompt or the schema without updating the other. Round 1 prompt
quality is enforced by this test for the existing `startup_idea_pipeline`
— do the same for your new template.

## Step 6 — Run the test suite

```bash
# Pure unit tests (no DB needed)
python3 -m pytest tests/test_startup_schemas.py tests/test_prompt_schema_alignment.py --noconftest -v

# Full suite (inside docker)
docker compose exec -T api pytest tests/ -v
```

If everything is green, your new template is ready to ship.

## How the runtime uses your template

For reference, here's what happens when a user creates a workflow from
your template via `POST /workflows/from-template/{template_id}`:

1. **`app/api/workflow_routes.py:create_workflow_from_template`** validates
   that all `required_context` keys are present in the request body, then
   creates a `WorkflowRow`.
2. **`app/services/workflow_service.create_workflow`** inserts the row and
   creates the first step's job. Each step's `output_schema` and
   `context_inputs` are stored as part of the step JSON on the workflow row.
3. **`app/workers/main.py`** polls for queued jobs and dispatches each to
   the appropriate handler in `app/jobs/`.
4. For research jobs, **`app/jobs/research.py:execute_research_job`** loads
   the StepDefinition from the workflow row, looks up the schema in
   `STEP_OUTPUT_SCHEMAS`, runs Claude with the rendered prompt, validates
   the output strictly, and stores the normalized JSON as `result_data`.
5. On success, **`app/services/workflow_service.advance_workflow`** evaluates
   conditions, evaluates `loop_condition` (Round 3), and creates the next
   step's job — applying `_prune_context` based on `context_inputs`.
6. Validation failures raise `ClaudeRunError`, which marks the job FAILED
   and triggers the existing `max_retries` auto-retry path.
7. Cost tracking from Round 3 and live progress streaming from Round 4
   work automatically — you don't need to do anything in your template.

## When your template needs something the framework doesn't have

If your template needs a feature that doesn't exist yet (a new condition
operator, a new job type, etc.), the right move is usually to extend the
framework rather than work around it. Look at how Round 3's
`survivor_count_below` operator was added in `_evaluate_condition`
(`app/services/workflow_service.py`) — it's a few lines of code and a
field on `StepCondition`. Same pattern works for new operators.

## Common gotchas

- **Forgot to add the schema to `STEP_OUTPUT_SCHEMAS`.** The lookup
  silently degrades to loose mode. The completeness test in
  `tests/test_startup_schemas.py::test_registry_completeness` catches
  this — write a similar one for your template.
- **Used `{key}` in a JSON example block without `{{ }}`.** The renderer
  thinks `{key}` is a substitution placeholder and replaces it with
  whatever's in context (or `{unknown}`). Always escape literal braces.
- **Set `min_length` too aggressively.** The schema validates EVERY job
  output; if Claude can plausibly fail to produce 5 items, don't require
  5. Use 3 as a floor for "show some real effort" and let synthesis
  filter from there.
- **Forgot `context_inputs` on a step that doesn't need everything.** By
  default the prompt receives the entire context dict. Use
  `context_inputs=[...]` to keep prompts small — see how `build_mvp` uses
  `context_inputs=["selected_idea"]`.

## See also

- `RESEARCH_IMPROVEMENTS.md` — the running tracker of pipeline upgrades
  and the rationale behind each round's changes.
- `app/workflows/templates.py` — the worked example
  (`STARTUP_IDEA_PIPELINE`).
- `app/services/workflow_service.py` — the runtime that consumes your
  template (`advance_workflow`, `_evaluate_condition`, `_prune_context`).
