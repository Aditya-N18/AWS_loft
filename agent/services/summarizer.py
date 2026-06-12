from __future__ import annotations

from agent.clients.anthropic_client import AnthropicClient
from agent.models import ChurnAlert, MarketSummary, SensoProfile
from agent.prompts.market_summary import MARKET_SUMMARY_SYSTEM, build_market_summary_prompt
from agent.tracing.langfuse_tracer import traced


def _mock_summary(alert: ChurnAlert) -> MarketSummary:
    quote = alert.web_mentions[0].signal_text if alert.web_mentions else "Usage has dropped sharply."
    return MarketSummary(
        summary=(
            f"{alert.account_name} shows a {alert.usage_drop_pct:.0f}% usage drop alongside "
            f"{alert.web_signals} negative open-web signals. Public mentions cite frustration "
            f"with support responsiveness and active evaluation of alternatives — e.g. \"{quote}\"."
        ),
        primary_risk="support frustration + competitor evaluation",
        confidence=0.89,
    )


@traced("summarize_market_signals")
def summarize_market_signals(alert: ChurnAlert, profile: SensoProfile | None = None) -> MarketSummary:
    client = AnthropicClient()
    mentions = [m.model_dump() for m in alert.web_mentions]

    if client.mock_mode:
        return _mock_summary(alert)

    user_prompt = build_market_summary_prompt(
        account_name=alert.account_name,
        arr=alert.arr,
        usage_drop_pct=alert.usage_drop_pct,
        web_mentions=mentions,
    )
    data = client.complete_json(MARKET_SUMMARY_SYSTEM, user_prompt)
    return MarketSummary(**data)
