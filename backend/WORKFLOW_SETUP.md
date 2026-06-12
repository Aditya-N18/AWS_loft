# Render Workflows Setup

**Why you see `create task failed: not found`**

The `ghost-churn-workflows` entry in `render.yaml` uses `type: worker`. That is a **background worker**, not a **Render Workflow** service. Background workers do **not** register tasks with the Render Workflows API.

Render Blueprints **cannot** create Workflow services yet. You must create one in the Dashboard.

Inline fallback still runs email + cited.md, but judges won't see task runs in the Workflows UI until this is fixed.

---

## Fix (10 minutes)

### 1. Delete or ignore the background worker

In Render Dashboard, if you have a service named `ghost-churn-workflows` with type **Background Worker**, delete it or leave it — it won't register workflow tasks.

### 2. Create a Workflow service

1. Render Dashboard → **New** → **Workflow**
2. Connect the same Git repo
3. **Root directory:** `AWS_loft/backend` (or wherever `app/workflows.py` lives)
4. **Build command:** `pip install -r requirements.txt`
5. **Start command:** `python app/workflows.py`
6. **Name:** `ghost-churn-workflows` (or any name — note the slug)

Click **Deploy Workflow**. Wait for build to finish — this registers tasks.

### 3. Copy exact task slugs

1. Dashboard → your Workflow → **Tasks**
2. You should see:
   - `run_agent_evaluation`
   - `send_approval_email`
3. Click each task — copy the **slug** (format: `{workflow-slug}/run_agent_evaluation`)

Example: `ghost-churn-workflows/run_agent_evaluation`

### 4. Set env vars on the **web** service (`ghost-churn-backend`)

```
RENDER_API_KEY=rnd_...
RENDER_WORKFLOW_SLUG=<exact-workflow-slug-from-dashboard>
```

Or set full task identifiers (slug or `tsk-...` ID from task page):

```
RENDER_TASK_AGENT_EVAL=ghost-churn-workflows/run_agent_evaluation
RENDER_TASK_SEND_EMAIL=ghost-churn-workflows/send_approval_email
```

Redeploy the web service after changing env vars.

### 5. Set env vars on the **Workflow** service

Same SMTP / testmail / Langfuse vars as the web service:

```
BACKEND_INTERNAL_URL=https://ghost-churn-backend.onrender.com
TESTMAIL_TO_EMAIL=...
SMTP_HOST=smtp.zoho.com
SMTP_PORT=465
SMTP_USER=...
SMTP_PASSWORD=...
TESTMAIL_FROM_EMAIL=...
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
```

`BACKEND_INTERNAL_URL` must include `https://` (code auto-adds if missing).

### 6. Verify

**Dashboard:** Workflow → Tasks → `send_approval_email` → Start Task with test JSON:

```json
{
  "email_payload": {
    "account_id": "test",
    "account_name": "Test Co",
    "arr": 48000,
    "offer_draft": "Hello from Render Workflow",
    "subject": "Workflow test"
  }
}
```

**API:** After approve, logs should show:

```
[render-sdk] ghost-churn-workflows/send_approval_email queued → run_id=trn_...
```

NOT `not found`.

**Health check:**

```bash
curl -s https://ghost-churn-backend.onrender.com/health | jq '.task_slugs'
```

---

## Local dev (works without Dashboard)

**Terminal 1:**
```bash
cd AWS_loft/backend
RENDER_USE_LOCAL_DEV=true uv run render workflows dev --env-file .env -- python app/workflows.py
```

**Terminal 2:**
```bash
RENDER_USE_LOCAL_DEV=true uv run uvicorn app.main:app --port 8000
```

**Terminal 3:**
```bash
render workflows tasks list --local
```

---

## Troubleshooting

| Error | Fix |
|-------|-----|
| `not found` | Workflow service not created, or wrong slug in `RENDER_WORKFLOW_SLUG` |
| `404` on task-runs API | Same — tasks never registered |
| Task runs but state stuck at 3 | `BACKEND_INTERNAL_URL` wrong on workflow service |
| Email fails in workflow | Add SMTP env vars to **workflow** service, not just web |
