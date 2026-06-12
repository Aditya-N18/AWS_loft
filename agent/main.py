from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running as `python agent/main.py` from repo root
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.clients.senso import fetch_senso_context
from agent.config import settings
from agent.models import AgentResult, ChurnAlert
from agent.services.cited_report import load_fixture, render_cited_report, write_cited_report
from agent.services.offer_generator import generate_offer
from agent.services.summarizer import summarize_market_signals
from agent.tracing.langfuse_tracer import flush_traces, get_current_trace_id, get_trace_url, traced


@traced("evaluate_churn_alert")
def evaluate_churn_alert(alert: ChurnAlert) -> AgentResult:
    threshold = settings.churn_threshold

    if alert.churn_score < threshold:
        return AgentResult(
            status="monitoring",
            account_id=alert.account_id,
            account_name=alert.account_name,
            churn_score=alert.churn_score,
            threshold=threshold,
            metadata={"reason": "below_threshold"},
        )

    profile = fetch_senso_context(alert.account_id)

    if profile.do_not_contact:
        return AgentResult(
            status="blocked",
            account_id=alert.account_id,
            account_name=alert.account_name,
            churn_score=alert.churn_score,
            threshold=threshold,
            senso_profile=profile,
            metadata={"reason": "do_not_contact"},
        )

    summary = summarize_market_signals(alert, profile)
    offer = generate_offer(alert, profile, summary)

    trace_id = get_current_trace_id()
    cited_content = render_cited_report(
        alert=alert,
        profile=profile,
        offer=offer,
        langfuse_trace_id=trace_id,
        agent_confidence=summary.confidence,
    )
    cited_path = write_cited_report(cited_content, alert.account_id)

    status = "escalate" if profile.escalation_required else "approval_required"

    return AgentResult(
        status=status,
        account_id=alert.account_id,
        account_name=alert.account_name,
        churn_score=alert.churn_score,
        threshold=threshold,
        market_summary=summary,
        senso_profile=profile,
        offer=offer,
        cited_report_path=str(cited_path),
        langfuse_trace_id=trace_id,
        langfuse_trace_url=get_trace_url(trace_id),
        metadata={
            "ui_state": 4 if status == "approval_required" else 3,
            "discount_capped": offer.discount_capped,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Ghost Churn agent core loop")
    parser.add_argument("--fixture", help="Load mock ClickHouse fixture, e.g. acme")
    parser.add_argument("--account-id", help="Fetch from ClickHouse by account ID (requires wiring)")
    parser.add_argument("--json-out", help="Write AgentResult JSON to this path")
    args = parser.parse_args()

    if args.fixture:
        alert = load_fixture(args.fixture)
    elif args.account_id:
        from agent.clients.clickhouse import fetch_churn_alert

        alert = fetch_churn_alert(args.account_id)
    else:
        parser.error("Provide --fixture acme or --account-id <id>")

    result = evaluate_churn_alert(alert)
    flush_traces()

    payload = result.model_dump()
    print(json.dumps(payload, indent=2))

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote {out_path}", file=sys.stderr)

    if result.cited_report_path:
        print(f"\nCited report: {result.cited_report_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
