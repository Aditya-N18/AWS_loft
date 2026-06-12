from __future__ import annotations

from agent.clients.anthropic_client import AnthropicClient
from agent.clients.senso import SensoClient
from agent.models import ChurnAlert, MarketSummary, OfferDraft, SensoProfile
from agent.prompts.offer_email import OFFER_EMAIL_SYSTEM, build_offer_email_prompt
from agent.tracing.langfuse_tracer import traced


def _mock_offer(profile: SensoProfile, summary: MarketSummary, usage_drop_pct: float) -> OfferDraft:
    discount = min(15.0, profile.max_discount_pct)
    return OfferDraft(
        subject=f"Let's get {profile.account_name}'s {profile.use_case} back on track",
        body=(
            f"Hi {profile.key_contact_name},\n\n"
            f"I noticed {profile.account_name}'s activity around {profile.use_case} has dropped "
            f"about {usage_drop_pct:.0f}% over the last two weeks, and your team has raised concerns "
            f"publicly about support responsiveness.\n\n"
            f"We'd like to help before your renewal on {profile.renewal_date}. "
            f"I can offer {discount:.0f}% off your annual renewal and unlock "
            f"{profile.feature_unlock_allowed} at no extra cost, plus a dedicated check-in this week.\n\n"
            f"Would you have 20 minutes to walk through what's blocking you?\n\n"
            f"Best,\nGhost Churn Retention Team"
        ),
        discount_pct=discount,
        feature_unlock=profile.feature_unlock_allowed,
        contact_name=profile.key_contact_name,
        contact_email=profile.key_contact_email,
    )


@traced("generate_offer")
def generate_offer(
    alert: ChurnAlert,
    profile: SensoProfile,
    market_summary: MarketSummary,
) -> OfferDraft:
    client = AnthropicClient()

    if client.mock_mode:
        offer = _mock_offer(profile, market_summary, alert.usage_drop_pct)
    else:
        user_prompt = build_offer_email_prompt(
            account_name=profile.account_name,
            use_case=profile.use_case,
            contact_name=profile.key_contact_name,
            contact_email=profile.key_contact_email,
            renewal_date=profile.renewal_date,
            days_to_renewal=profile.days_to_renewal,
            max_discount_pct=profile.max_discount_pct,
            feature_unlock_allowed=profile.feature_unlock_allowed,
            market_summary=market_summary.summary,
            usage_drop_pct=alert.usage_drop_pct,
        )
        data = client.complete_json(OFFER_EMAIL_SYSTEM, user_prompt)
        offer = OfferDraft(**data)

    senso = SensoClient()
    capped_discount, was_capped = senso.validate_discount(profile, offer.discount_pct)
    if was_capped:
        offer.discount_pct = capped_discount
        offer.discount_capped = True

    return offer
