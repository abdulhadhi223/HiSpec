
import argparse
import os
import re
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


SCHEMA_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def verify_schema(schema: str) -> None:
    if not SCHEMA_PATTERN.fullmatch(schema):
        raise ValueError(f"Invalid schema identifier: {schema!r}")

    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is missing")

    # Same URL that the existing main Alembic env.py consumes.
    url = make_url(database_url)

    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 15},
    )

    try:
        with engine.connect() as connection:
            result = connection.execute(
                text("""
                    SELECT
                        current_database(),
                        current_user,
                        current_schema(),
                        current_setting('search_path'),
                        EXISTS (
                            SELECT 1
                            FROM pg_namespace
                            WHERE nspname = :schema
                        ),
                        has_schema_privilege(
                            current_user, :schema, 'USAGE'
                        ),
                        has_schema_privilege(
                            current_user, :schema, 'CREATE'
                        )
                """),
                {"schema": schema},
            ).one()

            (
                database_name,
                database_user,
                active_schema,
                search_path,
                schema_exists,
                has_usage,
                has_create,
            ) = result

            print("=== NMDB Schema Verification ===", flush=True)
            print(f"Database       : {database_name}", flush=True)
            print(f"Database user  : {database_user}", flush=True)
            print(f"Expected schema: {schema}", flush=True)
            print(f"Active schema  : {active_schema}", flush=True)
            print(f"Search path    : {search_path}", flush=True)
            print(f"Schema exists  : {schema_exists}", flush=True)
            print(f"USAGE privilege: {has_usage}", flush=True)
            print(f"CREATE privilege: {has_create}", flush=True)

            errors = []

            if not schema_exists:
                errors.append(f"Schema {schema!r} does not exist")

            if active_schema != schema:
                errors.append(
                    f"Expected active schema {schema!r}, "
                    f"but PostgreSQL selected {active_schema!r}"
                )

            if not has_usage:
                errors.append("Application user lacks USAGE permission")

            if not has_create:
                errors.append("Application user lacks CREATE permission")

            if errors:
                raise RuntimeError("; ".join(errors))

            print("Schema verification PASSED", flush=True)

    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify NMDB deployment PostgreSQL schema"
    )
    parser.add_argument(
        "--schema",
        required=True,
        help="Expected NMDB deployment schema",
    )

    args = parser.parse_args()

    try:
        verify_schema(args.schema)
        return 0
    except Exception as exc:
        print(f"Schema verification FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
