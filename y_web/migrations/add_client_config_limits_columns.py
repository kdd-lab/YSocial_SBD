"""Database migration to add per-user client configuration limit columns."""

import os
import sqlite3

try:
    import psycopg2

    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False


DEFAULT_MAX_CLIENT_DAYS = 30
DEFAULT_MAX_CLIENT_NEW_AGENTS_PCT = 0.05
DEFAULT_MAX_CLIENT_CHURN_PCT = 0.05


def migrate_sqlite(db_path):
    """Add client configuration limit columns to SQLite admin_users table."""
    if not os.path.exists(db_path):
        print(f"Database file not found: {db_path}")
        return False

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(admin_users)")
        columns = [row[1] for row in cursor.fetchall()]

        if "max_client_days" not in columns:
            cursor.execute(
                f"ALTER TABLE admin_users ADD COLUMN max_client_days INTEGER DEFAULT {DEFAULT_MAX_CLIENT_DAYS}"
            )
            print("✓ Added max_client_days column to SQLite database")

        if "max_client_new_agents_pct" not in columns:
            cursor.execute(
                f"ALTER TABLE admin_users ADD COLUMN max_client_new_agents_pct REAL DEFAULT {DEFAULT_MAX_CLIENT_NEW_AGENTS_PCT}"
            )
            print("✓ Added max_client_new_agents_pct column to SQLite database")

        if "max_client_churn_pct" not in columns:
            cursor.execute(
                f"ALTER TABLE admin_users ADD COLUMN max_client_churn_pct REAL DEFAULT {DEFAULT_MAX_CLIENT_CHURN_PCT}"
            )
            print("✓ Added max_client_churn_pct column to SQLite database")

        cursor.execute(
            f"""
            UPDATE admin_users
            SET max_client_days = {DEFAULT_MAX_CLIENT_DAYS}
            WHERE max_client_days IS NULL OR max_client_days < 1
            """
        )
        cursor.execute(
            f"""
            UPDATE admin_users
            SET max_client_new_agents_pct = {DEFAULT_MAX_CLIENT_NEW_AGENTS_PCT}
            WHERE max_client_new_agents_pct IS NULL OR max_client_new_agents_pct < 0 OR max_client_new_agents_pct > 1
            """
        )
        cursor.execute(
            f"""
            UPDATE admin_users
            SET max_client_churn_pct = {DEFAULT_MAX_CLIENT_CHURN_PCT}
            WHERE max_client_churn_pct IS NULL OR max_client_churn_pct < 0 OR max_client_churn_pct > 1
            """
        )

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"✗ Error migrating SQLite database: {e}")
        return False


def migrate_postgresql(host, port, database, user, password):
    """Add client configuration limit columns to PostgreSQL admin_users table."""
    if not PSYCOPG2_AVAILABLE:
        print("✗ psycopg2 not available. Cannot migrate PostgreSQL database.")
        return False

    try:
        conn = psycopg2.connect(
            host=host, port=port, database=database, user=user, password=password
        )
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'admin_users'
            """
        )
        columns = [row[0] for row in cursor.fetchall()]

        if "max_client_days" not in columns:
            cursor.execute(
                f"""
                ALTER TABLE admin_users
                ADD COLUMN max_client_days INTEGER DEFAULT {DEFAULT_MAX_CLIENT_DAYS}
                """
            )
            print("✓ Added max_client_days column to PostgreSQL database")

        if "max_client_new_agents_pct" not in columns:
            cursor.execute(
                f"""
                ALTER TABLE admin_users
                ADD COLUMN max_client_new_agents_pct DOUBLE PRECISION DEFAULT {DEFAULT_MAX_CLIENT_NEW_AGENTS_PCT}
                """
            )
            print("✓ Added max_client_new_agents_pct column to PostgreSQL database")

        if "max_client_churn_pct" not in columns:
            cursor.execute(
                f"""
                ALTER TABLE admin_users
                ADD COLUMN max_client_churn_pct DOUBLE PRECISION DEFAULT {DEFAULT_MAX_CLIENT_CHURN_PCT}
                """
            )
            print("✓ Added max_client_churn_pct column to PostgreSQL database")

        cursor.execute(
            f"""
            UPDATE admin_users
            SET max_client_days = {DEFAULT_MAX_CLIENT_DAYS}
            WHERE max_client_days IS NULL OR max_client_days < 1
            """
        )
        cursor.execute(
            f"""
            UPDATE admin_users
            SET max_client_new_agents_pct = {DEFAULT_MAX_CLIENT_NEW_AGENTS_PCT}
            WHERE max_client_new_agents_pct IS NULL OR max_client_new_agents_pct < 0 OR max_client_new_agents_pct > 1
            """
        )
        cursor.execute(
            f"""
            UPDATE admin_users
            SET max_client_churn_pct = {DEFAULT_MAX_CLIENT_CHURN_PCT}
            WHERE max_client_churn_pct IS NULL OR max_client_churn_pct < 0 OR max_client_churn_pct > 1
            """
        )

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"✗ Error migrating PostgreSQL database: {e}")
        return False
