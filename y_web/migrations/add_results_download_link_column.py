"""
Database migration script to add results_download_link column to exps table.

This script adds:
- results_download_link: String column (default '')
  Used by admins to provide downloadable results URL when marking experiments completed.
"""

import os
import sqlite3

try:
    import psycopg2

    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False


def migrate_sqlite(db_path):
    """
    Add results_download_link column to SQLite database.

    Args:
        db_path: Path to the SQLite database file

    Returns:
        bool: True if successful, False otherwise
    """
    if not os.path.exists(db_path):
        print(f"Database file not found: {db_path}")
        return False

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(exps)")
        columns = [row[1] for row in cursor.fetchall()]

        if "results_download_link" not in columns:
            cursor.execute(
                "ALTER TABLE exps ADD COLUMN results_download_link TEXT DEFAULT ''"
            )
            print("✓ Added results_download_link column to SQLite database")
        else:
            print("○ results_download_link column already exists in SQLite database")

        conn.commit()
        conn.close()
        return True

    except Exception as e:
        print(f"✗ Error migrating SQLite database: {e}")
        return False


def migrate_postgresql(host, port, database, user, password):
    """
    Add results_download_link column to PostgreSQL database.

    Args:
        host: PostgreSQL server host
        port: PostgreSQL server port
        database: Database name
        user: Database user
        password: Database password

    Returns:
        bool: True if successful, False otherwise
    """
    if not PSYCOPG2_AVAILABLE:
        print("✗ psycopg2 not available. Cannot migrate PostgreSQL database.")
        print("  Install with: pip install psycopg2-binary")
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
            WHERE table_name = 'exps'
            """
        )
        columns = [row[0] for row in cursor.fetchall()]

        if "results_download_link" not in columns:
            cursor.execute(
                """
                ALTER TABLE exps
                ADD COLUMN results_download_link VARCHAR(500) DEFAULT ''
                """
            )
            print("✓ Added results_download_link column to PostgreSQL database")
        else:
            print("○ results_download_link column already exists in PostgreSQL database")

        conn.commit()
        conn.close()
        return True

    except Exception as e:
        print(f"✗ Error migrating PostgreSQL database: {e}")
        return False
