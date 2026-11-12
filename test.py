"""Jenkins-only NMDB/NEC test lifecycle: provision -> Alembic -> pytest -> cleanup.

Run from the repository checkout with its virtualenv Python:
    .venv/bin/python scripts/ci/run_database_tests.py

Input: CI_POSTGRES_URL, a Jenkins secret text PostgreSQL URL ending in /postgres.
Use a dedicated non-superuser CI role with CREATEDB, not production credentials.
PostgreSQL 14+, SQLAlchemy 2.x, psycopg2, Alembic and the project's test dependencies
must already be installed. This script does not change local pytest behavior.

This version accepts a canonical maintenance URL without query parameters. It
fails closed on transport options rather than dropping TLS/security parameters;
add explicit psycopg2/asyncpg TLS mapping before using a query-based TLS profile.
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
SUITES = {
    "nmdb": {"folder": "tests", "ini": "alembic.ini", "report": "main.xml"},
    "nec": {"folder": "tests_nec", "ini": "alembic.nec.ini", "report": "nec.xml"},
}
NEC_TABLES = {"cached_mission", "cached_sensor_catalog", "nec_sync_log"}
NAME_PATTERN = re.compile(r"(?:nmdb|nec)_ci_[0-9a-f]{32}")


def maintenance_url(raw: str) -> URL:
    url = make_url(raw.strip())
    if url.get_backend_name() != "postgresql" or url.database != "postgres":
        raise ValueError("CI_POSTGRES_URL must target the postgres maintenance database")
    if not url.host or not url.username:
        raise ValueError("An explicit CI host and username are required")
    if url.query:
        raise ValueError("Use a canonical CI URL without query parameters; map TLS options explicitly if needed")
    return url.set(drivername="postgresql+psycopg2")


def database_urls(admin: URL, names: dict[str, str]) -> dict[str, URL]:
    """Two separate databases; sync URLs pin public, async URL has no options."""
    for suite in SUITES:
        if not re.fullmatch(fr"{suite}_ci_[0-9a-f]{{32}}", names[suite]):
            raise ValueError("Unexpected generated CI database name")
    nmdb = admin.set(database=names["nmdb"])
    nec = admin.set(database=names["nec"])
    return {
        "nmdb": nmdb.update_query_dict({"options": "-csearch_path=public"}),
        "nec_sync": nec.update_query_dict({"options": "-csearch_path=public"}),
        "nec_async": nec.set(drivername="postgresql+asyncpg"),
    }


def child_environment(suite: str, urls: dict[str, URL], *, migration: bool) -> dict[str, str]:
    """Use the SAME database pair in both migration and pytest subprocesses."""
    env = os.environ.copy()
    for key in (
        "CI_POSTGRES_URL", "NEC_EXPECTED_TEST_DB", "NEC_MIGRATION_DATABASE_URL",
        "TEST_SCHEMA", "NMDB_SKIP_TEST_RESET", "PYTEST_ADDOPTS",
        "DATABASE_URL", "TEST_DATABASE_URL", "NEC_DATABASE_URL", "NEC_TEST_DATABASE_URL",
        "NEC_DB_HOST", "NEC_DB_PORT", "NEC_DB_NAME", "NEC_APP_USER", "NEC_APP_PASS",
    ):
        env.pop(key, None)
    # Avoid libpq environment defaults redirecting a connection or search_path.
    for key in list(env):
        if key.startswith("PG"):
            env.pop(key, None)

    nmdb_url = urls["nmdb"].render_as_string(hide_password=False)
    nec_async = urls["nec_async"].render_as_string(hide_password=False)
    nec_connection = urls["nec_sync"] if migration else urls["nec_async"]
    env.update({
        "TESTING": "1",
        "APP_MODE": suite,
        "APP_ENVIRONMENT": suite,  # Retain existing project compatibility.
        "DATABASE_URL": nmdb_url,
        "TEST_DATABASE_URL": nmdb_url,
        "NEC_DATABASE_URL": nec_connection.render_as_string(hide_password=False),
        "NEC_TEST_DATABASE_URL": nec_async,
        "NEC_SCHEMA": "public",  # Existing revisions still read this value.
        "NMDB_SKIP_TEST_RESET": "1",
        "COVERAGE_FILE": str(ROOT / f".coverage.{suite}"),
    })
    return env


def migration_command(suite: str) -> list[str]:
    return [sys.executable, "-m", "alembic", "-c", SUITES[suite]["ini"], "upgrade", "head"]


def pytest_command(suite: str) -> list[str]:
    info = SUITES[suite]
    command = [sys.executable, "-m", "pytest", info["folder"]]
    if suite == "nec":
        command.append("--nec-db-prepared")
    command.extend([
        "-vv", "--tb=short", f"--junitxml=test-results/{info['report']}",
        "--cov=app", "--cov-report=",
    ])
    return command


def run_process(command: list[str], env: dict[str, str], label: str) -> int:
    print(f"\n=== {label} ===", flush=True)
    process = subprocess.Popen(command, cwd=ROOT, env=env, start_new_session=True)
    try:
        result = process.wait()
        return result if result >= 0 else 1
    except BaseException:
        if process.poll() is None:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait()
        raise


def verify_migrated(url: URL, database: str, suite: str) -> None:
    """Check the target and history after Alembic; never create missing tables."""
    engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 10})
    try:
        with engine.connect() as conn:
            actual = conn.execute(text("SELECT current_database(), current_schema()")).one()
            if tuple(actual) != (database, "public"):
                raise RuntimeError("Migration verification connected to an unexpected target")
            tables = set(inspect(conn).get_table_names(schema="public"))
            if "alembic_version" not in tables:
                raise RuntimeError(f"{suite}: public.alembic_version is missing after migration")
            revisions = conn.execute(text("SELECT version_num FROM public.alembic_version")).scalars().all()
            if not revisions:
                raise RuntimeError(f"{suite}: no applied migration revision; check committed version files")
            if suite == "nec" and not NEC_TABLES.issubset(tables):
                raise RuntimeError("NEC migration did not create all three required tables in public")
        print(f"Verified {suite}: {database}.public", flush=True)
    finally:
        engine.dispose()


def combine_coverage() -> int:
    # Separate pytest processes, separate data files; combine only this run's two files.
    paths = [ROOT / ".coverage.nmdb", ROOT / ".coverage.nec"]
    if not all(path.is_file() for path in paths):
        print("ERROR: a suite did not produce coverage data", file=sys.stderr)
        return 1
    env = os.environ.copy()
    env.pop("CI_POSTGRES_URL", None)
    env["COVERAGE_FILE"] = str(ROOT / ".coverage")
    for args in (
        ["combine", "--keep", *(str(path) for path in paths)],
        ["xml", "-o", "coverage.xml"],
        ["html", "-d", "coverage-html"],
    ):
        code = run_process([sys.executable, "-m", "coverage", *args], env, "Coverage")
        if code:
            return code
    return 0


def interrupted(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


def main() -> int:
    try:
        admin = maintenance_url(os.environ.get("CI_POSTGRES_URL", ""))
    except Exception:
        print("ERROR: configure CI_POSTGRES_URL with an explicit PostgreSQL host/user, /postgres and no query parameters", file=sys.stderr)
        return 2

    for info in SUITES.values():
        if not (ROOT / info["ini"]).is_file() or not (ROOT / info["folder"]).is_dir():
            print("ERROR: run from the complete repository checkout; missing migration config or test folder", file=sys.stderr)
            return 2

    # Do not report stale output if migration fails before pytest on a reused workspace.
    (ROOT / "test-results").mkdir(exist_ok=True)
    for name in ("main.xml", "nec.xml"):
        (ROOT / "test-results" / name).unlink(missing_ok=True)
    for name in (".coverage", ".coverage.nmdb", ".coverage.nec", "coverage.xml"):
        (ROOT / name).unlink(missing_ok=True)

    shutil.rmtree(ROOT / "coverage-html", ignore_errors=True)

    token = uuid4().hex
    names = {suite: f"{suite}_ci_{token}" for suite in SUITES}
    urls = database_urls(admin, names)
    # Only names successfully created by this invocation can reach cleanup.
    created: list[str] = []
    code = 1
    engine = None
    old_handler = signal.signal(signal.SIGTERM, interrupted)
    try:
        engine = create_engine(
            admin, isolation_level="AUTOCOMMIT", poolclass=NullPool,
            connect_args={"connect_timeout": 10},
        )
        with engine.connect() as conn:
            for name in names.values():
                quoted = engine.dialect.identifier_preparer.quote_identifier(name)
                conn.exec_driver_sql(f"CREATE DATABASE {quoted} TEMPLATE template0")
                created.append(name)
                print(f"Created CI database: {name}", flush=True)

        for suite in SUITES:
            migration_env = child_environment(suite, urls, migration=True)
            code = run_process(migration_command(suite), migration_env, f"Migrate {suite.upper()} public schema")
            if code:
                raise RuntimeError(f"{suite}: Alembic failed; no pytest will run")
            verify_migrated(urls["nmdb" if suite == "nmdb" else "nec_sync"], names[suite], suite)

        # Both suites run even if a test assertion in the first suite fails.
        # Return failure to Jenkins, which then blocks image/deployment stages.
        results = []
        for suite in SUITES:
            test_env = child_environment(suite, urls, migration=False)
            results.append(run_process(pytest_command(suite), test_env, f"Run {suite.upper()} pytest"))
        coverage_result = combine_coverage()
        code = next((value for value in results if value), coverage_result)
    except KeyboardInterrupt:
        code = 130
    except RuntimeError as exc:
        # These are our own messages and do not contain connection URLs.
        print(f"ERROR: {exc}", file=sys.stderr)
        code = code if code else 1
    except Exception as exc:
        print(f"ERROR: CI database workflow failed ({type(exc).__name__})", file=sys.stderr)
        code = 1
    finally:
        if engine is not None:
            for name in reversed(created):
                try:
                    if not NAME_PATTERN.fullmatch(name):
                        raise RuntimeError("Invalid cleanup name")
                    quoted = engine.dialect.identifier_preparer.quote_identifier(name)
                    with engine.connect() as conn:
                        conn.exec_driver_sql(f"DROP DATABASE {quoted} WITH (FORCE)")
                    print(f"Removed CI database: {name}", flush=True)
                except Exception as exc:
                    print(f"ERROR: cleanup failed for {name} ({type(exc).__name__}); check for an orphan CI database", file=sys.stderr)
                    if code == 0:
                        code = 1
            engine.dispose()
        signal.signal(signal.SIGTERM, old_handler)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
