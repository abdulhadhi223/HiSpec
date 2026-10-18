
import argparse
import os
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    required = [
        "NEC_DB_HOST",
        "NEC_DB_PORT",
        "NEC_DB_NAME",
        "NEC_APP_USER",
        "NEC_APP_PASS",
    ]

    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise RuntimeError(
            "Missing NEC configuration: " + ", ".join(missing)
        )

    if os.environ["NEC_DB_NAME"] != "nmdb_nec":
        raise RuntimeError("NEC database must be nmdb_nec")

    url = URL.create(
        drivername="postgresql+psycopg2",
        username=os.environ["NEC_APP_USER"],
        password=os.environ["NEC_APP_PASS"],
        host=os.environ["NEC_DB_HOST"],
        port=int(os.environ["NEC_DB_PORT"]),
        database=os.environ["NEC_DB_NAME"],
    )

    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10},
    )

    try:
        with engine.connect() as connection:
            database = connection.execute(
                text("SELECT current_database()")
            ).scalar_one()

            schema = connection.execute(
                text("SELECT current_schema()")
            ).scalar_one()

            if database != "nmdb_nec" or schema != "public":
                raise RuntimeError(
                    f"Unexpected database target: {database}.{schema}"
                )

            print(f"NEC database verified: {database}.{schema}", flush=True)
    finally:
        engine.dispose()

    if args.check_only:
        print("NEC preflight successful", flush=True)
        return

    # Set both variables before Alembic imports project models.
    database_url = url.render_as_string(hide_password=False)
    os.environ["DATABASE_URL"] = database_url
    os.environ["NEC_MIGRATION_DATABASE_URL"] = database_url
    os.environ["NEC_SCHEMA"] = "public"
    os.environ["APP_MODE"] = "nec"

    config = Config("alembic.nec.ini")

    print("Starting NEC Alembic migration", flush=True)
    command.upgrade(config, "head")
    print("NEC Alembic migration completed", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"NEC migration failed: {exc}", file=sys.stderr)
        sys.exit(1)




stage('Migrate NEC Database') {
    when {
        expression {
            return params.IMAGE_TAG?.trim() &&
                   params.DEPLOY_TARGET == 'nec'
        }
    }

    steps {
        withCredentials([
            usernamePassword(
                credentialsId: 'nec-db-app',
                usernameVariable: 'NEC_APP_USER',
                passwordVariable: 'NEC_APP_PASS'
            )
        ]) {
            sh '''#!/usr/bin/env bash
set -euo pipefail
set +x

echo "=== Starting NEC database migration ==="

: "${NEC_DB_HOST:?Missing NEC_DB_HOST}"
: "${NEC_DB_PORT:?Missing NEC_DB_PORT}"
: "${NEC_DB_NAME:?Missing NEC_DB_NAME}"
: "${NEC_APP_USER:?Missing NEC_APP_USER}"
: "${NEC_APP_PASS:?Missing NEC_APP_PASS}"

test -f alembic.nec.ini
test -f alembic_nec/env.py
test -f scripts/run_nec_migration.py
test -d alembic_nec/versions

# Reuse existing Jenkins Python environment.
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
fi

PYTHON=".venv/bin/python"

# Confirm required packages are available.
if ! "$PYTHON" -c \
    "import alembic, sqlalchemy, psycopg2" ; then
    "$PYTHON" -m pip install \
        --no-index \
        --find-links=wheels \
        -r requirements.txt

    "$PYTHON" -m pip install \
        --no-index \
        --find-links=wheels \
        psycopg2-binary
fi

# Make project environment available before imports.
export APP_MODE="nec"
export APP_ENVIRONMENT="nec"
export NEC_SCHEMA="public"

# Syntax validation before opening the database.
"$PYTHON" -m py_compile \
    scripts/run_nec_migration.py \
    alembic_nec/env.py

# Run NEC migration exactly once.
"$PYTHON" scripts/run_nec_migration.py

echo "=== NEC database migration completed ==="
'''
        }
    }
}
