"""Local web surface for The Board Market."""

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from profiles.paper_pilot import get_pilot, reconcile_pilot, reset_pilot, start_pilot


ROOT = Path(__file__).resolve().parent
BOARD_SNAPSHOT = ROOT / "data" / "board_today.json"

app = FastAPI(title="The Board Market", version="0.1.0")
app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")
app.mount("/data", StaticFiles(directory=ROOT / "data"), name="data")


class PaperPilotStart(BaseModel):
    bankroll: float = Field(default=100.0, ge=10, le=1000)


@app.get("/api/board/today")
def board_today() -> dict:
    if not BOARD_SNAPSHOT.exists():
        raise HTTPException(status_code=503, detail="Board snapshot has not been generated")
    return json.loads(BOARD_SNAPSHOT.read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "snapshot_ready": BOARD_SNAPSHOT.exists()}


@app.get("/api/connections/status")
def connection_status() -> dict:
    required = ("SCHWAB_APP_KEY", "SCHWAB_APP_SECRET", "SCHWAB_REDIRECT_URI", "BOARD_MARKET_KEY")
    missing = [name for name in required if not os.environ.get(name)]
    return {
        "schwab": {
            "connector_available": True,
            "configured": not missing,
            "authorized": False,
            "mode": "read_only",
            "order_routing": False,
            "missing_configuration": missing,
        },
        "fidelity": {"mode": "manual_csv", "order_routing": False},
        "robinhood": {"connector_available": False, "order_routing": False},
    }


@app.get("/api/paper-pilot")
def paper_pilot_status() -> dict:
    return get_pilot()


@app.post("/api/paper-pilot/start")
def paper_pilot_start(payload: PaperPilotStart) -> dict:
    try:
        return start_pilot(payload.bankroll)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/paper-pilot/reconcile")
def paper_pilot_reconcile() -> dict:
    try:
        return reconcile_pilot()
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/paper-pilot")
def paper_pilot_reset() -> dict:
    return reset_pilot()


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(ROOT / "index.html")
