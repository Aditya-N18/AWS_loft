import os
import time

import clickhouse_connect

client = clickhouse_connect.get_client(
    host=os.environ["CLICKHOUSE_HOST"],
    user=os.environ["CLICKHOUSE_USER"],
    password=os.environ["CLICKHOUSE_PASSWORD"],
    secure=True,
    verify=False,
)

THRESHOLD = 25000  # lowered to match current data
already_fired = set()

print("Poller running... checking every 10 seconds")

while True:
    result = client.query("""
        SELECT account_id, account_name, arr,
               round(churn_score, 0) AS churn_score
        FROM ghost_churn.churn_scores
        WHERE churn_score > 20000
        ORDER BY churn_score DESC
    """)

    for row in result.named_results():
        acct_id = row["account_id"]
        if acct_id not in already_fired:
            print(
                f"🚨 ANOMALY DETECTED: {row['account_name']} | "
                f"score={row['churn_score']} | ARR=${row['arr']:.0f}"
            )
            already_fired.add(acct_id)

    time.sleep(10)
