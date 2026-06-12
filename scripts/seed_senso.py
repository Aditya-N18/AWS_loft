#!/usr/bin/env python3
"""Seed Senso knowledge base with 5 demo account profiles."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SENSO_BASE = "https://apiv2.senso.ai/api/v1"
FIXTURES = ROOT / "agent" / "fixtures" / "senso_accounts.json"


def account_markdown(account_id: str, data: dict) -> str:
    return f"""# Account Profile: {data['account_name']}

**Account ID:** {account_id}
**ARR:** ${data['arr']:,}
**Product Tier:** {data['product_tier']}
**Renewal Date:** {data['renewal_date']} ({data['days_to_renewal']} days remaining)

## Key Contact
- **Name:** {data['key_contact_name']}
- **Email:** {data['key_contact_email']}

## Use Case
{data['use_case']}

## Discount Guardrails
- **Max authorized discount:** {data['max_discount_pct']}%
- **Allowed feature unlock:** {data['feature_unlock_allowed']}
- **Policy:** {data['senso_policy']}
- **Escalation required:** {'Yes' if data.get('escalation_required') else 'No'}
- **Do not contact:** {'Yes' if data.get('do_not_contact') else 'No'}

## Offer Templates
Pre-approved language: acknowledge usage drop, reference use case, offer discount up to {data['max_discount_pct']}%, include {data['feature_unlock_allowed']} if appropriate.
"""


def find_folder(api_key: str, name: str) -> str | None:
    headers = {"X-API-Key": api_key}
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{SENSO_BASE}/org/kb/find", headers=headers, params={"q": name})
        if response.status_code != 200:
            return None
        for item in response.json().get("nodes", []):
            if item.get("type") == "folder" and item.get("name") == name:
                return item.get("kb_node_id")
    return None


def create_folder(api_key: str, name: str) -> str | None:
    existing = find_folder(api_key, name)
    if existing:
        return existing

    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{SENSO_BASE}/org/kb/folders",
            headers=headers,
            json={"name": name},
        )
        if response.status_code in {200, 201}:
            body = response.json()
            return body.get("kb_node_id") or body.get("id")
        if response.status_code == 409:
            return find_folder(api_key, name)
        response.raise_for_status()
    return None


def ingest_raw(api_key: str, title: str, content: str, folder_id: str | None = None) -> dict:
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    payload: dict = {
        "title": title,
        "text": content,
        "summary": f"Ghost Churn demo account profile: {title}",
    }
    if folder_id:
        payload["kb_folder_node_id"] = folder_id

    with httpx.Client(timeout=30.0) as client:
        response = client.post(f"{SENSO_BASE}/org/kb/raw", headers=headers, json=payload)
        if response.status_code == 409:
            return {"id": "already_exists", "processing_status": "duplicate"}
        if response.status_code >= 400:
            print(f"Senso error {response.status_code}: {response.text}", file=sys.stderr)
        response.raise_for_status()
        return response.json()


def main() -> int:
    api_key = os.getenv("SENSO_API_KEY", "")
    if not api_key:
        print("SENSO_API_KEY not set. Skipping remote seed.")
        print(f"Local fixtures available at: {FIXTURES}")
        print("Set SENSO_API_KEY in .env and re-run to upload to Senso.")
        return 0

    accounts = json.loads(FIXTURES.read_text(encoding="utf-8"))
    print(f"Seeding {len(accounts)} account profiles to Senso...")

    folder_id = create_folder(api_key, "ghost-churn-accounts")
    if folder_id:
        print(f"Using folder ghost-churn-accounts: {folder_id}")

    for account_id, data in accounts.items():
        title = f"{data['account_name']} ({account_id})"
        content = account_markdown(account_id, data)
        result = ingest_raw(api_key, title, content, folder_id)
        node_id = result.get("id") or result.get("kb_node_id") or "ok"
        print(f"  OK {title} -> {node_id}")

    print("Done. Query Senso with: 'What is the max authorized discount for acme-corp?'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
