from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class WebMention(BaseModel):
    source: str
    sentiment: str
    signal_text: str
    url: str
    ts: str


class ChurnAlert(BaseModel):
    account_id: str
    account_name: str
    arr: float
    usage_now: float
    usage_before: float
    web_signals: int
    churn_score: float
    usage_drop_pct: float
    web_mentions: list[WebMention] = Field(default_factory=list)


class SensoProfile(BaseModel):
    account_id: str
    account_name: str
    arr: float
    renewal_date: str
    days_to_renewal: int
    key_contact_name: str
    key_contact_email: str
    use_case: str
    product_tier: str
    max_discount_pct: float
    feature_unlock_allowed: str
    senso_policy: str
    escalation_required: bool = False
    do_not_contact: bool = False
    raw_answer: str = ""


class MarketSummary(BaseModel):
    summary: str
    primary_risk: str
    confidence: float


class OfferDraft(BaseModel):
    subject: str
    body: str
    discount_pct: float
    feature_unlock: str
    contact_name: str
    contact_email: str
    discount_capped: bool = False


class AgentResult(BaseModel):
    status: str
    account_id: str
    account_name: str
    churn_score: float
    threshold: float
    market_summary: MarketSummary | None = None
    senso_profile: SensoProfile | None = None
    offer: OfferDraft | None = None
    cited_report_path: str | None = None
    langfuse_trace_id: str | None = None
    langfuse_trace_url: str | None = None
    evaluated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    metadata: dict[str, Any] = Field(default_factory=dict)
