import os
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from app import connection_status
from connectors.schwab import build_authorize_url


REQUIRED_ENV = {
    "SCHWAB_APP_KEY": "test-key",
    "SCHWAB_APP_SECRET": "test-secret",
    "SCHWAB_REDIRECT_URI": "https://localhost:8080/callback",
    "BOARD_MARKET_KEY": "test-fernet-key",
}


class ConnectionStatusTests(unittest.TestCase):
    def test_schwab_reports_missing_configuration_without_exposing_values(self):
        with patch.dict(os.environ, {}, clear=True):
            status = connection_status()["schwab"]

        self.assertFalse(status["configured"])
        self.assertFalse(status["authorized"])
        self.assertFalse(status["order_routing"])
        self.assertEqual(set(REQUIRED_ENV), set(status["missing_configuration"]))
        self.assertNotIn("test-secret", str(status))

    def test_schwab_reports_ready_to_authorize_when_environment_is_complete(self):
        with patch.dict(os.environ, REQUIRED_ENV, clear=True):
            status = connection_status()["schwab"]
            authorize_url = build_authorize_url("csrf-test")

        query = parse_qs(urlparse(authorize_url).query)
        self.assertTrue(status["configured"])
        self.assertFalse(status["authorized"])
        self.assertEqual("read_only", status["mode"])
        self.assertEqual(["readonly"], query["scope"])
        self.assertEqual(["csrf-test"], query["state"])


if __name__ == "__main__":
    unittest.main()
