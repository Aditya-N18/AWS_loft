from __future__ import annotations

from typing import Any

from agent.config import settings
from agent.models import ChurnAlert, WebMention


def _get_client():
    import clickhouse_connect

    if not settings.clickhouse_host:
        raise RuntimeError("CLICKHOUSE_HOST is not configured in .env")

    return clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        username=settings.clickhouse_user or "default",
        password=settings.clickhouse_password,
        database=settings.clickhouse_db,
        secure=True,
    )


def _fetch_market_signals(client) -> list[WebMention]:
    query = """
        SELECT source, sentiment, signal_text, url, ts
        FROM market_signals
        WHERE sentiment = 'negative'
        ORDER BY ts DESC
        LIMIT 10
    """
    rows = client.query(query).named_results()
    mentions: list[WebMention] = []
    for row in rows:
        ts = row.get("ts") or ""
        mentions.append(
            WebMention(
                source=row.get("source") or "reddit",
                sentiment=row.get("sentiment") or "negative",
                signal_text=row.get("signal_text") or "",
                url=row.get("url") or "",
                ts=str(ts),
            )
        )
    return mentions


def fetch_churn_alert(account_id: str) -> ChurnAlert:
    """Fetch latest churn alert from ClickHouse for a given account."""
    client = _get_client()

    score_query = """
        SELECT
            account_id,
            account_name,
            arr,
            usage_now,
            usage_before,
            support_tickets,
            churn_score,
            round((1 - usage_now / (usage_before + 1)) * 100, 1) AS usage_drop_pct
        FROM churn_scores
        WHERE account_id = %(account_id)s
        LIMIT 1
    """
    result = client.query(score_query, parameters={"account_id": account_id})
    rows = list(result.named_results())
    if not rows:
        raise LookupError(f"No churn score found for account_id={account_id!r}")

    row: dict[str, Any] = rows[0]
    web_mentions = _fetch_market_signals(client)
    web_signals = len(web_mentions)

    return ChurnAlert(
        account_id=row["account_id"],
        account_name=row["account_name"],
        arr=float(row["arr"]),
        usage_now=float(row["usage_now"]),
        usage_before=float(row["usage_before"]),
        web_signals=web_signals,
        churn_score=float(row["churn_score"] or 0),
        usage_drop_pct=float(row["usage_drop_pct"]),
        web_mentions=web_mentions,
    )


def list_high_risk_accounts(limit: int = 10) -> list[ChurnAlert]:
    """Return accounts above the configured churn threshold."""
    client = _get_client()
    query = """
        SELECT
            account_id,
            account_name,
            arr,
            usage_now,
            usage_before,
            support_tickets,
            churn_score,
            round((1 - usage_now / (usage_before + 1)) * 100, 1) AS usage_drop_pct
        FROM churn_scores
        WHERE churn_score > %(threshold)s
        ORDER BY churn_score DESC
        LIMIT %(limit)s
    """
    rows = client.query(
        query,
        parameters={"threshold": settings.churn_threshold, "limit": limit},
    ).named_results()

    web_mentions = _fetch_market_signals(client)
    web_signals = len(web_mentions)

    alerts: list[ChurnAlert] = []
    for row in rows:
        alerts.append(
            ChurnAlert(
                account_id=row["account_id"],
                account_name=row["account_name"],
                arr=float(row["arr"]),
                usage_now=float(row["usage_now"]),
                usage_before=float(row["usage_before"]),
                web_signals=web_signals,
                churn_score=float(row["churn_score"] or 0),
                usage_drop_pct=float(row["usage_drop_pct"]),
                web_mentions=web_mentions,
            )
        )
    return alerts
