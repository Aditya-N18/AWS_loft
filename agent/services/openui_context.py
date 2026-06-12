from __future__ import annotations

import json
from typing import Any

from agent.config import settings
from agent.models import AgentResult, ChurnAlert, WebMention


def _usage_history(alert: ChurnAlert) -> list[int]:
    before = max(int(alert.usage_before), 1)
    now = max(int(alert.usage_now), 0)
    return [
        int(before * 0.95),
        int(before * 1.0),
        int(before * 0.88),
        int(before * 0.72),
        int(before * 0.55),
        int(now * 0.9),
        now,
    ]


def _web_quotes(mentions: list[WebMention]) -> list[dict[str, str]]:
    quotes: list[dict[str, str]] = []
    for m in mentions:
        source = m.source if m.source in {"reddit", "twitter", "g2", "capterra"} else "reddit"
        quotes.append({"source": source, "quote": m.signal_text, "url": m.url})
    return quotes


def infer_ui_state(alert: ChurnAlert, result: AgentResult | None = None) -> int:
    if result and result.metadata.get("ui_state"):
        return int(result.metadata["ui_state"])
    if alert.churn_score < settings.churn_threshold:
        return 1
    if alert.usage_drop_pct > 30 and alert.web_signals == 0:
        return 2
    if result and result.status == "approval_required":
        return 4
    if alert.churn_score > 50000 and alert.web_signals > 0:
        return 3
    return 3


def build_openui_user_prompt(
    alert: ChurnAlert,
    result: AgentResult | None,
    ui_state: int,
    *,
    cited_md_url: str | None = None,
    crm_url: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "ui_state_to_render": ui_state,
        "account_id": alert.account_id,
        "account_name": alert.account_name,
        "arr": alert.arr,
        "churn_score": alert.churn_score,
        "threshold": settings.churn_threshold,
        "usage_drop_pct": alert.usage_drop_pct,
        "usage_history": _usage_history(alert),
        "web_signals_count": alert.web_signals,
        "web_quotes": _web_quotes(alert.web_mentions),
        "support_tickets": [
            {"subject": "Exports broken since last update", "daysAgo": 6},
            {"subject": "Dashboard not loading for half our team", "daysAgo": 4},
        ],
    }

    if result and result.market_summary:
        payload["market_signal_summary"] = result.market_summary.summary

    if result and result.senso_profile:
        p = result.senso_profile
        payload["senso"] = {
            "renewal_days": p.days_to_renewal,
            "contact_name": p.key_contact_name,
            "contact_email": p.key_contact_email,
            "senso_policy": p.senso_policy,
            "max_discount_pct": p.max_discount_pct,
            "use_case": p.use_case,
        }

    if result and result.offer:
        o = result.offer
        payload["offer"] = {
            "subject": o.subject,
            "email_body": o.body,
            "discount_pct": o.discount_pct,
            "feature_unlock": o.feature_unlock,
        }

    if result and result.langfuse_trace_id:
        payload["langfuse_trace_id"] = result.langfuse_trace_id

    if ui_state == 1:
        payload["healthy_accounts"] = [
            {"name": "CloudPeak", "arr": 29000, "usagePct": 92},
            {"name": "TechFlow", "arr": 32000, "usagePct": 88},
            {"name": "Nexus AI", "arr": 55000, "usagePct": 95},
            {"name": "DevBase", "arr": 61000, "usagePct": 91},
        ]

    if ui_state == 5:
        payload["save_report"] = {
            "arr_protected": alert.arr,
            "total_duration_label": "47 minutes",
            "cited_md_url": cited_md_url or "https://ghost-churn.onrender.com/cited/acme-corp.md",
            "crm_url": crm_url or "https://app.hubspot.com/tasks/48291",
            "timeline": [
                {"label": "Reddit signal detected", "detail": alert.web_mentions[0].signal_text if alert.web_mentions else "", "time": "T+0m"},
                {"label": "Churn score computed", "detail": f"Score {int(alert.churn_score)}", "time": "T+12m"},
                {"label": "Senso verified", "detail": "Discount within policy", "time": "T+28m"},
                {"label": "Offer approved & sent", "detail": "Save email dispatched", "time": "T+47m"},
            ],
            "metrics": {
                "timeToDetect": "12 min",
                "timeToOffer": "28 min",
                "timeToSend": "47 min",
            },
        }

    return (
        f"Render Ghost Churn UI STATE {ui_state} using OpenUI Lang.\n"
        f"Use this data exactly:\n{json.dumps(payload, indent=2)}"
    )
