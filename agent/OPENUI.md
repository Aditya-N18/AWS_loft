# OpenUI WebSocket — Aditya integration

Streams **OpenUI Lang** (plain text tokens) over WebSocket with `frame_start` / `frame_end` boundaries.

## Run locally

```powershell
cd D:\Hackathons\AWS_loft
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m agent.openui_server --port 8765
```

## WebSocket URL

```
ws://localhost:8765/ws/ui?fixture=acme&state=4
```

### Query parameters

| Param | Description |
|-------|-------------|
| `fixture` | Mock ClickHouse data, e.g. `acme` |
| `account_id` | Live ClickHouse row, e.g. `acme-corp` |
| `state` | UI state 1–5 (optional; auto-inferred if omitted) |
| `evaluate` | `true` (default) runs full agent pipeline before render |
| `cited_md_url` | For state 5 |
| `crm_url` | For state 5 |

### Examples

```
ws://localhost:8765/ws/ui?fixture=acme&state=1   # AccountHealthMonitor
ws://localhost:8765/ws/ui?fixture=acme&state=2   # EarlyWarningCard
ws://localhost:8765/ws/ui?fixture=acme&state=3   # ChurnRiskDashboard
ws://localhost:8765/ws/ui?fixture=acme&state=4   # OfferApprovalCard
ws://localhost:8765/ws/ui?fixture=acme&state=5   # SaveReport
ws://localhost:8765/ws/ui?account_id=acme-corp&state=4
```

## Frame format

Each message is plain text. Boundaries are JSON lines:

```
{"type":"frame_start"}
root = Stack([approval])
approval = OfferApprovalCard(...)
{"type":"frame_end"}
```

## Render deployment (Aditya — other machine)

Deploy as a Render **Web Service** from branch `kenil/agent-core`.

**Start command:**
```bash
uvicorn agent.openui_server:app --host 0.0.0.0 --port $PORT
```

**Build command:**
```bash
pip install -r requirements.txt
```

**Health check path:** `/health`

Or use the repo `render.yaml` blueprint.

After deploy, open `https://YOUR-SERVICE.onrender.com/` — the JSON shows the WebSocket URL.

**Aditya connects to:**
```
wss://YOUR-SERVICE.onrender.com/ws/ui?fixture=acme&state=4
```

Set these env vars in Render dashboard (same keys Aarsh uses):

- `ANTHROPIC_API_KEY`
- `SENSO_API_KEY`
- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_SECRET_KEY`
- `LANGFUSE_HOST=https://us.cloud.langfuse.com`
- `CLICKHOUSE_HOST`, `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`, `CLICKHOUSE_DB=ghost_churn`
- `AGENT_MOCK_MODE=false`
- `CHURN_THRESHOLD=5000`

## LAN / ngrok (local dev only)

Replace `localhost` with your machine IP, or expose via ngrok:

```powershell
ngrok http 8765
```

Connect frontend to `wss://YOUR-NGROK/ws/ui?fixture=acme&state=4` (use ngrok TCP for raw WS if needed).

## System prompt

Aditya's OpenUI Lang spec lives in `agent/prompts/openui_system.py`.

When `AGENT_MOCK_MODE=false` and `ANTHROPIC_API_KEY` is set, Claude streams live OpenUI Lang. Otherwise deterministic templates stream for demo reliability.
