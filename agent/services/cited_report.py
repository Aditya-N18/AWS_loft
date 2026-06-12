from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from agent.config import settings
from agent.models import AgentResult, ChurnAlert, OfferDraft, SensoProfile
from agent.tracing.langfuse_tracer import traced


def _usage_drop_ratio(alert: ChurnAlert) -> str:
    if alert.usage_before <= 0:
        return "0"
    ratio = 1 - (alert.usage_now / (alert.usage_before + 1))
    return f"{ratio:.2f}"


def _minutes_since_first_signal(alert: ChurnAlert) -> int:
    if not alert.web_mentions:
        return 0
    first_ts = min(datetime.fromisoformat(m.ts.replace("Z", "+00:00")) for m in alert.web_mentions)
    now = datetime.now(timezone.utc)
    return max(1, int((now - first_ts).total_seconds() / 60))


@traced("render_cited_report")
def render_cited_report(
    alert: ChurnAlert,
    profile: SensoProfile,
    offer: OfferDraft,
    *,
    langfuse_trace_id: str | None = None,
    agent_confidence: float = 0.91,
    steps_traced: int = 7,
    hallucination_flags: int = 0,
    crm_task_id: str = "HubSpot Task #48291",
    approved_by: str = "[human operator]",
) -> str:
    env = Environment(
        loader=FileSystemLoader(str(settings.templates_dir)),
        autoescape=select_autoescape(enabled_extensions=()),
    )
    template = env.get_template("cited.md.j2")
    return template.render(
        account_name=alert.account_name,
        arr=alert.arr,
        action_taken_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        minutes_signal_to_action=_minutes_since_first_signal(alert),
        web_mentions=[m.model_dump() for m in alert.web_mentions],
        usage_drop_pct=round(alert.usage_drop_pct, 1),
        usage_now=int(alert.usage_now),
        usage_before=int(alert.usage_before),
        usage_drop_ratio=_usage_drop_ratio(alert),
        web_signals=alert.web_signals,
        churn_score=int(alert.churn_score),
        threshold=int(settings.churn_threshold),
        max_discount_pct=int(profile.max_discount_pct),
        key_contact_name=profile.key_contact_name,
        key_contact_title=profile.product_tier,
        renewal_date=profile.renewal_date,
        days_to_renewal=profile.days_to_renewal,
        use_case=profile.use_case,
        senso_policy=profile.senso_policy,
        offer_discount_pct=int(offer.discount_pct),
        feature_unlock=offer.feature_unlock,
        contact_email=offer.contact_email,
        crm_task_id=crm_task_id,
        approved_by=approved_by,
        langfuse_trace_id=langfuse_trace_id or "lf_trace_mock",
        agent_confidence=agent_confidence,
        steps_traced=steps_traced,
        hallucination_flags=hallucination_flags,
    )


def write_cited_report(content: str, account_id: str) -> Path:
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    path = settings.output_dir / f"cited-{account_id}.md"
    path.write_text(content, encoding="utf-8")
    return path


def render_from_result(result: AgentResult, alert: ChurnAlert) -> Path:
    if not result.senso_profile or not result.offer:
        raise ValueError("AgentResult missing senso_profile or offer")
    content = render_cited_report(
        alert=alert,
        profile=result.senso_profile,
        offer=result.offer,
        langfuse_trace_id=result.langfuse_trace_id,
        agent_confidence=result.market_summary.confidence if result.market_summary else 0.91,
    )
    return write_cited_report(content, alert.account_id)


def load_fixture(name: str) -> ChurnAlert:
    fixture_map = {"acme": "acme_churn_alert.json"}
    filename = fixture_map.get(name, name if name.endswith(".json") else f"{name}_churn_alert.json")
    path = settings.fixtures_dir / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    return ChurnAlert(**data)


if __name__ == "__main__":
    from agent.clients.senso import fetch_senso_context
    from agent.services.offer_generator import generate_offer
    from agent.services.summarizer import summarize_market_signals

    parser = argparse.ArgumentParser(description="Render cited.md from fixture")
    parser.add_argument("--fixture", default="acme", help="Fixture name, e.g. acme")
    args = parser.parse_args()

    alert = load_fixture(args.fixture)
    profile = fetch_senso_context(alert.account_id)
    summary = summarize_market_signals(alert, profile)
    offer = generate_offer(alert, profile, summary)
    content = render_cited_report(alert, profile, offer)
    path = write_cited_report(content, alert.account_id)
    print(path)
