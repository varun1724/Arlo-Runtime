"""End-to-end integration test for the Round 4 N8nClient rewrite.

Runs against the LIVE n8n container. Gated behind the env var
``ARLO_N8N_INTEGRATION_TESTS=1`` so the normal unit test run in the
docker test container doesn't trigger it. Enable with:

.. code-block:: bash

    docker compose exec -T api env ARLO_N8N_INTEGRATION_TESTS=1 \\
        pytest tests/test_n8n_e2e.py -v

This is the headline proof that the rewrite actually works against
n8n 2.15.0 running in the docker-compose stack. It creates a minimal
hand-crafted webhook workflow, activates it, POSTs to the webhook,
asserts the response, and cleans up afterwards.

The hand-crafted workflow is intentionally minimal so this test is
about the integration, NOT about the builder's output quality.
Builder quality is a Round 1 concern.
"""

from __future__ import annotations

import os
import uuid

import pytest

from app.tools.n8n import N8nAPIError, N8nClient

# Skip the entire file unless the env var is set. CI / default pytest
# runs skip these without touching the n8n container.
pytestmark = pytest.mark.skipif(
    os.environ.get("ARLO_N8N_INTEGRATION_TESTS") != "1",
    reason="ARLO_N8N_INTEGRATION_TESTS=1 to run n8n integration tests",
)


def _minimal_webhook_workflow(path: str) -> dict:
    """Build a minimal n8n workflow with a Webhook trigger followed by
    a Set node that echoes the incoming body back as the response.

    Uses stable node IDs so debugging is easier if this test fails.
    """
    return {
        "name": f"arlo-test-{path}",
        "nodes": [
            {
                "id": "webhook-node",
                "name": "Webhook",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 1,
                "position": [0, 0],
                "parameters": {
                    "httpMethod": "POST",
                    "path": path,
                    "responseMode": "onReceived",
                    "options": {},
                },
            },
            {
                "id": "set-node",
                "name": "Echo",
                "type": "n8n-nodes-base.set",
                "typeVersion": 1,
                "position": [250, 0],
                "parameters": {
                    "values": {
                        "string": [
                            {"name": "echo", "value": "hello-from-arlo"},
                        ],
                    },
                },
            },
        ],
        "connections": {
            "Webhook": {
                "main": [[{"node": "Echo", "type": "main", "index": 0}]]
            }
        },
        "settings": {},
    }


@pytest.mark.asyncio
async def test_create_activate_trigger_delete_minimal_webhook_workflow():
    """Headline Round 4 proof: every method of N8nClient works against
    n8n 2.15.0 using a minimal real workflow.

    Steps:
    1. Create the workflow (POST /api/v1/workflows)
    2. Assert the returned id is a string
    3. Extract the webhook URL via extract_webhook_url_from_workflow
    4. Activate the workflow (POST /api/v1/workflows/{id}/activate)
    5. Trigger the webhook (POST {base}/webhook/{path})
    6. Assert the response looks like a success
    7. Deactivate (POST /api/v1/workflows/{id}/deactivate)
    8. Delete the workflow (DELETE /api/v1/workflows/{id})

    Cleanup happens in a try/finally so a leaked workflow can be found
    via its ``arlo-test-*`` name prefix even if something fails.
    """
    client = N8nClient()
    path = f"arlo-test-{uuid.uuid4().hex[:8]}"
    workflow_json = _minimal_webhook_workflow(path)

    created_id: str | None = None
    try:
        # Step 1: create
        created = await client.create_workflow(workflow_json)
        assert isinstance(created, dict)
        created_id = created.get("id")
        assert created_id, f"create_workflow returned no id: {created}"

        # Step 2: extract webhook URL
        webhook_url = N8nClient.extract_webhook_url_from_workflow(workflow_json)
        assert webhook_url, "failed to extract webhook URL from our own workflow"
        assert path in webhook_url

        # Step 3: activate
        await client.activate_workflow(str(created_id))

        # Step 4: trigger the webhook
        response = await client.trigger_webhook(webhook_url, payload={"test": "data"})
        assert isinstance(response, dict)
        status_code = response.get("_status_code")
        assert status_code and 200 <= status_code < 300, (
            f"webhook trigger returned non-2xx: {status_code} — {response}"
        )

        # Step 5: deactivate
        await client.deactivate_workflow(str(created_id))

    finally:
        # Step 6: cleanup — always delete the test workflow if created
        if created_id:
            try:
                await client.delete_workflow(str(created_id))
            except N8nAPIError:
                # Best effort. If it's stuck, the arlo-test-* prefix
                # makes it easy to find and manually clean up later.
                pass


@pytest.mark.asyncio
async def test_list_workflows_returns_a_list():
    """Sanity check: list_workflows always returns a list (possibly
    empty) against a real n8n instance."""
    client = N8nClient()
    result = await client.list_workflows()
    assert isinstance(result, list)
