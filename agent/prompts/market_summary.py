MARKET_SUMMARY_SYSTEM = """You are a customer success analyst for Ghost Churn.
Summarize why an account is at churn risk using only the provided signals.
Respond with valid JSON only — no markdown fences."""


def build_market_summary_prompt(
    account_name: str,
    arr: float,
    usage_drop_pct: float,
    web_mentions: list[dict],
) -> str:
    mentions_text = "\n".join(
        f"- [{m['source']}] ({m['sentiment']}) {m['signal_text']} | {m['url']}"
        for m in web_mentions
    )
    return f"""Account: {account_name}
ARR: ${arr:,.0f}
Usage drop (7d vs prior 7d): {usage_drop_pct:.1f}%

Web mentions:
{mentions_text or '- none'}

Return JSON:
{{
  "summary": "2-3 sentences explaining why this customer may leave",
  "primary_risk": "single short label, e.g. support frustration",
  "confidence": 0.0
}}"""
