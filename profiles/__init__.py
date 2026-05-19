"""The Board Market — Profile subsystem.

Auth, ledger, performance tracking. SQLite-backed.
"""

from .db import get_connection, db_cursor, run_migrations
from .auth import register, login, get_user, is_registration_open
from .ledger import create_play, close_play, get_play, list_plays, cancel_play
from .performance import performance_summary, equity_curve, max_drawdown

__all__ = [
    "get_connection", "db_cursor", "run_migrations",
    "register", "login", "get_user", "is_registration_open",
    "create_play", "close_play", "get_play", "list_plays", "cancel_play",
    "performance_summary", "equity_curve", "max_drawdown",
]
