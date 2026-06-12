import clickhouse_connect
import uuid
import random
from datetime import datetime, timedelta
import os

client = clickhouse_connect.get_client(
    host='gr0sklg10m.us-west-2.aws.clickhouse.cloud',
    user='default',
    password='y_T~V4F~ECB02',
    secure=True,
    verify = False
)

accounts = [
    {"id": "acme-corp",  "name": "Acme Corp",  "arr": 48000},
    {"id": "techflow",   "name": "TechFlow",    "arr": 32000},
    {"id": "devbase",    "name": "DevBase",     "arr": 61000},
    {"id": "cloudpeak",  "name": "CloudPeak",   "arr": 29000},
    {"id": "nexus-ai",   "name": "Nexus AI",    "arr": 55000},
]
features = ["api_calls", "dashboard_logins", "export_runs", "integrations"]

# --- account_activity ---
rows = []
for day in range(14, 0, -1):
    ts = datetime.now() - timedelta(days=day)
    for acc in accounts:
        for feat in features:
            if acc["id"] == "acme-corp":
                # gradual decline: starts ~100, ends ~15
                count = max(2, int(100 * (1 - (14 - day) / 14 * 0.85) + random.randint(-4, 4)))
            else:
                count = random.randint(75, 125)
            rows.append([acc["id"], acc["name"], acc["arr"], feat, count, ts])

client.insert('ghost_churn.account_activity', rows,
    column_names=['account_id','account_name','arr','feature_name','event_count','ts'])
print(f"✓ account_activity: {len(rows)} rows")

# --- support_signals (Acme only — 4 tickets over last 6 days) ---
tickets = [
    ["acme-corp", "Acme Corp", str(uuid.uuid4()), "negative", "Exports broken since last update",          datetime.now() - timedelta(days=6)],
    ["acme-corp", "Acme Corp", str(uuid.uuid4()), "negative", "Dashboard not loading for half our team",   datetime.now() - timedelta(days=4)],
    ["acme-corp", "Acme Corp", str(uuid.uuid4()), "negative", "API rate limits blocking our pipeline",     datetime.now() - timedelta(days=2)],
    ["acme-corp", "Acme Corp", str(uuid.uuid4()), "negative", "No response from support in 5 days",        datetime.now() - timedelta(days=1)],
    ["techflow",  "TechFlow",  str(uuid.uuid4()), "neutral",  "Question about billing cycle",              datetime.now() - timedelta(days=3)],
]
client.insert('ghost_churn.support_signals', tickets,
    column_names=['account_id','account_name','ticket_id','sentiment','subject','ts'])
print(f"✓ support_signals: {len(tickets)} rows")

# --- market_signals (anonymous Reddit/G2 complaints) ---
complaints = [
    ["reddit", "Export feature has been broken for weeks, support is unresponsive",          "https://reddit.com/r/saas/comments/abc1"],
    ["g2",     "Price increased 30% with no warning, looking at alternatives",               "https://g2.com/reviews/abc2"],
    ["reddit", "Dashboard timeouts on any dataset over 10k rows",                            "https://reddit.com/r/saas/comments/abc3"],
    ["g2",     "Missing Salesforce integration that every competitor has",                   "https://g2.com/reviews/abc4"],
    ["reddit", "Support took 6 days to respond to a critical bug report",                   "https://reddit.com/r/saas/comments/abc5"],
    ["twitter","Switching away from this tool, exports are completely broken",               "https://twitter.com/user/status/abc6"],
    ["g2",     "API rate limits are way too restrictive for enterprise use",                 "https://g2.com/reviews/abc7"],
    ["reddit", "No SSO support is a dealbreaker for our security team",                     "https://reddit.com/r/saas/comments/abc8"],
    ["g2",     "Onboarding docs are outdated, spent 2 weeks figuring things out",           "https://g2.com/reviews/abc9"],
    ["reddit", "Been a customer 2 years, recent updates broke half our workflows",          "https://reddit.com/r/saas/comments/abc10"],
]
mkt_rows = [
    [str(uuid.uuid4()), src, txt, url, "negative", datetime.now() - timedelta(days=random.randint(1, 7))]
    for src, txt, url in complaints
]
client.insert('ghost_churn.market_signals', mkt_rows,
    column_names=['signal_id','source','signal_text','url','sentiment','ts'])
print(f"✓ market_signals: {len(mkt_rows)} rows")

print("\n✓ All done. Run: SELECT account_id, churn_score FROM ghost_churn.churn_scores ORDER BY churn_score DESC")