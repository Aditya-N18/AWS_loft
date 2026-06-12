from __future__ import annotations

import json
from typing import Any

import httpx

from agent.config import settings
from agent.models import SensoProfile

SENSO_BASE = "https://apiv2.senso.ai/api/v1"


def _load_mock_profiles() -> dict[str, dict[str, Any]]:
    path = settings.fixtures_dir / "senso_accounts.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_profile(account_id: str, data: dict[str, Any], raw_answer: str = "") -> SensoProfile:
    return SensoProfile(
        account_id=data["account_id"],
        account_name=data["account_name"],
        arr=float(data["arr"]),
        renewal_date=data["renewal_date"],
        days_to_renewal=int(data["days_to_renewal"]),
        key_contact_name=data["key_contact_name"],
        key_contact_email=data["key_contact_email"],
        use_case=data["use_case"],
        product_tier=data["product_tier"],
        max_discount_pct=float(data["max_discount_pct"]),
        feature_unlock_allowed=data["feature_unlock_allowed"],
        senso_policy=data["senso_policy"],
        escalation_required=bool(data.get("escalation_required", False)),
        do_not_contact=bool(data.get("do_not_contact", False)),
        raw_answer=raw_answer,
    )


class SensoClient:
    def __init__(self) -> None:
        self.api_key = settings.senso_api_key
        self.mock_mode = settings.agent_mock_mode or not settings.has_senso

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key, "Content-Type": "application/json"}

    def search(self, query: str, max_results: int = 5) -> dict[str, Any]:
        if self.mock_mode:
            return {"answer": "", "results": [], "mock": True}

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{SENSO_BASE}/org/search",
                headers=self._headers(),
                json={"query": query, "max_results": max_results},
            )
            response.raise_for_status()
            return response.json()

    def fetch_account_context(self, account_id: str) -> SensoProfile:
        mock_profiles = _load_mock_profiles()
        if account_id not in mock_profiles:
            raise KeyError(f"Unknown account_id in fixtures: {account_id}")

        if self.mock_mode:
            return _parse_profile(account_id, mock_profiles[account_id], raw_answer="mock")

        query = (
            f"Return account profile for {account_id}: key contact, renewal date, "
            f"max authorized discount, use case, product tier, escalation rules, "
            f"and do-not-contact status."
        )
        result = self.search(query, max_results=8)
        answer = result.get("answer") or json.dumps(result.get("results", []))
        profile = _parse_profile(account_id, mock_profiles[account_id], raw_answer=answer)
        return profile

    def validate_discount(self, profile: SensoProfile, proposed_discount: float) -> tuple[float, bool]:
        if proposed_discount <= profile.max_discount_pct:
            return proposed_discount, False
        return profile.max_discount_pct, True


def fetch_senso_context(account_id: str) -> SensoProfile:
    return SensoClient().fetch_account_context(account_id)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fetch Senso account profile")
    parser.add_argument("--account", required=True, help="Account ID, e.g. acme-corp")
    args = parser.parse_args()

    profile = fetch_senso_context(args.account)
    print(profile.model_dump_json(indent=2))
