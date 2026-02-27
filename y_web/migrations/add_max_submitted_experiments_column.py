"""
Database migration to add max_submitted_experiments to admin_users.
"""

import os
import sqlite3

try:
    import psycopg2

    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False


def migrate_sqlite(db_path):
    """Add max_submitted_experiments to SQLite admin_users table."""
    if not os.path.exists(db_path):
        print(f"Database file not found: {db_path}")
        return False

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(admin_users)")
        columns = [row[1] for row in cursor.fetchall()]

        if "max_submitted_experiments" not in columns:
            cursor.execute(
                "ALTER TABLE admin_users ADD COLUMN max_submitted_experiments INTEGER DEFAULT 3"
            )
            cursor.execute(
                """
                UPDATE admin_users
                SET max_submitted_experiments = 3
                WHERE max_submitted_experiments IS NULL
                """
            )
            print("✓ Added max_submitted_experiments column to SQLite database")
        else:
            cursor.execute(
                """
                UPDATE admin_users
                SET max_submitted_experiments = 3
                WHERE max_submitted_experiments IS NULL
                """
            )
            print(
                "○ max_submitted_experiments column already exists in SQLite database"
            )

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"✗ Error migrating SQLite database: {e}")
        return False


def migrate_postgresql(host, port, database, user, password):
    """Add max_submitted_experiments to PostgreSQL admin_users table."""
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

        if "max_submitted_experiments" not in columns:
            cursor.execute(
                """
                ALTER TABLE admin_users
                ADD COLUMN max_submitted_experiments INTEGER DEFAULT 3
                """
            )
            print("✓ Added max_submitted_experiments column to PostgreSQL database")
        else:
            print(
                "○ max_submitted_experiments column already exists in PostgreSQL database"
            )

        cursor.execute(
            """
            UPDATE admin_users
            SET max_submitted_experiments = 3
            WHERE max_submitted_experiments IS NULL
            """
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"✗ Error migrating PostgreSQL database: {e}")
        return False
