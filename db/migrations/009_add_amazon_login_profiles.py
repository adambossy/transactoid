"""Add amazon_login_profiles table."""

revision = "009"
down_revision = "008"


def upgrade(conn):  # type: ignore[no-untyped-def]
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS amazon_login_profiles (
            profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_key TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            browserbase_context_id TEXT,
            enabled BOOLEAN NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            last_auth_at TIMESTAMP,
            last_auth_status TEXT,
            last_auth_error TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def downgrade(conn):  # type: ignore[no-untyped-def]
    conn.execute("DROP TABLE IF EXISTS amazon_login_profiles")
