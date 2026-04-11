# n8n v2.15.0 REST API — Phase 0 Empirical Findings

**Probe date:** 2026-04-11
**n8n version:** 2.15.0
**Auth header:** `X-N8N-API-KEY` (confirmed working — "Authorization: Bearer" not tested because the legacy header still works)

This document captures the ground truth of the n8n REST API as it
actually behaves on the target instance, NOT what the published docs
or source code suggest. Every section here comes from a real curl
against the running container, with the response pasted in.

The Round 4 rewrite of `app/tools/n8n.py` and `app/jobs/n8n.py` is
grounded in these findings. Where my pre-probe guesses were wrong,
the diffs in those files reference back to this doc.

---

## 1. List workflows

```
GET /api/v1/workflows
```

**Response (200):**

```json
{"data": [], "nextCursor": null}
```

**Notes:**
- `/api/v1/` prefix still works in v2.15.0 — no move to `/api/v2/`
- Pagination uses `nextCursor` (string or null), not a limit/offset pattern
- Response shape: `{data: [...], nextCursor: ...}`, so `.get("data", [])` works

---

## 2. Create workflow (empty) — validation contract

```
POST /api/v1/workflows
Body: {"name":"arlo-probe-empty","nodes":[],"connections":{}}
```

**Response (400):**

```json
{"message": "request/body must have required property 'settings'"}
```

