"""
The Board Market — Schwab Trader API Client

Phase 5 connector. READ-ONLY in Phase 5. No order placement until Phase 6.

Implements OAuth 2.0 flow with 30-min access tokens and 7-day refresh tokens.
See docs/CONNECTORS.md for the full spec.

ENVIRONMENT VARIABLES REQUIRED:
  SCHWAB_APP_KEY        — from developer.schwab.com
  SCHWAB_APP_SECRET     — from developer.schwab.com
  SCHWAB_REDIRECT_URI   — your registered callback URL
  BOARD_MARKET_KEY      — Fernet key for token encryption
"""

import os
import base64
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional

try:
    import httpx
    from cryptography.fernet import Fernet
except ImportError:
    httpx = None
    Fernet = None


SCHWAB_BASE_URL = "https://api.schwabapi.com"
SCHWAB_AUTH_URL = f"{SCHWAB_BASE_URL}/v1/oauth/authorize"
SCHWAB_TOKEN_URL = f"{SCHWAB_BASE_URL}/v1/oauth/token"
SCHWAB_TRADER_URL = f"{SCHWAB_BASE_URL}/trader/v1"
SCHWAB_MARKET_URL = f"{SCHWAB_BASE_URL}/marketdata/v1"


class SchwabConfigError(Exception):
    """Missing env vars or config."""


class SchwabAuthError(Exception):
    """OAuth flow failure."""


def _config() -> dict:
    """Load and validate config from env vars."""
    required = ("SCHWAB_APP_KEY", "SCHWAB_APP_SECRET", "SCHWAB_REDIRECT_URI", "BOARD_MARKET_KEY")
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        raise SchwabConfigError(f"Missing env vars: {missing}")
    return {v: os.environ[v] for v in required}


def _fernet() -> "Fernet":
    if Fernet is None:
        raise RuntimeError("pip install cryptography")
    return Fernet(os.environ["BOARD_MARKET_KEY"].encode())


def encrypt_token(token: str) -> str:
    """Encrypt a token for DB storage."""
    return _fernet().encrypt(token.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    """Decrypt a stored token."""
    return _fernet().decrypt(encrypted.encode()).decode()


def build_authorize_url(state: str, scope: str = "readonly") -> str:
    """
    Build the URL to redirect the user to for Schwab authorization.
    `state` should be a random per-session value for CSRF protection.

    scope="readonly" for the Phase 5 read-only path; pass scope="trade" (and a
    Schwab app approved for Accounts & Trading) to enable order placement. Real
    order routing is still gated by LIVE_TRADING_ENABLED + the $100 capital cap.
    """
    cfg = _config()
    params = {
        "client_id": cfg["SCHWAB_APP_KEY"],
        "redirect_uri": cfg["SCHWAB_REDIRECT_URI"],
        "response_type": "code",
        "scope": scope,
        "state": state,
    }
    return f"{SCHWAB_AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_tokens(auth_code: str) -> dict:
    """
    Exchange authorization code for access + refresh tokens.
    Called on OAuth callback.

    Returns:
        {
            "access_token": str,
            "refresh_token": str,
            "expires_at": datetime,
            "token_type": "Bearer"
        }
    """
    if httpx is None:
        raise RuntimeError("pip install httpx")

    cfg = _config()
    basic = base64.b64encode(
        f"{cfg['SCHWAB_APP_KEY']}:{cfg['SCHWAB_APP_SECRET']}".encode()
    ).decode()

    response = httpx.post(
        SCHWAB_TOKEN_URL,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": cfg["SCHWAB_REDIRECT_URI"],
        },
    )

    if response.status_code != 200:
        raise SchwabAuthError(f"Token exchange failed: {response.status_code} {response.text}")

    data = response.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at": datetime.utcnow() + timedelta(seconds=data["expires_in"]),
        "token_type": data.get("token_type", "Bearer"),
    }


def refresh_access_token(refresh_token: str) -> dict:
    """
    Refresh an expired access token. Refresh tokens last 7 days.
    Called automatically by sync jobs when access_token is near expiry.
    """
    if httpx is None:
        raise RuntimeError("pip install httpx")

    cfg = _config()
    basic = base64.b64encode(
        f"{cfg['SCHWAB_APP_KEY']}:{cfg['SCHWAB_APP_SECRET']}".encode()
    ).decode()

    response = httpx.post(
        SCHWAB_TOKEN_URL,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )

    if response.status_code != 200:
        raise SchwabAuthError(f"Refresh failed: {response.status_code} — user must reauthenticate")

    data = response.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", refresh_token),
        "expires_at": datetime.utcnow() + timedelta(seconds=data["expires_in"]),
    }


# ─────────────────────────── Read-only API methods ───────────────────────────

