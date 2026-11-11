
from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
SUITES = {
    "nmdb": ("tests", "nmdb_ci_", "main.xml"),
    "nec": ("tests_nec", "nec_ci_", "nec.xml"),
}

def maintenance_url(raw: str) -> URL:
    url = make_url(raw.strip())
    if url.get_backend_name() != "postgresql" or url.database != "postgres":
        raise ValueError("CI_POSTGRES_URL must target the PostgreSQL maintenance database 'postgres'")
    # These keys could override the URL destination after changing its database.
    if set(url.query) - {"options"}:
        raise ValueError("Use a canonical CI URL without query parameters; configure TLS explicitly if required")
    return url.set(drivername="postgresql+psycopg2").difference_update_query(["options"])


def test_environment(suite: str, admin_url: URL, database: str) -> dict[str, str]:
    env = os.environ.copy()
    # Do not leak old shared-schema configuration into the new test process.
    for key in (
        "CI_POSTGRES_URL", "DATABASE_URL", "TEST_DATABASE_URL",
        "NEC_DATABASE_URL", "NEC_TEST_DATABASE_URL", "NEC_MIGRATION_DATABASE_URL",
        "NEC_EXPECTED_TEST_DB", "NEC_SCHEMA", "TEST_SCHEMA",
        "NMDB_SKIP_TEST_RESET", "PGOPTIONS", "PGDATABASE", "PGSERVICE",
    ):
        env.pop(key, None)

    # pytest obtains both drivers from this one test URL as necessary.
    url = admin_url.set(database=database).update_query_dict(
        {"options": "-csearch_path=public"}
    )
    env["TESTING"] = "1"
    env["APP_MODE"] = suite
    # Transitional compatibility until APP_ENVIRONMENT consumers are retired.
    env["APP_ENVIRONMENT"] = suite
    env["COVERAGE_FILE"] = str(ROOT / f".coverage.{suite}")
    rendered = url.render_as_string(hide_password=False)
    if suite == "nec":
        env["NEC_TEST_DATABASE_URL"] = rendered
        # tests_nec/conftest.py normalizes this to asyncpg before app imports.
        env["NEC_DATABASE_URL"] = rendered
    else:
        env["TEST_DATABASE_URL"] = rendered
        env["DATABASE_URL"] = rendered
    return env


def pytest_command(suite: str) -> list[str]:
    folder, _, report = SUITES[suite]
    return [
        sys.executable, "-m", "pytest", folder, "-vv", "--tb=short",
        f"--junitxml=test-results/{report}", "--cov=app",
        f"--cov-report=xml:coverage-{suite}.xml",
        f"--cov-report=html:coverage-{suite}-html",
    ]


def interrupted(signum: int, _frame: object) -> None:
    raise KeyboardInterrupt(f"signal {signum}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=tuple(SUITES))
    args = parser.parse_args()
    raw = os.environ.get("CI_POSTGRES_URL", "")
    if not raw.strip():
        print("ERROR: CI_POSTGRES_URL is required", file=sys.stderr)
        return 2

    try:
        admin_url = maintenance_url(raw)
    except Exception as exc:
        # Avoid printing a malformed URL or a password from an exception.
        print(f"ERROR: Invalid CI database configuration ({type(exc).__name__})", file=sys.stderr)
        return 2

    _, prefix, _ = SUITES[args.suite]
    database = f"{prefix}{uuid4().hex}"
    if not re.fullmatch(r"(?:nmdb|nec)_ci_[0-9a-f]{32}", database):
        raise RuntimeError("Refusing an invalid generated database name")

    engine = create_engine(
        admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool,
        connect_args={"connect_timeout": 10},
    )
    quoted_db = engine.dialect.identifier_preparer.quote_identifier(database)
    created = False
    code = 1
    old_handler = signal.signal(signal.SIGTERM, interrupted)
    try:
        with engine.connect() as conn:
            # No IF EXISTS, no arbitrary database-name input: never reuse a DB.
            conn.exec_driver_sql(f"CREATE DATABASE {quoted_db} TEMPLATE template0")
        created = True
        print(f"Created {database}; schema=public", flush=True)
        (ROOT / "test-results").mkdir(exist_ok=True)
        completed = subprocess.run(
            pytest_command(args.suite), cwd=ROOT,
            env=test_environment(args.suite, admin_url, database), check=False,
        )
        code = completed.returncode if completed.returncode >= 0 else 1
    except KeyboardInterrupt:
        code = 130
    except Exception as exc:
        print(f"ERROR: CI test execution failed ({type(exc).__name__})", file=sys.stderr)
        code = 1
    finally:
        # Normal completion, pytest failure, and handled interruption land here.
        # Agent loss or SIGKILL still requires administrative orphan cleanup.
        try:
            if created:
                with engine.connect() as conn:
                    conn.exec_driver_sql(f"DROP DATABASE {quoted_db} WITH (FORCE)")
                print(f"Removed {database}", flush=True)
        except Exception as exc:
            print(
                f"ERROR: Cleanup failed for {database} ({type(exc).__name__}); "
                "remove this CI-owned database after checking the build has stopped",
                file=sys.stderr,
            )
            if code == 0:
                code = 1
        finally:
            engine.dispose()
            signal.signal(signal.SIGTERM, old_handler)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
