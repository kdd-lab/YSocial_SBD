"""
Database migration script to add remote experiment fields to exps table.

This script adds:
- is_remote: Integer column (default 0, where 0=local, 1=remote)
- remote_host: String column (default NULL, stores remote host address)
- remote_port: Integer column (default NULL, stores remote port)

Run this script to update existing YSocial installations.
"""

import os
import sqlite3
import sys

try:
    import psycopg2

    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False


def migrate_sqlite(db_path):
    """
    Add remote experiment fields to SQLite database.

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

        # Check if columns already exist
        cursor.execute("PRAGMA table_info(exps)")
        columns = [row[1] for row in cursor.fetchall()]

        # Add is_remote column if it doesn't exist
        if "is_remote" not in columns:
            cursor.execute(
                "ALTER TABLE exps ADD COLUMN is_remote INTEGER DEFAULT 0"
            )
            print("✓ Added is_remote column to SQLite database")
        else:
            print("○ is_remote column already exists in SQLite database")

        # Add remote_host column if it doesn't exist
        if "remote_host" not in columns:
            cursor.execute(
                "ALTER TABLE exps ADD COLUMN remote_host TEXT DEFAULT NULL"
            )
            print("✓ Added remote_host column to SQLite database")
        else:
            print("○ remote_host column already exists in SQLite database")

        # Add remote_port column if it doesn't exist
        if "remote_port" not in columns:
            cursor.execute(
                "ALTER TABLE exps ADD COLUMN remote_port INTEGER DEFAULT NULL"
            )
            print("✓ Added remote_port column to SQLite database")
        else:
            print("○ remote_port column already exists in SQLite database")

        conn.commit()
        conn.close()
        return True

    except Exception as e:
        print(f"✗ Error migrating SQLite database: {e}")
        return False


def migrate_postgresql(host, port, database, user, password):
    """
    Add remote experiment fields to PostgreSQL database.

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

        # Check if columns already exist
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND LOWER(table_name) = 'exps'
        """)
        columns = [row[0] for row in cursor.fetchall()]

        # Add is_remote column if it doesn't exist
        if "is_remote" not in columns:
            cursor.execute("""
                ALTER TABLE exps 
                ADD COLUMN is_remote INTEGER DEFAULT 0
            """)
            print("✓ Added is_remote column to PostgreSQL database")
        else:
            print("○ is_remote column already exists in PostgreSQL database")

        # Add remote_host column if it doesn't exist
        if "remote_host" not in columns:
            cursor.execute("""
                ALTER TABLE exps 
                ADD COLUMN remote_host VARCHAR(255) DEFAULT NULL
            """)
            print("✓ Added remote_host column to PostgreSQL database")
        else:
            print("○ remote_host column already exists in PostgreSQL database")

        # Add remote_port column if it doesn't exist
        if "remote_port" not in columns:
            cursor.execute("""
                ALTER TABLE exps 
                ADD COLUMN remote_port INTEGER DEFAULT NULL
            """)
            print("✓ Added remote_port column to PostgreSQL database")
        else:
            print("○ remote_port column already exists in PostgreSQL database")

        conn.commit()
        conn.close()
        return True

    except Exception as e:
        print(f"✗ Error migrating PostgreSQL database: {e}")
        return False


def main():
    """Run migration for both SQLite and PostgreSQL databases."""
    print("YSocial Database Migration: Adding Remote Experiment Fields")
    print("=" * 60)
    print()

    # Migrate SQLite database
    print("Migrating SQLite databases...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(script_dir))

    # List of possible SQLite database locations
    db_paths = [
        os.path.join(project_root, "data_schema", "database_dashboard.db"),
        os.path.join(project_root, "y_web", "db", "dashboard.db"),
        os.path.join(project_root, "db", "dashboard.db"),
    ]

    sqlite_success = True
    migrated_count = 0
    for db_path in db_paths:
        if os.path.exists(db_path):
            print(f"  Found database: {db_path}")
            if migrate_sqlite(db_path):
                migrated_count += 1
            else:
                sqlite_success = False
        else:
            print(f"  Skipping (not found): {db_path}")

    if migrated_count == 0:
        print("  ✗ No SQLite databases found to migrate")
        sqlite_success = False
    else:
        print(f"  ✓ Successfully migrated {migrated_count} database(s)")

    print()

    # Migrate PostgreSQL database (if configured)
    print("Migrating PostgreSQL database...")

    # Try to read PostgreSQL configuration from environment variables
    pg_host = os.environ.get("POSTGRES_HOST", "localhost")
    pg_port = os.environ.get("POSTGRES_PORT", "5432")
    pg_database = os.environ.get("POSTGRES_DB", "ysocial")
    pg_user = os.environ.get("POSTGRES_USER", "postgres")
    pg_password = os.environ.get("POSTGRES_PASSWORD", "")

    if pg_password:
        postgresql_success = migrate_postgresql(
            pg_host, pg_port, pg_database, pg_user, pg_password
        )
    else:
        print("○ PostgreSQL not configured (no password found in environment)")
        print("  To migrate PostgreSQL, set the following environment variables:")
        print("  - POSTGRES_HOST (default: localhost)")
        print("  - POSTGRES_PORT (default: 5432)")
        print("  - POSTGRES_DB (default: ysocial)")
        print("  - POSTGRES_USER (default: postgres)")
        print("  - POSTGRES_PASSWORD (required)")
        postgresql_success = None

    print()
    print("=" * 60)
    print("Migration Summary:")
    print(f"  SQLite:     {'✓ Success' if sqlite_success else '✗ Failed'}")
    if postgresql_success is not None:
        print(f"  PostgreSQL: {'✓ Success' if postgresql_success else '✗ Failed'}")
    else:
        print("  PostgreSQL: ○ Skipped (not configured)")
    print("=" * 60)

    return 0 if sqlite_success else 1


if __name__ == "__main__":
    sys.exit(main())
