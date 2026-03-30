from __future__ import annotations

import asyncio
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("arlo.tools.n8n")


class N8nError(Exception):
    """Base error for n8n operations."""


class N8nTimeoutError(N8nError):
    """Raised when an n8n execution exceeds the timeout."""


class N8nAPIError(N8nError):
    """Raised when the n8n API returns an error."""

    def __init__(self, message: str, status_code: int | None = None, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class N8nClient:
    """Async client for the n8n REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
    ):
        self._base_url = (base_url or settings.n8n_base_url).rstrip("/")
        self._api_key = api_key or settings.n8n_api_key
        self._headers = {
            "X-N8N-API-KEY": self._api_key,
            "Content-Type": "application/json",
        }

    async def _request(
        self, method: str, path: str, json: dict | None = None
    ) -> dict:
        """Make an HTTP request to the n8n API."""
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                method, url, headers=self._headers, json=json
            )

        if response.status_code >= 400:
            raise N8nAPIError(
                f"n8n API error: {response.status_code} {response.text[:500]}",
                status_code=response.status_code,
                body=response.text,
            )

        return response.json()

    async def create_workflow(self, workflow_json: dict) -> dict:
        """Create a new workflow in n8n.

        Returns the created workflow dict including its 'id'.
        """
        result = await self._request("POST", "/api/v1/workflows", json=workflow_json)
        logger.info("Created n8n workflow: %s", result.get("id"))
        return result

    async def activate_workflow(self, workflow_id: str) -> dict:
        """Activate a workflow so it responds to triggers."""
        result = await self._request(
            "PATCH", f"/api/v1/workflows/{workflow_id}", json={"active": True}
        )
        logger.info("Activated n8n workflow: %s", workflow_id)
        return result

    async def deactivate_workflow(self, workflow_id: str) -> dict:
        """Deactivate a workflow."""
        return await self._request(
            "PATCH", f"/api/v1/workflows/{workflow_id}", json={"active": False}
        )

    async def execute_workflow(
        self, workflow_id: str, data: dict | None = None
    ) -> dict:
        """Trigger a workflow execution.

        Returns execution metadata including 'id'.
        """
        payload = {}
        if data:
            payload["data"] = data
        result = await self._request(
            "POST", f"/api/v1/workflows/{workflow_id}/run", json=payload
        )
        logger.info("Triggered n8n execution for workflow %s", workflow_id)
        return result

    async def get_execution(self, execution_id: str) -> dict:
        """Get the status and data of an execution."""
        return await self._request("GET", f"/api/v1/executions/{execution_id}")

    async def poll_execution(
        self,
        execution_id: str,
        timeout: int | None = None,
        interval: int | None = None,
    ) -> dict:
        """Poll an execution until it completes or times out.

        Returns the final execution dict.
        Raises N8nTimeoutError if the timeout is exceeded.
        """
        if timeout is None:
            timeout = settings.n8n_execution_timeout_seconds
        if interval is None:
            interval = settings.n8n_poll_interval_seconds

        elapsed = 0
        while elapsed < timeout:
            execution = await self.get_execution(execution_id)
            status = execution.get("status", "unknown")

            if status in ("success", "error", "crashed"):
                logger.info(
                    "n8n execution %s finished with status: %s",
                    execution_id, status,
                )
                return execution

            await asyncio.sleep(interval)
            elapsed += interval

        raise N8nTimeoutError(
            f"n8n execution {execution_id} timed out after {timeout}s"
        )

    async def list_workflows(self) -> list[dict]:
        """List all workflows."""
        result = await self._request("GET", "/api/v1/workflows")
        return result.get("data", [])

    async def delete_workflow(self, workflow_id: str) -> None:
        """Delete a workflow."""
        await self._request("DELETE", f"/api/v1/workflows/{workflow_id}")
        logger.info("Deleted n8n workflow: %s", workflow_id)
