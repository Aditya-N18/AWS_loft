import os
import uuid
from datetime import datetime, timedelta

import clickhouse_connect
from flask import Flask, jsonify

app = Flask(__name__)


def get_client():
    return clickhouse_connect.get_client(
        host=os.environ.get("CLICKHOUSE_HOST", "gr0sklg10m.us-west-2.aws.clickhouse.cloud"),
        user=os.environ.get("CLICKHOUSE_USER", "default"),
        password=os.environ.get("CLICKHOUSE_PASSWORD", "y_T~V4F~ECB02"),
        secure=True,
        verify=False,
    )


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/inject", methods=["POST"])
def inject():
    client = get_client()
    now = datetime.now()

    activity_rows = [
        ["acme-corp", "Acme Corp", 48000.0, "api_calls", 0, now],
        ["acme-corp", "Acme Corp", 48000.0, "dashboard_logins", 0, now],
        ["acme-corp", "Acme Corp", 48000.0, "export_runs", 0, now],
        ["acme-corp", "Acme Corp", 48000.0, "integrations", 0, now],
    ]
    client.insert(
        "ghost_churn.account_activity",
        activity_rows,
        column_names=["account_id", "account_name", "arr", "feature_name", "event_count", "ts"],
    )

    support_rows = [
        ["acme-corp", "Acme Corp", str(uuid.uuid4()), "negative", "Nothing works, evaluating alternatives", now],
        ["acme-corp", "Acme Corp", str(uuid.uuid4()), "negative", "Exports still broken after 2 weeks", now],
    ]
    client.insert(
        "ghost_churn.support_signals",
        support_rows,
        column_names=["account_id", "account_name", "ticket_id", "sentiment", "subject", "ts"],
    )

    return jsonify({"status": "injected"})


@app.route("/reset", methods=["POST"])
def reset():
    client = get_client()
    cutoff = datetime.now() - timedelta(minutes=15)

    client.command(
        """
        ALTER TABLE ghost_churn.account_activity
        DELETE WHERE account_id = 'acme-corp' AND ts > {cutoff:DateTime}
        """,
        parameters={"cutoff": cutoff},
    )
    client.command(
        """
        ALTER TABLE ghost_churn.support_signals
        DELETE WHERE account_id = 'acme-corp' AND ts > {cutoff:DateTime}
        """,
        parameters={"cutoff": cutoff},
    )

    return jsonify({"status": "reset"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
