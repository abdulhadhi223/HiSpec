#!/usr/bin/env python3
"""
Run from pipeline only. Requires DB admin credentials.

Usage:
  python provision_schema.py <schema_name>
  python provision_schema.py <schema_name> --drop-first --yes

Environment variables required:
  DB_ADMIN_URL   - PostgreSQL admin connection URL
  DB_APP_USER    - App user to grant privileges to

Examples:
  python provision_schema.py dev_feature_ew_track
  python provision_schema.py test_feature_ew_track --drop-first --yes
"""
import sys
import os
import re
import psycopg2
from psycopg2 import sql


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

SAFE_IDENTIFIER = re.compile(r'^[a-zA-Z0-9_]{1,63}$')

def validate_identifier(value: str, label: str) -> None:
    """
    Reject anything that doesn't look like a safe PostgreSQL identifier.
    Prevents crafted names from causing issues even with Identifier quoting.
    """
    if not SAFE_IDENTIFIER.match(value):
        print(f"ERROR: {label} '{value}' contains invalid characters.")
        print("Only letters, digits, and underscores are allowed (max 63 chars).")
        sys.exit(1)


def parse_args():
    if len(sys.argv) < 2:
        print("ERROR: Missing required argument <schema_name>")
        print(__doc__)
        sys.exit(1)

    schema     = sys.argv[1]
    drop_first = '--drop-first' in sys.argv
    confirmed  = '--yes' in sys.argv

    if drop_first and not confirmed:
        print(
            f"ERROR: --drop-first requires --yes to confirm intentional data loss.\n"
            f"  Schema to drop: {schema}\n"
            f"  Re-run with: python provision_schema.py {schema} --drop-first --yes"
        )
        sys.exit(1)

    return schema, drop_first


def get_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        print(f"ERROR: Environment variable '{key}' is not set or empty.")
        sys.exit(1)
    return value


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    schema, drop_first = parse_args()

    admin_url = get_env('DB_ADMIN_URL')
    app_user  = get_env('DB_APP_USER')

    # Validate both identifiers before touching the DB
    validate_identifier(schema,   'schema')
    validate_identifier(app_user, 'app_user')

    conn = None
    cur  = None

    try:
        conn = psycopg2.connect(admin_url)
        conn.autocommit = True
        cur = conn.cursor()

        # -- Drop (only when explicitly confirmed) --------------------------
        if drop_first:
            cur.execute(
                sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(
                    sql.Identifier(schema)
                )
            )
            print(f"Dropped schema: {schema}")

        # -- Create schema --------------------------------------------------
        cur.execute(
            sql.SQL('CREATE SCHEMA IF NOT EXISTS {}').format(
                sql.Identifier(schema)
            )
        )
        print(f"Created schema: {schema}")

        # -- Schema-level access -------------------------------------------
        cur.execute(
            sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(
                sql.Identifier(schema),
                sql.Identifier(app_user)
            )
        )
        cur.execute(
            sql.SQL('GRANT CREATE ON SCHEMA {} TO {}').format(
                sql.Identifier(schema),
                sql.Identifier(app_user)
            )
        )

        # -- Existing tables (already created by a previous migration run) --
        cur.execute(
            sql.SQL(
                'GRANT SELECT, INSERT, UPDATE, DELETE '
                'ON ALL TABLES IN SCHEMA {} TO {}'
            ).format(
                sql.Identifier(schema),
                sql.Identifier(app_user)
            )
        )

        # -- Existing sequences (needed for SERIAL / gen_random_uuid) -------
        cur.execute(
            sql.SQL(
                'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}'
            ).format(
                sql.Identifier(schema),
                sql.Identifier(app_user)
            )
        )

        # -- Future tables and sequences (created by subsequent migrations) --
        cur.execute(
            sql.SQL(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA {} '
                'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}'
            ).format(
                sql.Identifier(schema),
                sql.Identifier(app_user)
            )
        )
        cur.execute(
            sql.SQL(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA {} '
                'GRANT USAGE, SELECT ON SEQUENCES TO {}'
            ).format(
                sql.Identifier(schema),
                sql.Identifier(app_user)
            )
        )

        print(f"Privileges granted on schema '{schema}' to user '{app_user}'")
        print(f"Schema ready: {schema}")

    except psycopg2.Error as e:
        print(f"ERROR: Database operation failed: {e}")
        sys.exit(1)

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


if __name__ == '__main__':
    main()