class SchwabClient:
    """Read-only client. Order placement explicitly NOT implemented in Phase 5."""

    def __init__(self, access_token: str):
        if httpx is None:
            raise RuntimeError("pip install httpx")
        self.access_token = access_token
        self.client = httpx.Client(
            base_url=SCHWAB_TRADER_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0,
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def get_accounts(self) -> list[dict]:
        """List all accounts the user has at Schwab."""
        r = self.client.get("/accounts")
        r.raise_for_status()
        return r.json()

    def get_positions(self, account_hash: str) -> list[dict]:
        """Positions for a specific account."""
        r = self.client.get(f"/accounts/{account_hash}?fields=positions")
        r.raise_for_status()
        data = r.json()
        return data.get("securitiesAccount", {}).get("positions", [])

    def get_transactions(
        self,
        account_hash: str,
        start_date: datetime,
        end_date: Optional[datetime] = None,
    ) -> list[dict]:
        """Transactions in date range."""
        end_date = end_date or datetime.utcnow()
        params = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
        }
        r = self.client.get(f"/accounts/{account_hash}/transactions", params=params)
        r.raise_for_status()
        return r.json()

    def get_quote(self, ticker: str) -> dict:
        """Real-time quote (requires market data subscription)."""
        r = httpx.get(
            f"{SCHWAB_MARKET_URL}/{ticker}/quotes",
            headers={"Authorization": f"Bearer {self.access_token}"},
            timeout=15.0,
        )
        r.raise_for_status()
        return r.json()

    # ─────────────────────────── Order placement ───────────────────────────
    # Live order routing. Every entry point that can spend real money checks
    # LIVE_TRADING_ENABLED first (belt-and-suspenders; the live engine also caps
    # total deployment at LIVE_CAPITAL_CAP). Default OFF.

    def place_order(self, account_hash: str, order: dict) -> dict:
        """POST a Schwab order. Returns {order_id, status}. Hard-gated."""
        if not live_trading_enabled():
            raise SchwabAuthError(
                "Live trading is disabled. Set LIVE_TRADING_ENABLED=true to route real orders."
            )
        r = self.client.post(f"/accounts/{account_hash}/orders", json=order)
        r.raise_for_status()
        # Schwab returns the new order id in the Location header (no body on 201).
        location = r.headers.get("location", "")
        order_id = location.rstrip("/").split("/")[-1] if location else None
        return {"order_id": order_id, "status": r.status_code}

    def get_order(self, account_hash: str, order_id: str) -> dict:
        r = self.client.get(f"/accounts/{account_hash}/orders/{order_id}")
        r.raise_for_status()
        return r.json()

    def cancel_order(self, account_hash: str, order_id: str) -> int:
        r = self.client.delete(f"/accounts/{account_hash}/orders/{order_id}")
        r.raise_for_status()
        return r.status_code


def live_trading_enabled() -> bool:
    """Master kill switch. Real orders are impossible unless this is truthy."""
    return os.environ.get("LIVE_TRADING_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def build_equity_market_order(ticker: str, quantity: int, instruction: str) -> dict:
    """A simple equities market order. instruction = 'BUY' or 'SELL'."""
    return {
        "orderType": "MARKET",
        "session": "NORMAL",
        "duration": "DAY",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [
            {
                "instruction": instruction.upper(),
                "quantity": quantity,
                "instrument": {"symbol": ticker.upper(), "assetType": "EQUITY"},
            }
        ],
    }


def build_stop_loss_order(ticker: str, quantity: int, stop_price: float) -> dict:
    """A protective sell-stop for an open long. Rounds stop to 2dp."""
    return {
        "orderType": "STOP",
        "session": "NORMAL",
        "duration": "GOOD_TILL_CANCEL",
        "stopPrice": round(stop_price, 2),
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [
            {
                "instruction": "SELL",
                "quantity": quantity,
                "instrument": {"symbol": ticker.upper(), "assetType": "EQUITY"},
            }
        ],
    }


# ───────────────────────── Token persistence (.state) ─────────────────────────
# Encrypted at rest with BOARD_MARKET_KEY (Fernet). Stored under .state/ which is
# gitignored, so refresh tokens never touch the repo.

def _token_path():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    state = root / ".state"
    state.mkdir(exist_ok=True)
    return state / "schwab_tokens.json"


def save_tokens(tokens: dict) -> None:
    """Persist access+refresh tokens encrypted. `tokens` from exchange/refresh."""
    import json

    payload = {
        "access_token": encrypt_token(tokens["access_token"]),
        "refresh_token": encrypt_token(tokens["refresh_token"]),
        "expires_at": tokens["expires_at"].isoformat()
        if hasattr(tokens["expires_at"], "isoformat")
        else tokens["expires_at"],
    }
    _token_path().write_text(json.dumps(payload), encoding="utf-8")


def load_tokens() -> Optional[dict]:
    """Load + decrypt tokens, refreshing the access token if expired. None if absent."""
    import json

    path = _token_path()
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    access = decrypt_token(raw["access_token"])
    refresh = decrypt_token(raw["refresh_token"])
    expires_at = datetime.fromisoformat(raw["expires_at"])
    if datetime.utcnow() >= expires_at - timedelta(minutes=2):
        refreshed = refresh_access_token(refresh)
        save_tokens(refreshed)
        return {"access_token": refreshed["access_token"], "refresh_token": refreshed["refresh_token"]}
    return {"access_token": access, "refresh_token": refresh}
