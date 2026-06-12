"""
Ghost Churn — FastAPI Backend
5-state workflow engine bridging ClickHouse webhooks → Render Workflows → OpenUI.

UI States (numeric):
  1  Monitor   — baseline, no active signal
  2  Warning   — usage drop detected, no web signal yet
  3  Risk      — ClickHouse threshold crossed, webhook received
  4  Approval  — run_agent_evaluation complete, offer_draft ready for human
  5  Saved     — human approved, send_approval_email dispatched

Local dev:
  RENDER_USE_LOCAL_DEV=true render workflows dev -- python app/workflows.py
  RENDER_USE_LOCAL_DEV=true uvicorn app.main:app --reload
"""

import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from render_sdk import RenderAsync

from app.workflows import (
    _build_offer_draft,
    _write_cited_md,
    _query_senso,
    _SENSO_MOCK,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ghost-churn")

# ---------------------------------------------------------------------------
# Render Workflow task identifiers  {workflow-service-slug}/{task-name}
# ---------------------------------------------------------------------------

WORKFLOW_SLUG = os.environ.get("RENDER_WORKFLOW_SLUG", "ghost-churn-workflows")
TASK_AGENT_EVAL = f"{WORKFLOW_SLUG}/run_agent_evaluation"
TASK_SEND_EMAIL = f"{WORKFLOW_SLUG}/send_approval_email"

USE_LOCAL_DEV = os.environ.get("RENDER_USE_LOCAL_DEV", "").lower() in ("1", "true", "yes")

# ---------------------------------------------------------------------------
# App + middleware
# ---------------------------------------------------------------------------

api = FastAPI(title="Ghost Churn Backend", version="3.0.0")

api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PUBLIC_DIR = Path(__file__).parent.parent / "public"
PUBLIC_DIR.mkdir(exist_ok=True)

api.mount("/public", StaticFiles(directory=str(PUBLIC_DIR)), name="public")

# ---------------------------------------------------------------------------
# In-memory state store
# state integer: 1=monitor 2=warning 3=risk 4=approval 5=saved
# ---------------------------------------------------------------------------

WORKFLOW_STATE: dict[str, dict] = {}

STATE_LABELS = {1: "monitor", 2: "warning", 3: "risk", 4: "approval", 5: "saved"}

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ChurnAlertPayload(BaseModel):
    account_id: str
    account_name: str
    arr: float
    usage_drop_pct: float
    identifiable_issues: List[str] = []
    anonymous_market_sentiment: str = ""
    source: Optional[str] = "clickhouse"

class ApprovePayload(BaseModel):
    account_id: str
    approved_by: Optional[str] = "human-operator"

class TaskResultPayload(BaseModel):
    account_id: str
    offer_draft: str
    ticket_summary: str
    senso_context: dict
    langfuse_trace_id: Optional[str] = ""
    churn_score: Optional[float] = None

# ---------------------------------------------------------------------------
# Render SDK helper
# ---------------------------------------------------------------------------

async def _start_render_task(task_identifier: str, input_data: dict) -> Optional[str]:
    """Triggers a Render Workflow task. Returns run_id or None on failure."""
    render_api_key = os.environ.get("RENDER_API_KEY", "")
    if not render_api_key and not USE_LOCAL_DEV:
        logger.warning(
            f"[render-sdk] RENDER_API_KEY not set + RENDER_USE_LOCAL_DEV=false — "
            f"skipping dispatch of {task_identifier}"
        )
        return None
    try:
        render = RenderAsync(token=render_api_key or None)
        task_run = await render.workflows.start_task(task_identifier, input_data)
        run_id = getattr(task_run, "id", None) or str(task_run)
        logger.info(f"[render-sdk] {task_identifier} queued → run_id={run_id}")
        return run_id
    except Exception as exc:
        logger.warning(f"[render-sdk] Failed to dispatch {task_identifier}: {exc}")
        return None

# ---------------------------------------------------------------------------
# Inline fallback — runs agent evaluation synchronously when Render SDK is
# not wired (local dev without `render workflows dev`)
# ---------------------------------------------------------------------------

def _inline_agent_evaluation(account_id: str, state: dict) -> None:
    """Synchronous fallback: mimics run_agent_evaluation inline."""
    senso_context = _query_senso(account_id)
    offer_draft = _build_offer_draft(
        account_id=account_id,
        account_name=state["account_name"],
        arr=state["arr"],
        usage_drop_pct=state["usage_drop_pct"],
        identifiable_issues=state["identifiable_issues"],
        anonymous_market_sentiment=state["anonymous_market_sentiment"],
        senso=senso_context,
    )
    issues_count = max(1, len(state["identifiable_issues"]))
    churn_score = round(state["arr"] * (state["usage_drop_pct"] / 100) * issues_count, 2)
    issues_md = "\n".join(f"- {i}" for i in state["identifiable_issues"]) or "- No identifiable issues logged"
    ticket_summary = (
        f"## Internal Ticket — Ghost Churn Alert\n"
        f"**Account:** {state['account_name']} (`{account_id}`)\n"
        f"**ARR:** ${state['arr']:,.0f} | **Churn Score:** {churn_score:,.0f}\n"
        f"**Usage Drop:** {state['usage_drop_pct']:.0f}% (7-day)\n"
        f"**Renewal in:** {senso_context.get('renewal_days','?')} days\n"
        f"**Key Contact:** {senso_context.get('contact_name','Unknown')} <{senso_context.get('contact_email','')}>\n\n"
        f"### Identifiable Issues (Zendesk/Stripe)\n{issues_md}\n\n"
        f"### Anonymous Market Sentiment (Reddit/X)\n> {state['anonymous_market_sentiment']}\n\n"
        f"### Senso Policy\n{senso_context.get('policy_ref','N/A')} — max discount: {senso_context.get('max_discount_pct',20)}%\n"
    )
    state["offer_draft"] = offer_draft
    state["ticket_summary"] = ticket_summary
    state["senso_context"] = senso_context
    state["churn_score"] = churn_score
    state["langfuse_trace_id"] = f"lf_trace_{abs(hash(account_id + state['detected_ts'])) % 0xFFFFFF:x}"
    state["ui_state"] = 4
    logger.info(f"[inline] Agent evaluation complete for {account_id} — state→4")

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@api.get("/health")
def health():
    return {
        "status": "ok",
        "service": "ghost-churn-backend",
        "version": "3.0.0",
        "render_local_dev": USE_LOCAL_DEV,
        "workflow_slug": WORKFLOW_SLUG,
    }


@api.post("/api/webhooks/churn-alert", status_code=202)
async def churn_alert(payload: ChurnAlertPayload):
    """
    ClickHouse threshold webhook.
    Sets UI state to 3 (Risk) immediately, queues run_agent_evaluation.
    Task POSTs result back to /api/internal/task-result → advances to state 4.
    Falls back to inline evaluation if Render SDK not configured.
    """
    account_id = payload.account_id
    detected_ts = datetime.now(timezone.utc).isoformat()

    WORKFLOW_STATE[account_id] = {
        "account_id": account_id,
        "account_name": payload.account_name,
        "arr": payload.arr,
        "usage_drop_pct": payload.usage_drop_pct,
        "identifiable_issues": payload.identifiable_issues,
        "anonymous_market_sentiment": payload.anonymous_market_sentiment,
        "source": payload.source,
        "ui_state": 3,
        "offer_draft": None,
        "ticket_summary": None,
        "senso_context": None,
        "langfuse_trace_id": None,
        "churn_score": None,
        "approved_by": None,
        "action_ts": None,
        "detected_ts": detected_ts,
        "render_task_run_id": None,
    }

    logger.info(
        f"[{account_id}] churn-alert → state=3 (Risk) "
        f"ARR=${payload.arr:,.0f} drop={payload.usage_drop_pct}% "
        f"issues={len(payload.identifiable_issues)}"
    )

    run_id = await _start_render_task(
        TASK_AGENT_EVAL,
        {
            "account_id": account_id,
            "context": {
                "account_name": payload.account_name,
                "arr": payload.arr,
                "usage_drop_pct": payload.usage_drop_pct,
                "identifiable_issues": payload.identifiable_issues,
                "anonymous_market_sentiment": payload.anonymous_market_sentiment,
                "detected_ts": detected_ts,
            },
        },
    )

    if run_id:
        WORKFLOW_STATE[account_id]["render_task_run_id"] = run_id
        message = f"run_agent_evaluation queued — run_id={run_id}"
    else:
        _inline_agent_evaluation(account_id, WORKFLOW_STATE[account_id])
        message = "Render SDK not configured — agent evaluation ran inline → state=4"

    return {
        "status": "accepted",
        "account_id": account_id,
        "ui_state": WORKFLOW_STATE[account_id]["ui_state"],
        "ui_state_label": STATE_LABELS[WORKFLOW_STATE[account_id]["ui_state"]],
        "detected_ts": detected_ts,
        "render_task_run_id": run_id,
        "message": message,
    }


@api.post("/api/internal/task-result")
def task_result(payload: TaskResultPayload):
    """
    Internal endpoint called by the Render Workflow task (run_agent_evaluation)
    to push its result back and advance UI state from 3 → 4.
    Not exposed to the public frontend.
    """
    account_id = payload.account_id

    if account_id not in WORKFLOW_STATE:
        raise HTTPException(status_code=404, detail=f"No active workflow for {account_id}")

    state = WORKFLOW_STATE[account_id]
    state["offer_draft"] = payload.offer_draft
    state["ticket_summary"] = payload.ticket_summary
    state["senso_context"] = payload.senso_context
    state["langfuse_trace_id"] = payload.langfuse_trace_id or ""
    state["churn_score"] = payload.churn_score
    state["ui_state"] = 4

    logger.info(f"[{account_id}] task-result received → state=4 (Approval)")
    return {"status": "ok", "account_id": account_id, "ui_state": 4}


@api.get("/api/workflow/status/{account_id}")
def workflow_status(account_id: str):
    """
    Polling endpoint for OpenUI frontend.
    Returns numeric ui_state (1–5) + full context including offer_draft.
    """
    if account_id not in WORKFLOW_STATE:
        return {
            "account_id": account_id,
            "ui_state": 1,
            "ui_state_label": "monitor",
            "message": "No active workflow for this account.",
        }

    s = WORKFLOW_STATE[account_id]
    ui_state = s["ui_state"]
    return {
        "account_id": account_id,
        "ui_state": ui_state,
        "ui_state_label": STATE_LABELS.get(ui_state, "unknown"),
        "account_name": s.get("account_name"),
        "arr": s.get("arr"),
        "usage_drop_pct": s.get("usage_drop_pct"),
        "identifiable_issues": s.get("identifiable_issues"),
        "anonymous_market_sentiment": s.get("anonymous_market_sentiment"),
        "churn_score": s.get("churn_score"),
        "offer_draft": s.get("offer_draft"),
        "ticket_summary": s.get("ticket_summary"),
        "senso_context": s.get("senso_context"),
        "langfuse_trace_id": s.get("langfuse_trace_id"),
        "detected_ts": s.get("detected_ts"),
        "action_ts": s.get("action_ts"),
        "approved_by": s.get("approved_by"),
        "render_task_run_id": s.get("render_task_run_id"),
        "report_url": f"/public/{account_id}-cited.md" if ui_state == 5 else None,
    }


@api.post("/api/workflow/approve")
async def approve_workflow(payload: ApprovePayload):
    """
    Human approves the save offer (state 4 → 5).
    Queues send_approval_email Render Workflow task.
    Falls back to inline cited.md write if SDK not configured.
    """
    account_id = payload.account_id

    if account_id not in WORKFLOW_STATE:
        raise HTTPException(status_code=404, detail=f"No active workflow for account_id={account_id}")

    s = WORKFLOW_STATE[account_id]

    if s["ui_state"] == 5:
        return {
            "status": "already_saved",
            "account_id": account_id,
            "report_url": f"/public/{account_id}-cited.md",
        }

    if s["ui_state"] != 4:
        raise HTTPException(
            status_code=409,
            detail=f"ui_state={s['ui_state']} ({STATE_LABELS.get(s['ui_state'])}) — must be 4 (approval) to approve.",
        )

    action_ts = datetime.now(timezone.utc).isoformat()
    s["ui_state"] = 5
    s["approved_by"] = payload.approved_by
    s["action_ts"] = action_ts

    senso_context = s.get("senso_context") or _SENSO_MOCK
    offer_draft = s.get("offer_draft") or _build_offer_draft(
        account_id=account_id,
        account_name=s["account_name"],
        arr=s["arr"],
        usage_drop_pct=s["usage_drop_pct"],
        identifiable_issues=s["identifiable_issues"],
        anonymous_market_sentiment=s["anonymous_market_sentiment"],
        senso=senso_context,
    )
    s["offer_draft"] = offer_draft

    email_payload = {
        "account_id": account_id,
        "account_name": s["account_name"],
        "arr": s["arr"],
        "usage_drop_pct": s["usage_drop_pct"],
        "identifiable_issues": s["identifiable_issues"],
        "anonymous_market_sentiment": s["anonymous_market_sentiment"],
        "offer_draft": offer_draft,
        "ticket_summary": s.get("ticket_summary", ""),
        "senso_context": senso_context,
        "approved_by": payload.approved_by,
        "detected_ts": s["detected_ts"],
        "action_ts": action_ts,
        "langfuse_trace_id": s.get("langfuse_trace_id", ""),
    }

    run_id = await _start_render_task(TASK_SEND_EMAIL, {"email_payload": email_payload})

    if run_id:
        s["render_task_run_id"] = run_id
        logger.info(f"[{account_id}] send_approval_email queued → run_id={run_id} state=5")
        report_url = f"/public/{account_id}-cited.md"
        email_note = f"Render task dispatched — email + cited.md via run_id={run_id}"
    else:
        report_path = _write_cited_md(**email_payload)
        logger.info(f"[{account_id}] cited.md written inline — state=5")
        report_url = f"/public/{account_id}-cited.md"
        testmail_ns = os.environ.get("TESTMAIL_NAMESPACE", "ghostchurn")
        email_note = (
            f"Render SDK not configured — cited.md written inline. "
            f"Would send to: {testmail_ns}.{account_id}@inbox.testmail.app"
        )

    return {
        "status": "saved",
        "account_id": account_id,
        "account_name": s["account_name"],
        "ui_state": 5,
        "ui_state_label": "saved",
        "approved_by": payload.approved_by,
        "action_ts": action_ts,
        "render_task_run_id": run_id,
        "report_url": report_url,
        "email_note": email_note,
        "langfuse_trace_id": s.get("langfuse_trace_id", ""),
    }


@api.get("/api/workflow/all")
def list_all_workflows():
    """Returns all active workflow states. Used by OpenUI health monitor (state 1)."""
    return {
        "accounts": [
            {
                "account_id": k,
                "account_name": v.get("account_name"),
                "arr": v.get("arr"),
                "ui_state": v.get("ui_state"),
                "ui_state_label": STATE_LABELS.get(v.get("ui_state", 1), "unknown"),
                "usage_drop_pct": v.get("usage_drop_pct"),
                "churn_score": v.get("churn_score"),
                "detected_ts": v.get("detected_ts"),
                "render_task_run_id": v.get("render_task_run_id"),
            }
            for k, v in WORKFLOW_STATE.items()
        ]
    }


# uvicorn app.main:app
app = api
