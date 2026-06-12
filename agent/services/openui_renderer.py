from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from agent.config import settings
from agent.models import AgentResult, ChurnAlert
from agent.prompts.openui_system import OPENUI_SYSTEM_PROMPT
from agent.services.openui_context import build_openui_user_prompt, infer_ui_state

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _mock_openui_lang(alert: ChurnAlert, result: AgentResult | None, ui_state: int, **kwargs: Any) -> str:
    cited_md_url = kwargs.get("cited_md_url") or "https://ghost-churn.onrender.com/cited/acme-corp.md"
    history = [102, 98, 90, 75, 60, 45, 35]
    quotes = alert.web_mentions[:2] if alert.web_mentions else []
    profile = result.senso_profile if result else None
    offer = result.offer if result else None
    summary = result.market_summary.summary if result and result.market_summary else "Usage drop with negative public signals."
    trace = result.langfuse_trace_id if result and result.langfuse_trace_id else "lf_trace_mock"

    if ui_state == 1:
        return (
            'root = Stack([monitor])\n'
            'monitor = AccountHealthMonitor([{name: "CloudPeak", arr: 29000, usagePct: 92}, '
            '{name: "TechFlow", arr: 32000, usagePct: 88}, {name: "Nexus AI", arr: 55000, usagePct: 95}, '
            '{name: "DevBase", arr: 61000, usagePct: 91}], 2, 4)\n'
        )

    if ui_state == 2:
        return (
            'root = Stack([warning])\n'
            f'warning = EarlyWarningCard("{_escape(alert.account_name)}", {int(alert.arr)}, '
            f'{round(alert.usage_drop_pct, 1)}, 5, {history})\n'
        )

    if ui_state == 3:
        tickets = '[{subject: "Exports broken since last update", daysAgo: 6}]'
        wq = "[]"
        if quotes:
            q0 = quotes[0]
            src = q0.source if q0.source in {"reddit", "twitter", "g2", "capterra"} else "reddit"
            wq = f'[{{source: "{src}", quote: "{_escape(q0.signal_text)}", url: "{_escape(q0.url)}"}}]'
        return (
            'root = Stack([dashboard])\n'
            f'dashboard = ChurnRiskDashboard("{_escape(alert.account_name)}", {int(alert.arr)}, '
            f'{int(alert.arr)}, {int(alert.churn_score)}, {int(settings.churn_threshold)}, '
            f'{profile.days_to_renewal if profile else 23}, {round(alert.usage_drop_pct, 1)}, {history}, '
            f'{tickets}, {wq}, "{_escape(summary)}", "{trace}")\n'
        )

    if ui_state == 4 and profile and offer:
        reasoning = (
            f'["Usage down {round(alert.usage_drop_pct)}%", '
            f'"{alert.web_signals} negative web signals", '
            f'"Senso max discount {int(profile.max_discount_pct)}%"]'
        )
        return (
            'root = Stack([approval])\n'
            f'approval = OfferApprovalCard("{_escape(alert.account_name)}", {int(alert.arr)}, '
            f'"{_escape(profile.key_contact_name)}", "{_escape(profile.key_contact_email)}", '
            f'"{_escape(offer.subject)}", "{_escape(offer.body)}", {offer.discount_pct}, '
            f'"{_escape(offer.feature_unlock)}", {profile.days_to_renewal}, '
            f'"{_escape(profile.senso_policy)}", {profile.max_discount_pct}, {reasoning})\n'
        )

    if ui_state == 5:
        return (
            'root = Stack([report])\n'
            f'report = SaveReport("{_escape(alert.account_name)}", {int(alert.arr)}, "47 minutes", '
            '[{label: "Reddit signal detected", detail: "Public complaint ingested", time: "T+0m"}, '
            '{label: "Churn score computed", detail: "Threshold exceeded", time: "T+12m"}, '
            '{label: "Offer sent", detail: "Save email dispatched", time: "T+47m"}], '
            '{timeToDetect: "12 min", timeToOffer: "28 min", timeToSend: "47 min"}, '
            f'"{cited_md_url}", "{trace}", "https://app.hubspot.com/tasks/48291")\n'
        )

    return 'root = Stack([monitor])\nmonitor = AccountHealthMonitor([], 1, 0)\n'


async def _stream_text(text: str, chunk_size: int = 12) -> AsyncIterator[str]:
    for i in range(0, len(text), chunk_size):
        yield text[i : i + chunk_size]
        await asyncio.sleep(0.01)


async def stream_openui_lang(
    alert: ChurnAlert,
    result: AgentResult | None,
    ui_state: int | None = None,
    **kwargs: Any,
) -> AsyncIterator[str]:
    state = ui_state or infer_ui_state(alert, result)
    user_prompt = build_openui_user_prompt(alert, result, state, **kwargs)

    use_mock = settings.agent_mock_mode or not settings.has_anthropic or anthropic is None

    if use_mock:
        text = _mock_openui_lang(alert, result, state, **kwargs)
        async for chunk in _stream_text(text):
            yield chunk
        return

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    with client.messages.stream(
        model=settings.anthropic_model,
        max_tokens=2000,
        system=OPENUI_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        for text in stream.text_stream:
            yield text


async def stream_framed_openui(
    alert: ChurnAlert,
    result: AgentResult | None,
    ui_state: int | None = None,
    **kwargs: Any,
) -> AsyncIterator[str]:
    yield '{"type":"frame_start"}\n'
    async for token in stream_openui_lang(alert, result, ui_state, **kwargs):
        yield token
    yield '\n{"type":"frame_end"}\n'
