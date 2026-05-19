"""
The Board Market — Plaid Client

Phase 5 connector. Read-only balances, holdings, transactions.
Reuses Plaid app credentials from Brian's Poof E Gone / Command Center setup.

ENVIRONMENT VARIABLES REQUIRED:
  PLAID_CLIENT_ID
  PLAID_SECRET
  PLAID_ENV               — 'sandbox' | 'development' | 'production'
  BOARD_MARKET_KEY        — Fernet key for token encryption (shared with schwab.py)
"""

import os
from datetime import date
from typing import Optional

try:
    from plaid.api import plaid_api
    from plaid.model.products import Products
    from plaid.model.country_code import CountryCode
    from plaid.model.link_token_create_request import LinkTokenCreateRequest
    from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
    from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
    from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest
    from plaid.model.investments_transactions_get_request import InvestmentsTransactionsGetRequest
    from plaid.configuration import Configuration
    from plaid.api_client import ApiClient
except ImportError:
    plaid_api = None


PLAID_ENV_HOSTS = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com",
}


def _client() -> "plaid_api.PlaidApi":
    """Build a configured Plaid client."""
    if plaid_api is None:
        raise RuntimeError("pip install plaid-python")

    env = os.environ.get("PLAID_ENV", "sandbox")
    configuration = Configuration(
        host=PLAID_ENV_HOSTS[env],
        api_key={
            "clientId": os.environ["PLAID_CLIENT_ID"],
            "secret": os.environ["PLAID_SECRET"],
        },
    )
    return plaid_api.PlaidApi(ApiClient(configuration))


def create_link_token(user_id: int) -> str:
    """
    Generate a Link token to initialize Plaid Link flow on frontend.
    Brian clicks "Connect Roth via Plaid" → frontend uses this token to open Plaid Link.
    """
    client = _client()
    request = LinkTokenCreateRequest(
        products=[Products("investments")],
        client_name="The Board Market",
        country_codes=[CountryCode("US")],
        language="en",
        user=LinkTokenCreateRequestUser(client_user_id=str(user_id)),
    )
    response = client.link_token_create(request)
    return response["link_token"]


def exchange_public_token(public_token: str) -> str:
    """
    After user completes Plaid Link, frontend sends public_token here.
    Returns access_token (encrypted before DB storage).
    """
    client = _client()
    request = ItemPublicTokenExchangeRequest(public_token=public_token)
    response = client.item_public_token_exchange(request)
    return response["access_token"]


def get_holdings(access_token: str) -> dict:
    """
    Pulls all investment holdings for the linked account.
    Returns {accounts: [...], holdings: [...], securities: [...]}.
    """
    client = _client()
    request = InvestmentsHoldingsGetRequest(access_token=access_token)
    response = client.investments_holdings_get(request)
    return response.to_dict()


def get_investment_transactions(
    access_token: str,
    start_date: date,
    end_date: Optional[date] = None,
) -> dict:
    """Pull investment transactions in date range."""
    end_date = end_date or date.today()
    client = _client()
    request = InvestmentsTransactionsGetRequest(
        access_token=access_token,
        start_date=start_date,
        end_date=end_date,
    )
    response = client.investments_transactions_get(request)
    return response.to_dict()
