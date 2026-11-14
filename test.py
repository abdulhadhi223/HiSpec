set +x
set -euo pipefail
. .venv/bin/activate

# Only allow the build-specific test schema naming convention.
# Reserve four characters for the NEC "_nec" suffix.
if [[ ! "${TEST_SCHEMA:-}" =~ ^test_[a-z0-9_]+_[0-9]+$ ]] || (( ${#TEST_SCHEMA} > 59 )); then
    echo "ERROR: Invalid build-specific test schema"
    exit 1
fi

: "${NEC_TEST_DB:?NEC_TEST_DB must identify the permanent NEC test database}"

export DB_APP_USER="$NMDB_APP_USER"

# NMDB: existing permanent database selected by DB_NAME.
python "$SCHEMA_PY" "$TEST_SCHEMA" --drop-first --yes

# NEC: separate permanent test database.
DB_NAME="$NEC_TEST_DB" python "$SCHEMA_PY" "${TEST_SCHEMA}_nec" --drop-first --yes

===================

set +x
set -euo pipefail
. .venv/bin/activate

: "${TEST_SCHEMA:?TEST_SCHEMA must come from the branch resolver}"
: "${NEC_TEST_DB:?NEC_TEST_DB is required}"

export TESTING=1

# Preserve TEST_SCHEMA. Do not overwrite it with public.
export NEC_SCHEMA="${TEST_SCHEMA}_nec"

ENCODED_USER=$(python3 -c 'import os; from urllib.parse import quote; print(quote(os.environ["NMDB_APP_USER"], safe=""))')
ENCODED_PASS=$(python3 -c 'import os; from urllib.parse import quote; print(quote(os.environ["NMDB_APP_PASS"], safe=""))')

MAIN_OPTIONS=$(python3 -c 'import os; from urllib.parse import quote; print(quote("-csearch_path=" + os.environ["TEST_SCHEMA"], safe=""))')
NEC_OPTIONS=$(python3 -c 'import os; from urllib.parse import quote; print(quote("-csearch_path=" + os.environ["NEC_SCHEMA"], safe=""))')

MAIN_URL="postgresql+psycopg2://${ENCODED_USER}:${ENCODED_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}?options=${MAIN_OPTIONS}"

NEC_URL="postgresql+psycopg2://${ENCODED_USER}:${ENCODED_PASS}@${DB_HOST}:${DB_PORT}/${NEC_TEST_DB}?options=${NEC_OPTIONS}"

NEC_ASYNC_URL="postgresql+asyncpg://${ENCODED_USER}:${ENCODED_PASS}@${DB_HOST}:${DB_PORT}/${NEC_TEST_DB}"

export DATABASE_URL="$MAIN_URL"
export TEST_DATABASE_URL="$MAIN_URL"

export NEC_TEST_DATABASE_URL="$NEC_ASYNC_URL"
export NEC_DATABASE_URL="$NEC_ASYNC_URL"

===================

import os
import re

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase


NEC_SCHEMA = os.environ.get("NEC_SCHEMA", "public").strip()

if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", NEC_SCHEMA):
    raise RuntimeError(f"Invalid NEC_SCHEMA: {NEC_SCHEMA!r}")


class NECBase(DeclarativeBase):
    metadata = MetaData(schema=NEC_SCHEMA)

================

def pytest_configure(config: pytest.Config) -> None:
    db_prepared = config.getoption("--nec-db-prepared")

    if _TEST_URL.database != LOCAL_TEST_DB:
        raise pytest.UsageError(
            f"NEC tests must use the dedicated {LOCAL_TEST_DB!r} database"
        )

    if db_prepared:
        main_schema = os.environ.get("TEST_SCHEMA", "").strip()

        if (
            not re.fullmatch(
                r"test_[a-z0-9_]+_[0-9]+",
                main_schema,
            )
            or NEC_SCHEMA != f"{main_schema}_nec"
            or len(NEC_SCHEMA) > 63
        ):
            raise pytest.UsageError(
                "Prepared NEC tests require "
                "NEC_SCHEMA=<TEST_SCHEMA>_nec"
            )

    elif os.getenv("JENKINS_URL") or NEC_SCHEMA != "public":
        raise pytest.UsageError(
            "Local NEC table initialization is restricted to public. "
            "Jenkins must use --nec-db-prepared."
        )


===============================

set +x
set -euo pipefail

if [[ -n "${TEST_SCHEMA:-}" && -x .venv/bin/python ]]; then

    if [[ ! "$TEST_SCHEMA" =~ ^test_[a-z0-9_]+_[0-9]+$ ]] || (( ${#TEST_SCHEMA} > 59 )); then
        echo "ERROR: Refusing cleanup of an invalid test schema"
        exit 1
    fi

    : "${NEC_TEST_DB:?NEC_TEST_DB is required}"

    export DB_APP_USER="$NMDB_APP_USER"

    rc=0

    # NMDB test schema in the existing NMDB database.
    .venv/bin/python "$SCHEMA_PY" "$TEST_SCHEMA" --drop-only --yes || rc=1

    # NEC test schema in the separate permanent NEC test database.
    DB_NAME="$NEC_TEST_DB" .venv/bin/python "$SCHEMA_PY" "${TEST_SCHEMA}_nec" --drop-only --yes || rc=1

    exit "$rc"
fi
