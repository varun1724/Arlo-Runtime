"""Unit tests for N8nClient.validate_workflow_json (Round 3 safety net).

Pure unit tests — no DB, no httpx, no Claude. Every test constructs a
workflow dict in memory and asserts either acceptance or rejection
with a specific error message fragment.

The validator is the second line of defense for the side hustle
``build_n8n_workflow`` step. The first line is Round 4's
``required_artifacts`` check which proves ``workflow.json`` exists.
This validator proves it's a VALID n8n workflow — structurally
correct enough that the deploy step won't fail with an opaque 400
from n8n.

Every rejection is verified to include a specific field path in the
error message so Claude's auto-retry path gets a clear target.
"""

from __future__ import annotations

import pytest

from app.tools.n8n import N8nClient, N8nWorkflowValidationError


def _minimal_valid_workflow() -> dict:
    """Return the smallest workflow dict that passes every check."""
    return {
        "nodes": [
            {
                "id": "node-1",
                "name": "Webhook",
                "type": "n8n-nodes-base.webhook",
                "parameters": {"path": "my-slug"},
            }
        ],
        "connections": {},
        "settings": {},
    }


# ─────────────────────────────────────────────────────────────────────
# Happy path
# ─────────────────────────────────────────────────────────────────────


def test_accepts_minimal_valid_workflow():
    """Smallest possible workflow: one webhook trigger node, empty
    connections, empty settings. Must pass."""
    N8nClient.validate_workflow_json(_minimal_valid_workflow())


def test_accepts_webhook_plus_response_node():
    """Webhook trigger + respondToWebhook is a common pattern. The
    respond node is NOT a trigger so the 'exactly one webhook' rule
    must count it as zero."""
    wf = _minimal_valid_workflow()
    wf["nodes"].append(
        {
            "id": "node-2",
            "name": "Respond",
            "type": "n8n-nodes-base.respondToWebhook",
            "parameters": {},
        }
    )
    N8nClient.validate_workflow_json(wf)


def test_accepts_webhook_with_real_pipeline_nodes():
    """Realistic side hustle workflow: webhook → httpRequest → set → respond."""
    wf = {
        "nodes": [
            {
                "id": "n1",
                "name": "Webhook",
                "type": "n8n-nodes-base.webhook",
                "parameters": {"path": "deal-scanner"},
            },
            {
                "id": "n2",
                "name": "Fetch",
                "type": "n8n-nodes-base.httpRequest",
                "parameters": {"url": "https://api.example.com"},
            },
            {
                "id": "n3",
                "name": "Transform",
                "type": "n8n-nodes-base.set",
                "parameters": {},
            },
            {
                "id": "n4",
                "name": "Respond",
                "type": "n8n-nodes-base.respondToWebhook",
                "parameters": {},
            },
        ],
        "connections": {"Webhook": {"main": [[{"node": "Fetch"}]]}},
        "settings": {"callerPolicy": "workflowsFromSameOwner"},
    }
    N8nClient.validate_workflow_json(wf)


# ─────────────────────────────────────────────────────────────────────
# Top-level structure rejections
# ─────────────────────────────────────────────────────────────────────


def test_rejects_non_dict_input():
    with pytest.raises(N8nWorkflowValidationError) as exc:
        N8nClient.validate_workflow_json([])  # type: ignore[arg-type]
    assert "JSON object" in str(exc.value)


def test_rejects_none_input():
    with pytest.raises(N8nWorkflowValidationError):
        N8nClient.validate_workflow_json(None)  # type: ignore[arg-type]


def test_rejects_missing_nodes_field():
    with pytest.raises(N8nWorkflowValidationError) as exc:
        N8nClient.validate_workflow_json({"connections": {}, "settings": {}})
    assert "nodes" in str(exc.value)


def test_rejects_missing_connections_field():
    with pytest.raises(N8nWorkflowValidationError) as exc:
        N8nClient.validate_workflow_json({
            "nodes": [_minimal_valid_workflow()["nodes"][0]],
            "settings": {},
        })
    assert "connections" in str(exc.value)


def test_rejects_missing_settings_field():
    """Round 4 Phase 0 finding: n8n v2.15.0 explicitly rejects
    workflows without a settings field with a 400 error."""
    with pytest.raises(N8nWorkflowValidationError) as exc:
        N8nClient.validate_workflow_json({
            "nodes": [_minimal_valid_workflow()["nodes"][0]],
            "connections": {},
        })
    assert "settings" in str(exc.value)
    # Must mention v2.15.0 context so the Claude retry knows why
    assert "v2.15.0" in str(exc.value) or "n8n" in str(exc.value).lower()


# ─────────────────────────────────────────────────────────────────────
# Node-level structure rejections
# ─────────────────────────────────────────────────────────────────────


def test_rejects_empty_nodes_list():
    wf = _minimal_valid_workflow()
    wf["nodes"] = []
    with pytest.raises(N8nWorkflowValidationError) as exc:
        N8nClient.validate_workflow_json(wf)
    assert "non-empty" in str(exc.value).lower()


def test_rejects_node_without_id_field():
    wf = _minimal_valid_workflow()
    del wf["nodes"][0]["id"]
    with pytest.raises(N8nWorkflowValidationError) as exc:
        N8nClient.validate_workflow_json(wf)
    msg = str(exc.value)
    assert "nodes[0]" in msg
    assert "'id'" in msg


