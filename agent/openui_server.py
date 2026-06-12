"""WebSocket server streaming OpenUI Lang for Aditya's frontend."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from agent.config import settings
from agent.main import evaluate_churn_alert
from agent.models import ChurnAlert
from agent.services.cited_report import load_fixture
from agent.services.openui_context import infer_ui_state
from agent.services.openui_renderer import stream_framed_openui
from agent.tracing.langfuse_tracer import flush_traces

app = FastAPI(title="Ghost Churn OpenUI Stream", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _load_alert(fixture: str | None, account_id: str | None) -> ChurnAlert:
    if fixture:
        return load_fixture(fixture)
    if account_id:
        from agent.clients.clickhouse import fetch_churn_alert

        return fetch_churn_alert(account_id)
    return load_fixture("acme")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ghost-churn-openui"}


@app.get("/")
def root() -> dict[str, str]:
    import os

    base = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8765").rstrip("/")
    ws_base = base.replace("https://", "wss://").replace("http://", "ws://")
    return {
        "websocket": f"{ws_base}/ws/ui?fixture=acme&state=4",
        "health": f"{base}/health",
    }


@app.websocket("/ws/ui")
async def ws_ui(
    websocket: WebSocket,
    fixture: str | None = Query(None),
    account_id: str | None = Query(None),
    state: int | None = Query(None, ge=1, le=5),
    cited_md_url: str | None = Query(None),
    crm_url: str | None = Query(None),
    evaluate: bool = Query(True, description="Run full agent pipeline before rendering UI"),
):
    await websocket.accept()
    try:
        alert = _load_alert(fixture, account_id)
        result = evaluate_churn_alert(alert) if evaluate else None
        ui_state = state or infer_ui_state(alert, result)

        async for chunk in stream_framed_openui(
            alert,
            result,
            ui_state=ui_state,
            cited_md_url=cited_md_url,
            crm_url=crm_url,
        ):
            await websocket.send_text(chunk)

        flush_traces()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        await websocket.send_text(f'{{"type":"error","message":"{str(exc).replace(chr(34), chr(39))}"}}\n')
        await websocket.close(code=1011)
    else:
        await websocket.close()


def main() -> None:
    import os
    import uvicorn

    parser = argparse.ArgumentParser(description="Ghost Churn OpenUI WebSocket server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8765")))
    args = parser.parse_args()

    print(f"OpenUI WebSocket: ws://{args.host}:{args.port}/ws/ui?fixture=acme&state=4")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
