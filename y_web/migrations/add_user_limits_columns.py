"""
Database migration to add per-user configurator limits to admin_users.
"""

import os
import sqlite3

try:
    import psycopg2

    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False


def migrate_sqlite(db_path):
    """Add max_agents_per_population and max_clients_per_experiment columns."""
    if not os.path.exists(db_path):
        print(f"Database file not found: {db_path}")
        return False

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(admin_users)")
        columns = [row[1] for row in cursor.fetchall()]

        if "max_agents_per_population" not in columns:
            cursor.execute(
                "ALTER TABLE admin_users ADD COLUMN max_agents_per_population INTEGER DEFAULT 1000"
            )
            print("✓ Added max_agents_per_population column to SQLite database")
        else:
            print("○ max_agents_per_population column already exists in SQLite database")

        if "max_clients_per_experiment" not in columns:
            cursor.execute(
                "ALTER TABLE admin_users ADD COLUMN max_clients_per_experiment INTEGER DEFAULT 1"
            )
            print("✓ Added max_clients_per_experiment column to SQLite database")
        else:
            print("○ max_clients_per_experiment column already exists in SQLite database")

        cursor.execute(
            """
            UPDATE admin_users
            SET max_agents_per_population = 1000
            WHERE max_agents_per_population IS NULL OR max_agents_per_population < 1
            """
        )
        cursor.execute(
            """
            UPDATE admin_users
            SET max_clients_per_experiment = 1
            WHERE max_clients_per_experiment IS NULL OR max_clients_per_experiment < 1
            """
        )

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"✗ Error migrating SQLite database: {e}")
        return False


def migrate_postgresql(host, port, database, user, password):
    """Add max_agents_per_population and max_clients_per_experiment columns."""
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

        if "max_agents_per_population" not in columns:
            cursor.execute(
                """
                ALTER TABLE admin_users
                ADD COLUMN max_agents_per_population INTEGER DEFAULT 1000
                """
            )
            print("✓ Added max_agents_per_population column to PostgreSQL database")
        else:
            print("○ max_agents_per_population column already exists in PostgreSQL database")

        if "max_clients_per_experiment" not in columns:
            cursor.execute(
                """
                ALTER TABLE admin_users
                ADD COLUMN max_clients_per_experiment INTEGER DEFAULT 1
                """
            )
            print("✓ Added max_clients_per_experiment column to PostgreSQL database")
        else:
            print("○ max_clients_per_experiment column already exists in PostgreSQL database")

        cursor.execute(
            """
            UPDATE admin_users
            SET max_agents_per_population = 1000
            WHERE max_agents_per_population IS NULL OR max_agents_per_population < 1
            """
        )
        cursor.execute(
            """
            UPDATE admin_users
            SET max_clients_per_experiment = 1
            WHERE max_clients_per_experiment IS NULL OR max_clients_per_experiment < 1
            """
        )

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"✗ Error migrating PostgreSQL database: {e}")
        return False