def test_rejects_node_without_name_field():
    wf = _minimal_valid_workflow()
    del wf["nodes"][0]["name"]
    with pytest.raises(N8nWorkflowValidationError) as exc:
        N8nClient.validate_workflow_json(wf)
    assert "'name'" in str(exc.value)


def test_rejects_node_without_type_field():
    wf = _minimal_valid_workflow()
    del wf["nodes"][0]["type"]
    with pytest.raises(N8nWorkflowValidationError) as exc:
        N8nClient.validate_workflow_json(wf)
    assert "'type'" in str(exc.value)


def test_rejects_node_without_parameters_field():
    wf = _minimal_valid_workflow()
    del wf["nodes"][0]["parameters"]
    with pytest.raises(N8nWorkflowValidationError) as exc:
        N8nClient.validate_workflow_json(wf)
    assert "'parameters'" in str(exc.value)


def test_rejects_node_type_with_whitespace():
    wf = _minimal_valid_workflow()
    wf["nodes"][0]["type"] = "n8n-nodes-base.web hook"
    with pytest.raises(N8nWorkflowValidationError) as exc:
        N8nClient.validate_workflow_json(wf)
    assert "whitespace" in str(exc.value).lower()


def test_rejects_node_type_empty_string():
    wf = _minimal_valid_workflow()
    wf["nodes"][0]["type"] = "   "
    with pytest.raises(N8nWorkflowValidationError) as exc:
        N8nClient.validate_workflow_json(wf)
    assert "non-empty string" in str(exc.value).lower()


# ─────────────────────────────────────────────────────────────────────
# Webhook trigger count + path rejections
# ─────────────────────────────────────────────────────────────────────


def test_rejects_workflow_with_no_webhook_trigger():
    """Schedule Trigger and Manual Trigger don't work for the test_run
    step — must be a webhook."""
    wf = {
        "nodes": [
            {
                "id": "n1",
                "name": "Schedule",
                "type": "n8n-nodes-base.scheduleTrigger",
                "parameters": {},
            }
        ],
        "connections": {},
        "settings": {},
    }
    with pytest.raises(N8nWorkflowValidationError) as exc:
        N8nClient.validate_workflow_json(wf)
    msg = str(exc.value)
    assert "webhook trigger" in msg.lower()
    # Must tell Claude WHAT to do so the retry works
    assert "Webhook" in msg or "webhook" in msg


def test_rejects_workflow_with_multiple_webhook_triggers():
    wf = {
        "nodes": [
            {
                "id": "a",
                "name": "W1",
                "type": "n8n-nodes-base.webhook",
                "parameters": {"path": "a"},
            },
            {
                "id": "b",
                "name": "W2",
                "type": "n8n-nodes-base.webhook",
                "parameters": {"path": "b"},
            },
        ],
        "connections": {},
        "settings": {},
    }
    with pytest.raises(N8nWorkflowValidationError) as exc:
        N8nClient.validate_workflow_json(wf)
    assert "exactly one" in str(exc.value).lower()


def test_rejects_respond_to_webhook_node_as_only_trigger():
    """respondToWebhook is a response node, NOT a trigger. A workflow
    with only a respond node has no trigger."""
    wf = {
        "nodes": [
            {
                "id": "a",
                "name": "Respond",
                "type": "n8n-nodes-base.respondToWebhook",
                "parameters": {},
            }
        ],
        "connections": {},
        "settings": {},
    }
    with pytest.raises(N8nWorkflowValidationError) as exc:
        N8nClient.validate_workflow_json(wf)
    assert "no webhook trigger" in str(exc.value).lower()


def test_rejects_webhook_without_parameters_path():
    wf = _minimal_valid_workflow()
    wf["nodes"][0]["parameters"] = {}
    with pytest.raises(N8nWorkflowValidationError) as exc:
        N8nClient.validate_workflow_json(wf)
    assert "parameters.path" in str(exc.value)


def test_rejects_webhook_with_empty_string_path():
    wf = _minimal_valid_workflow()
    wf["nodes"][0]["parameters"] = {"path": "   "}
    with pytest.raises(N8nWorkflowValidationError) as exc:
        N8nClient.validate_workflow_json(wf)
    assert "parameters.path" in str(exc.value)


def test_rejects_webhook_with_non_string_path():
    wf = _minimal_valid_workflow()
    wf["nodes"][0]["parameters"] = {"path": 42}
    with pytest.raises(N8nWorkflowValidationError) as exc:
        N8nClient.validate_workflow_json(wf)
    assert "parameters.path" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────
# Error-message field path guarantees (so Claude retries well)
# ─────────────────────────────────────────────────────────────────────


def test_error_messages_include_field_path_for_nodes():
    """Every nodes[N] rejection must include the index so Claude
    knows which node to fix."""
    wf = _minimal_valid_workflow()
    wf["nodes"].append(
        {
            "id": "n2",
            "name": "Broken",
            # missing type
            "parameters": {},
        }
    )
    with pytest.raises(N8nWorkflowValidationError) as exc:
        N8nClient.validate_workflow_json(wf)
    assert "nodes[1]" in str(exc.value)
