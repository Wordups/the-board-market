"""
The Board Market — Database

SQLite connection management and migration runner.
Phase 3. Plain stdlib sqlite3 — no ORM. Simple, debuggable, fast enough.
"""

import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).parent.parent / "data" / "board_market.db"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def get_connection() -> sqlite3.Connection:
    """Get a connection with sensible defaults."""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_cursor():
    """Context manager for transactional cursor operations."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_migrations() -> None:
    """Run all .sql migrations in order. Idempotent."""
    if not MIGRATIONS_DIR.exists():
        print(f"No migrations directory at {MIGRATIONS_DIR}")
        return

    migrations = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migrations:
        print("No migrations found")
        return

    with db_cursor() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        applied = {row["filename"] for row in c.execute(
            "SELECT filename FROM schema_migrations"
        ).fetchall()}

        for mig in migrations:
            if mig.name in applied:
                print(f"  ⏭️  {mig.name} already applied")
                continue

            print(f"  ▶️  Applying {mig.name}...")
            sql = mig.read_text()
            c.executescript(sql)
            c.execute(
                "INSERT INTO schema_migrations (filename) VALUES (?)",
                (mig.name,)
            )
            print(f"  ✅ {mig.name} applied")


def reset_db(confirm: bool = False) -> None:
    """Nuke the DB. Requires explicit confirm. Phase 3 dev only."""
    if not confirm:
        raise ValueError("reset_db requires confirm=True")
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"  🗑️  Deleted {DB_PATH}")
    run_migrations()


if __name__ == "__main__":
    import sys
    if "--reset" in sys.argv:
        reset_db(confirm=True)
    else:
        run_migrations()
    print(f"\n✅ Database ready at {DB_PATH}")
