OFFER_EMAIL_SYSTEM = """You are a retention agent drafting a personalized save email.
Ground every claim in the provided account context and churn signals.
Stay within authorized discount limits. Respond with valid JSON only."""


def build_offer_email_prompt(
    account_name: str,
    use_case: str,
    contact_name: str,
    contact_email: str,
    renewal_date: str,
    days_to_renewal: int,
    max_discount_pct: float,
    feature_unlock_allowed: str,
    market_summary: str,
    usage_drop_pct: float,
) -> str:
    return f"""Draft a save offer email for a customer at churn risk.

Account: {account_name}
Use case on record: {use_case}
Key contact: {contact_name} <{contact_email}>
Renewal date: {renewal_date} ({days_to_renewal} days away)
Max authorized discount: {max_discount_pct}%
Allowed feature unlock: {feature_unlock_allowed}
Usage drop: {usage_drop_pct:.1f}%
Risk summary: {market_summary}

Rules:
- Propose a discount at or below {max_discount_pct}% (prefer slightly below max, e.g. 15% if max is 20%)
- Reference the specific use case and at least one concrete pain signal
- Professional, concise, human tone — not a generic marketing blast
- Include the feature unlock if appropriate

Return JSON:
{{
  "subject": "...",
  "body": "multi-paragraph email body as plain text with line breaks",
  "discount_pct": 0,
  "feature_unlock": "{feature_unlock_allowed}",
  "contact_name": "{contact_name}",
  "contact_email": "{contact_email}"
}}"""
