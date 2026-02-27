"""
Create experiment_notifications table for per-user submission/completion alerts.
"""

import os
import sqlite3

try:
    import psycopg2

    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False


def migrate_sqlite(db_path):
    """Create experiment_notifications table in SQLite if missing."""
    if not os.path.exists(db_path):
        print(f"Database file not found: {db_path}")
        return False

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='experiment_notifications'
            """
        )
        if cursor.fetchone():
            print("○ experiment_notifications table already exists in SQLite database")
            conn.close()
            return True

        cursor.execute(
            """
            CREATE TABLE experiment_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient_username TEXT NOT NULL,
                exp_id INTEGER NOT NULL,
                notification_type TEXT NOT NULL,
                message TEXT NOT NULL,
                is_read INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (exp_id) REFERENCES exps(idexp)
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX idx_experiment_notifications_recipient
            ON experiment_notifications(recipient_username)
            """
        )
        conn.commit()
        conn.close()
        print("✓ Created experiment_notifications table in SQLite database")
        return True
    except Exception as e:
        print(f"✗ Error migrating SQLite database: {e}")
        return False


def migrate_postgresql(host, port, database, user, password):
    """Create experiment_notifications table in PostgreSQL if missing."""
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
            SELECT to_regclass('public.experiment_notifications')
            """
        )
        table_exists = cursor.fetchone()[0] is not None

        if table_exists:
            print(
                "○ experiment_notifications table already exists in PostgreSQL database"
            )
            conn.close()
            return True

        cursor.execute(
            """
            CREATE TABLE experiment_notifications (
                id SERIAL PRIMARY KEY,
                recipient_username VARCHAR(50) NOT NULL,
                exp_id INTEGER NOT NULL REFERENCES exps(idexp),
                notification_type VARCHAR(20) NOT NULL,
                message VARCHAR(500) NOT NULL,
                is_read BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX idx_experiment_notifications_recipient
            ON experiment_notifications(recipient_username)
            """
        )
        conn.commit()
        conn.close()
        print("✓ Created experiment_notifications table in PostgreSQL database")
        return True
    except Exception as e:
        print(f"✗ Error migrating PostgreSQL database: {e}")
        return False
