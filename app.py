"""Local web surface for The Board Market.

This is the PRIVATE backend. It is never part of the public GitHub Pages
artifact (which is static and sets BOARD_PUBLIC_STATIC=true). Schwab OAuth,
tokens, balances, and live order routing live here only.
"""

import json
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from profiles.paper_pilot import get_pilot, reconcile_pilot, reset_pilot, start_pilot
from profiles import live_pilot
from connectors import schwab


ROOT = Path(__file__).resolve().parent
BOARD_SNAPSHOT = ROOT / "data" / "board_today.json"

# Loose CSRF state for the local single-user OAuth flow.
_OAUTH_STATES: set[str] = set()

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
    authorized = schwab.load_tokens() is not None
    live_enabled = schwab.live_trading_enabled()
    return {
        "schwab": {
            "connector_available": True,
            "configured": not missing,
            "authorized": authorized,
            "mode": "live" if (authorized and live_enabled) else "read_only",
            "order_routing": authorized and live_enabled and bool(live_pilot.account_hash()),
            "missing_configuration": missing,
        },
        "fidelity": {"mode": "manual_csv", "order_routing": False},
        "robinhood": {"connector_available": False, "order_routing": False},
    }


# ─────────────────────────── Schwab OAuth (you log in) ───────────────────────────

@app.get("/api/schwab/login", include_in_schema=False)
def schwab_login() -> RedirectResponse:
    """Redirect the browser to Schwab's consent page. Trading scope so the
    account can route orders once LIVE_TRADING_ENABLED is set."""
    try:
        state = secrets.token_urlsafe(24)
        _OAUTH_STATES.add(state)
        return RedirectResponse(schwab.build_authorize_url(state, scope="trade"))
    except schwab.SchwabConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/callback", include_in_schema=False)
def schwab_callback(code: str = "", state: str = "") -> RedirectResponse:
    """Schwab redirects here with ?code. Exchange it and store tokens (encrypted)."""
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")
    _OAUTH_STATES.discard(state)  # loose single-user check
    try:
        tokens = schwab.exchange_code_for_tokens(code)
        schwab.save_tokens(tokens)
    except (schwab.SchwabAuthError, schwab.SchwabConfigError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse("/?schwab=connected")


# ─────────────────────────── Live pilot (real $) ───────────────────────────

class LiveRun(BaseModel):
    dry_run: bool = False


@app.get("/api/live")
def live_status() -> dict:
    return live_pilot.live_status()


@app.post("/api/live/run")
def live_run(payload: LiveRun) -> dict:
    try:
        return live_pilot.run_live_cycle(dry_run=payload.dry_run)
    except (RuntimeError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/live")
def live_reset() -> dict:
    return live_pilot.reset_live()


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