**Key finding:** n8n v2 **requires** a `settings` field on the create payload.
An empty `{}` works (verified in #3). The Round 4 N8nClient must inject
an empty settings object if the caller doesn't provide one, OR the
builder prompt must always include it. We do BOTH for defense in depth.

---

## 3. Create workflow (real, with webhook trigger)

```
POST /api/v1/workflows
Body: {
  "name": "arlo-probe-real",
  "nodes": [{
    "parameters": {"path":"arlo-probe","httpMethod":"POST","options":{}},
    "id": "node-1",
    "name": "Webhook",
    "type": "n8n-nodes-base.webhook",
    "typeVersion": 1,
    "position": [0,0]
  }],
  "connections": {},
  "settings": {}
}
```

**Response (200) — full workflow dict returned:**

```json
{
  "name": "arlo-probe-real",
  "nodes": [{
    "parameters": {"path":"arlo-probe","httpMethod":"POST","options":{}},
    "id": "node-1",
    "name": "Webhook",
    "type": "n8n-nodes-base.webhook",
    "typeVersion": 1,
    "position": [0,0],
    "webhookId": "7a48637f-3790-466f-89d8-725c46698815"
  }],
  "connections": {},
  "settings": {
    "callerPolicy": "workflowsFromSameOwner",
    "availableInMCP": false
  },
  "active": false,
  "versionId": "e68f4715-45c3-4e32-b1b4-28f39bdcdb17",
  "id": "cfwWwcRoLtI253lD",
  "description": null,
  "staticData": null,
  "meta": null,
  "pinData": null,
  "activeVersionId": null,
  "updatedAt": "2026-04-11T03:33:42.355Z",
  "createdAt": "2026-04-11T03:33:42.355Z",
  "isArchived": false,
  "versionCounter": 1,
  "triggerCount": 0
}
```

**Key findings:**
- **Workflow IDs are short alphanumeric slugs**, NOT UUIDs. Example: `cfwWwcRoLtI253lD`. Treat them as opaque strings.
- Sent `settings: {}` and n8n auto-populated it with `callerPolicy` and `availableInMCP` on the way out. Clients should trust the returned settings, not re-send their own.
- The webhook node gets a server-generated `webhookId` (UUID) that is **different from** the node's `parameters.path`. For external triggering we care about the path, not the webhookId.
- Initial `active: false` — activation is a separate call.

---

## 4. Activate via v1-style PATCH (deprecated)

```
PATCH /api/v1/workflows/{id}
Body: {"active": true}
```

**Response (405):**

```json
{"message": "PATCH method not allowed"}
```

**Key finding:** The v0.x/v1 PATCH-with-body activation pattern is **explicitly rejected** in v2.15.0 with a 405 Method Not Allowed. Confirms the Round 4 fix was necessary.

---

## 5. Activate via v2-style POST (the correct path)

```
POST /api/v1/workflows/{id}/activate
```

(no body required)

**Response (200) — full workflow dict with `active: true` and a new `activeVersion` block:**

```json
{
  "id": "cfwWwcRoLtI253lD",
  "name": "arlo-probe-real",
  "active": true,
  "nodes": [...],
  "connections": {},
  "settings": {...},
  "versionId": "...",
  "activeVersionId": "e68f4715-45c3-4e32-b1b4-28f39bdcdb17",
  "triggerCount": 1,
  "activeVersion": {
    "workflowId": "cfwWwcRoLtI253lD",
    "nodes": [...],
    "connections": {},
    "authors": "Varun Saraf",
    "workflowPublishHistory": [{
      "event": "activated",
      "userId": "...",
      "createdAt": "2026-04-11T03:34:48.826Z"
    }]
  }
}
```

**Key finding:** Activation returns the full workflow with:
- `active: true`
- `triggerCount: 1` (was 0 before activation)
- A new `activeVersion` object with publication history

My Round 4 N8nClient.activate_workflow just returns the response dict as-is,
so callers can inspect `active`, `triggerCount`, and `activeVersion` if
they want. The side hustle executor only uses the fact of the 200.

**Deactivate is assumed symmetric** (`POST /api/v1/workflows/{id}/deactivate`) — NOT explicitly probed but very likely correct.

---

## 6. Webhook trigger — the REAL external-execution path

```
POST http://localhost:5678/webhook/arlo-probe
Body: {"hello": "world"}
```

**Response (200):**

```json
{"message": "Workflow was started"}
```

**Key findings:**
- **Webhook URL format confirmed:** `{base}/webhook/{path}` where `path` is the webhook node's `parameters.path`. The `webhookId` from the node is NOT in the URL.
- The default webhook response mode is `"onReceived"` — n8n returns this generic "Workflow was started" message **immediately** when the webhook queues the execution, BEFORE the workflow actually runs.
- This means `trigger_webhook` alone **cannot tell you whether the workflow succeeded**. It only tells you the webhook was accepted.
- **To get the actual execution result**, the test step must:
  1. Trigger the webhook
  2. Query `GET /api/v1/executions?workflowId={id}&limit=1` to find the newly-created execution
  3. Poll that execution to terminal status via `GET /api/v1/executions/{exec_id}`

This is a material behavior change from what Round 4's initial code assumed (which was: treat a 2xx webhook response as success). The fix is a small addition to `execute_n8n_job`'s execute phase.

---

## 7. List executions

```
GET /api/v1/executions?limit=5
```

**Response (200):**

```json
{
  "data": [{
    "id": "1",
    "finished": true,
    "mode": "webhook",
    "retryOf": null,
    "retrySuccessId": null,
    "status": "success",
    "startedAt": "2026-04-11T03:34:58.162Z",
    "stoppedAt": "2026-04-11T03:34:58.185Z",
    "workflowId": "cfwWwcRoLtI253lD",
    "waitTill": null
  }],
  "nextCursor": null
}
```

**Key findings:**
- Same `{data: [...], nextCursor: ...}` pagination as workflows list
- Each execution has **both `status` and `finished` fields**. v2.15.0 populates:
  - `status: "success" | "error" | ...` (the primary signal)
  - `finished: true | false` (redundant but useful as a fallback)
- `mode: "webhook"` indicates the execution was triggered by a webhook
- `workflowId` is the owning workflow's id (matches what we created)
- **Execution IDs are integer-strings** (`"1"`, `"2"`, ...), not UUIDs. This matters for path construction — see #8.
- `?limit=5` works. Not tested whether `?workflowId=X` as a filter works, but the response already includes `workflowId` on each row so client-side filtering is a fallback.
- TODO: empirically verify the `?workflowId=X` query param before relying on it in production code.

---

## 8. Get execution by ID

**First attempt (wrong):** `GET /api/v1/executions/cfwWwcRoLtI253lD` (using workflow ID by mistake)

**Response (400):**

```json
{"message": "request/params/id must be number"}
```

**Second attempt (correct):** `GET /api/v1/executions/1`

**Response (200):**

```json
{
  "id": "1",
  "finished": true,
  "mode": "webhook",
  "retryOf": null,
  "retrySuccessId": null,
  "status": "success",
  "createdAt": "2026-04-11T03:34:58.155Z",
  "startedAt": "2026-04-11T03:34:58.162Z",
  "stoppedAt": "2026-04-11T03:34:58.185Z",
  "deletedAt": null,
  "workflowId": "cfwWwcRoLtI253lD",
  "waitTill": null,
  "storedAt": "db"
}
```

**Key findings:**
- **Execution IDs must be integer-strings** in the path — the API rejects non-numeric IDs with `request/params/id must be number`. (Note: `"1"` works as a string in the URL, but it must BE a number, not a UUID or slug.)
- Single-execution response has the same fields as list-executions, plus `createdAt`, `deletedAt`, `storedAt`
- **NO execution data/output is included by default** in this response. The `data` field (which holds the workflow node outputs) is only returned with `?includeData=true`. For the test step we don't need data — the status field is sufficient.

---

## 9. Delete workflow

```
DELETE /api/v1/workflows/{id}
```

**Response (200):** Returns the full deleted workflow dict including a `shared` array with project ownership info:

```json
{
  "id": "cfwWwcRoLtI253lD",
  "name": "arlo-probe-real",
  "active": true,
  ...,
  "shared": [{
    "role": "workflow:owner",
    "workflowId": "cfwWwcRoLtI253lD",
    "projectId": "Hf6FiC4nsRMi5tD9",
    "project": {
      "id": "Hf6FiC4nsRMi5tD9",
      "name": "Varun Saraf <varunsaraf1724@gmail.com>",
      "type": "personal",
      ...
    }
  }]
}
```

**Key findings:**
- `DELETE` returns **200 with the deleted workflow body**, not 204 No Content. My Round 4 code passes `expect_json=False` for delete which would swallow the body — update to `expect_json=True` and ignore it.
- A successful DELETE on an active workflow works fine (doesn't require prior deactivation).

---

## Summary — what Round 4 code needs to change

| Finding | File | Change |
|---|---|---|
| Create requires `settings` field | `app/tools/n8n.py::create_workflow` | Inject `settings: {}` if the caller didn't provide it |
| Webhook trigger returns immediately before execution runs | `app/jobs/n8n.py::execute_n8n_job` | After `trigger_webhook`, query `list_executions(workflow_id=X, limit=1)` and poll the latest execution to terminal status |
| Execution IDs are integer-strings | `tests/test_n8n_e2e.py` | Type signature is already `str`, no code change. But docs / comments need to mention it. |
| DELETE returns 200 with body | `app/tools/n8n.py::delete_workflow` | Change `expect_json=False` to `expect_json=True` (the body is thrown away anyway) |
| Builder prompt must produce `settings` field | `app/workflows/templates.py::build_n8n_workflow` | Add explicit requirement "workflow.json must include a `settings` object (empty `{}` is fine)" to the prompt |

## Things confirmed unchanged

- `/api/v1/` prefix
- `X-N8N-API-KEY` header auth
- `POST /api/v1/workflows/{id}/activate` path
- `{base}/webhook/{path}` webhook URL format
- Pagination shape `{data: [...], nextCursor: ...}`
- Execution response has both `status` and `finished` fields (normalization already handles this)

## Open questions deferred to future rounds

1. **`?workflowId=X` query filter on `/executions`** — not probed. If the client-side filter in Round 4's code doesn't work, we'll need to probe this and adjust. Falls back to listing all executions and filtering in Python (slower but always works).
2. **Deactivation endpoint** — not explicitly probed, assumed symmetric to `/activate`. Probe in a future round if we need deactivation in any real workflow.
3. **Execution `data` field shape** via `?includeData=true` — not needed for the test step, but useful if we ever want to surface node-by-node execution output to the user.
4. **Webhook response modes other than `onReceived`** — e.g. setting `responseMode: "lastNode"` in the webhook node parameters would make `trigger_webhook` return the actual last-node output synchronously. Would simplify the executor flow. Probe if we want to skip the list-executions → poll dance.
