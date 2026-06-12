"""
Ghost Churn — FastAPI Backend
5-state workflow engine bridging ClickHouse webhooks → Render Workflows → OpenUI.

Person 3 approve webhook: POST /workflow/save-customer

Local dev (uv):
  uv sync
  uv run uvicorn app.main:app --reload --port 8000
  RENDER_USE_LOCAL_DEV=true uv run render workflows dev --env-file .env -- python app/workflows.py
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
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from render_sdk import RenderAsync

from app.workflows import (
    _build_offer_draft,
    _build_ticket_summary,
    _default_policy,
    _execute_send_approval,
    _slugify_account_id,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ghost-churn")

WORKFLOW_SLUG = os.environ.get("RENDER_WORKFLOW_SLUG", "ghost-churn-workflows")
TASK_AGENT_EVAL = f"{WORKFLOW_SLUG}/run_agent_evaluation"
TASK_SEND_EMAIL = f"{WORKFLOW_SLUG}/send_approval_email"

USE_LOCAL_DEV = os.environ.get("RENDER_USE_LOCAL_DEV", "").lower() in ("1", "true", "yes")

api = FastAPI(title="Ghost Churn Backend", version="3.1.0")

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

WORKFLOW_STATE: dict[str, dict] = {}

STATE_LABELS = {1: "monitor", 2: "warning", 3: "risk", 4: "approval", 5: "saved"}


class UsageWarningPayload(BaseModel):
    account_id: str
    account_name: str
    usage_drop_pct: float
    arr: float


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


class OfferPayload(BaseModel):
    accountName: str
    arr: float
    contactName: str
    contactEmail: str
    subject: str
    emailBody: str
    discountPct: float
    featureUnlock: str
    renewalDays: int
    sensoPolicy: str = ""
    sensoMaxDiscount: float = 20
    agentReasoning: List[str] = Field(default_factory=list)


class SaveCustomerPayload(BaseModel):
    action: str
    approvedAt: str
    approvedBy: str = "demo-operator"
    offer: OfferPayload


class TaskResultPayload(BaseModel):
    account_id: str
    offer_draft: str
    ticket_summary: str
    policy: dict = Field(default_factory=dict)
    langfuse_trace_id: Optional[str] = ""
    churn_score: Optional[float] = None


async def _start_render_task(task_identifier: str, input_data: dict) -> Optional[str]:
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


def _inline_agent_evaluation(account_id: str, state: dict) -> None:
    policy = _default_policy()
    offer_draft = _build_offer_draft(
        account_id=account_id,
        account_name=state["account_name"],
        arr=state["arr"],
        usage_drop_pct=state["usage_drop_pct"],
        identifiable_issues=state["identifiable_issues"],
        anonymous_market_sentiment=state["anonymous_market_sentiment"],
        policy=policy,
    )
    issues_count = max(1, len(state["identifiable_issues"]))
    churn_score = round(state["arr"] * (state["usage_drop_pct"] / 100) * issues_count, 2)
    ticket_summary = _build_ticket_summary(
        account_id=account_id,
        account_name=state["account_name"],
        arr=state["arr"],
        usage_drop_pct=state["usage_drop_pct"],
        identifiable_issues=state["identifiable_issues"],
        anonymous_market_sentiment=state["anonymous_market_sentiment"],
        policy=policy,
        churn_score=churn_score,
    )
    state["offer_draft"] = offer_draft
    state["ticket_summary"] = ticket_summary
    state["policy"] = policy
    state["churn_score"] = churn_score
    state["langfuse_trace_id"] = f"lf_trace_{abs(hash(account_id + state['detected_ts'])) % 0xFFFFFF:x}"
    state["ui_state"] = 4
    logger.info(f"[inline] Agent evaluation complete for {account_id} — state→4")


def _offer_to_email_payload(payload: SaveCustomerPayload) -> dict:
    offer = payload.offer
    account_id = _slugify_account_id(offer.accountName)
    policy = {
        "max_discount_pct": offer.sensoMaxDiscount,
        "contact_name": offer.contactName,
        "contact_email": offer.contactEmail,
        "renewal_days": offer.renewalDays,
        "use_case": offer.featureUnlock,
        "policy_ref": offer.sensoPolicy or "Retention Policy",
    }
    return {
        "account_id": account_id,
        "account_name": offer.accountName,
        "arr": offer.arr,
        "usage_drop_pct": 0,
        "identifiable_issues": [],
        "anonymous_market_sentiment": "",
        "offer_draft": offer.emailBody,
        "subject": offer.subject,
        "ticket_summary": _build_ticket_summary(
            account_id=account_id,
            account_name=offer.accountName,
            arr=offer.arr,
            usage_drop_pct=0,
            identifiable_issues=[],
            anonymous_market_sentiment="",
            policy=policy,
            churn_score=offer.arr,
            agent_reasoning=offer.agentReasoning,
        ),
        "policy": policy,
        "approved_by": payload.approvedBy,
        "detected_ts": payload.approvedAt,
        "action_ts": payload.approvedAt,
        "discount_pct": offer.discountPct,
        "feature_unlock": offer.featureUnlock,
        "agent_reasoning": offer.agentReasoning,
    }


def _empty_workflow_state(account_id: str, account_name: str, arr: float) -> dict:
    return {
        "account_id": account_id,
        "account_name": account_name,
        "arr": arr,
        "usage_drop_pct": 0,
        "identifiable_issues": [],
        "anonymous_market_sentiment": "",
        "source": None,
        "offer_draft": None,
        "ticket_summary": None,
        "policy": None,
        "langfuse_trace_id": None,
        "churn_score": None,
        "approved_by": None,
        "action_ts": None,
        "detected_ts": None,
        "render_task_run_id": None,
    }


@api.get("/health")
def health():
    return {
        "status": "ok",
        "service": "ghost-churn-backend",
        "version": "3.1.0",
        "render_local_dev": USE_LOCAL_DEV,
        "workflow_slug": WORKFLOW_SLUG,
        "endpoints": {
            "approve": "/workflow/save-customer",
            "usage_warning": "/api/webhooks/usage-warning",
            "churn_alert": "/api/webhooks/churn-alert",
            "status": "/api/workflow/status/{account_id}",
        },
    }


@api.post("/workflow/save-customer", status_code=202)
async def save_customer(payload: SaveCustomerPayload):
    """
    Person 3 Approve & Send webhook.
    Queues send_approval_email Render Workflow; falls back to inline execution.
    """
    if payload.action != "approve":
        return JSONResponse(
            status_code=422,
            content={"ok": False, "reason": "Only action=approve is supported for demo"},
        )

    if not payload.offer.emailBody.strip():
        return JSONResponse(
            status_code=422,
            content={"ok": False, "reason": "offer.emailBody is required"},
        )

    email_payload = _offer_to_email_payload(payload)
    account_id = email_payload["account_id"]

    logger.info(
        f"[save-customer] approve from {payload.approvedBy} "
        f"account={email_payload['account_name']} id={account_id}"
    )

    run_id = await _start_render_task(TASK_SEND_EMAIL, {"email_payload": email_payload})

    if run_id:
        WORKFLOW_STATE[account_id] = {
            **email_payload,
            "ui_state": 5,
            "render_task_run_id": run_id,
        }
        return {
            "ok": True,
            "workflow_run_id": run_id,
            "estimated_complete_seconds": 5,
        }

    try:
        result = _execute_send_approval(email_payload)
        inline_id = f"inline-{account_id}"
        WORKFLOW_STATE[account_id] = {
            **email_payload,
            "ui_state": 5,
            "render_task_run_id": inline_id,
        }
        logger.info(f"[save-customer] inline execution complete → {result['email_to']}")
        return {
            "ok": True,
            "workflow_run_id": inline_id,
            "estimated_complete_seconds": 5,
        }
    except Exception as exc:
        logger.error(f"[save-customer] failed: {exc}")
        return JSONResponse(
            status_code=422,
            content={"ok": False, "reason": f"Failed to queue or execute workflow: {exc}"},
        )


@api.post("/api/webhooks/usage-warning", status_code=202)
async def usage_warning(payload: UsageWarningPayload):
    """
    ClickHouse early signal: usage drop without compound threshold crossed.
    Sets UI state to 2 (Warning). No workflow dispatch.
    """
    account_id = payload.account_id
    detected_ts = datetime.now(timezone.utc).isoformat()

    WORKFLOW_STATE[account_id] = {
        **_empty_workflow_state(account_id, payload.account_name, payload.arr),
        "usage_drop_pct": payload.usage_drop_pct,
        "source": "clickhouse-usage-warning",
        "ui_state": 2,
        "detected_ts": detected_ts,
    }

    logger.info(
        f"[{account_id}] usage-warning → state=2 (Warning) "
        f"drop={payload.usage_drop_pct}% ARR=${payload.arr:,.0f}"
    )

    return {
        "status": "accepted",
        "account_id": account_id,
        "ui_state": 2,
        "ui_state_label": "warning",
        "detected_ts": detected_ts,
    }


@api.post("/api/webhooks/churn-alert", status_code=202)
async def churn_alert(payload: ChurnAlertPayload):
    account_id = payload.account_id
    detected_ts = datetime.now(timezone.utc).isoformat()

    WORKFLOW_STATE[account_id] = {
        **_empty_workflow_state(account_id, payload.account_name, payload.arr),
        "usage_drop_pct": payload.usage_drop_pct,
        "identifiable_issues": payload.identifiable_issues,
        "anonymous_market_sentiment": payload.anonymous_market_sentiment,
        "source": payload.source,
        "ui_state": 3,
        "detected_ts": detected_ts,
    }

    logger.info(
        f"[{account_id}] churn-alert → state=3 (Risk) "
        f"ARR=${payload.arr:,.0f} drop={payload.usage_drop_pct}%"
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
    account_id = payload.account_id

    if account_id not in WORKFLOW_STATE:
        raise HTTPException(status_code=404, detail=f"No active workflow for {account_id}")

    state = WORKFLOW_STATE[account_id]
    state["offer_draft"] = payload.offer_draft
    state["ticket_summary"] = payload.ticket_summary
    state["policy"] = payload.policy
    state["langfuse_trace_id"] = payload.langfuse_trace_id or ""
    state["churn_score"] = payload.churn_score
    state["ui_state"] = 4

    logger.info(f"[{account_id}] task-result received → state=4 (Approval)")
    return {"status": "ok", "account_id": account_id, "ui_state": 4}


@api.get("/api/workflow/status/{account_id}")
def workflow_status(account_id: str):
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
        "policy": s.get("policy"),
        "langfuse_trace_id": s.get("langfuse_trace_id"),
        "detected_ts": s.get("detected_ts"),
        "action_ts": s.get("action_ts"),
        "approved_by": s.get("approved_by"),
        "render_task_run_id": s.get("render_task_run_id"),
        "report_url": f"/public/{account_id}-cited.md" if ui_state == 5 else None,
    }


@api.post("/api/workflow/approve")
async def approve_workflow(payload: ApprovePayload):
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
            detail=f"ui_state={s['ui_state']} — must be 4 (approval) to approve.",
        )

    action_ts = datetime.now(timezone.utc).isoformat()
    s["ui_state"] = 5
    s["approved_by"] = payload.approved_by
    s["action_ts"] = action_ts

    policy = s.get("policy") or _default_policy()
    offer_draft = s.get("offer_draft") or _build_offer_draft(
        account_id=account_id,
        account_name=s["account_name"],
        arr=s["arr"],
        usage_drop_pct=s["usage_drop_pct"],
        identifiable_issues=s["identifiable_issues"],
        anonymous_market_sentiment=s["anonymous_market_sentiment"],
        policy=policy,
    )

    email_payload = {
        "account_id": account_id,
        "account_name": s["account_name"],
        "arr": s["arr"],
        "usage_drop_pct": s["usage_drop_pct"],
        "identifiable_issues": s["identifiable_issues"],
        "anonymous_market_sentiment": s["anonymous_market_sentiment"],
        "offer_draft": offer_draft,
        "ticket_summary": s.get("ticket_summary", ""),
        "policy": policy,
        "approved_by": payload.approved_by,
        "detected_ts": s["detected_ts"],
        "action_ts": action_ts,
        "langfuse_trace_id": s.get("langfuse_trace_id", ""),
    }

    run_id = await _start_render_task(TASK_SEND_EMAIL, {"email_payload": email_payload})

    if run_id:
        s["render_task_run_id"] = run_id
        return {
            "status": "saved",
            "account_id": account_id,
            "ui_state": 5,
            "render_task_run_id": run_id,
            "report_url": f"/public/{account_id}-cited.md",
        }

    result = _execute_send_approval(email_payload)
    return {
        "status": "saved",
        "account_id": account_id,
        "ui_state": 5,
        "render_task_run_id": f"inline-{account_id}",
        "report_url": result["report_url"],
        "email_to": result["email_to"],
    }


@api.get("/api/workflow/all")
def list_all_workflows():
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


app = api
