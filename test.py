from collections.abc import AsyncIterator
import os
import re
from pathlib import Path

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from sqlalchemy import Enum as SAEnum, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env.local", override=False)


def _nec_test_url() -> URL:
    raw = os.getenv("NEC_TEST_DATABASE_URL", "").strip()
    if not raw:
        raise RuntimeError("NEC_TEST_DATABASE_URL is required; runtime URLs are not test fallbacks")
    url = make_url(raw)
    name = url.database or ""
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("NEC pytest requires PostgreSQL")
    if name != "test_nec" and not re.fullmatch(r"nec_ci_[0-9a-f]{32}", name):
        raise RuntimeError(
            "Refusing test-table reset: use test_nec or a CI-generated nec_ci_<32 hex digits> database"
        )
    # Keep this conversion limited to the connection format used by the project.
    # Do not silently discard TLS, service, host or database overrides.
    if set(url.query) - {"options"}:
        raise RuntimeError(
            "Unsupported test URL query parameters; configure driver-specific TLS/connection options explicitly"
        )
    return url.set(drivername="postgresql+asyncpg").difference_update_query(["options"])


# Select the test destination BEFORE test modules import the application.
_TEST_URL = _nec_test_url()
os.environ["TESTING"] = "1"
os.environ["APP_MODE"] = "nec"
os.environ["NEC_DATABASE_URL"] = _TEST_URL.render_as_string(hide_password=False)
# Temporary compatibility for old readers; no developer-provided schema setting.
os.environ["NEC_SCHEMA"] = "public"


@pytest.fixture(scope="session")
def pg_test_url() -> str:
    return _TEST_URL.render_as_string(hide_password=False)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def async_engine(pg_test_url: str) -> AsyncIterator[AsyncEngine]:
    from app.core.nec_base import NECBase
    import app.models.nec.nec_models  # noqa: F401  # Register NEC tables.

    if os.getenv("PYTEST_XDIST_WORKER"):
        raise RuntimeError("Use one pytest worker per NEC database; do not use -n for this fixture")

    required = {"cached_mission", "cached_sensor_catalog", "nec_sync_log"}
    actual = {table.name for table in NECBase.metadata.tables.values()}
    if actual != required:
        raise RuntimeError(
            f"Unexpected NEC metadata: {sorted(actual)}; expected {sorted(required)}"
        )
    for table in NECBase.metadata.tables.values():
        if table.schema != "public":
            raise RuntimeError(f"NEC model must target public: {table.fullname}")
        for column in table.columns:
            if isinstance(column.type, SAEnum):
                if column.type.schema not in (None, "public"):
                    raise RuntimeError(f"NEC ENUM must target public: {column.type.name}")
                if getattr(column.type, "create_type", True) is False:
                    raise RuntimeError(
                        "NEC model ENUM has create_type=False; give the test metadata an explicit "
                        "ENUM create/drop hook or enable ORM type DDL before using create_all"
                    )

    url = make_url(pg_test_url)
    engine = create_async_engine(
        url, echo=False, poolclass=NullPool,
        connect_args={"server_settings": {"search_path": "public"}},
    )
    try:
        async with engine.begin() as conn:
            database = await conn.scalar(text("SELECT current_database()"))
            if database != url.database:
                raise RuntimeError("Connected database does not match the validated NEC test URL")
            schema = await conn.scalar(text("SELECT current_schema()"))
            if schema != "public":
                raise RuntimeError("NEC test connection must use public")
            if await conn.scalar(text("SELECT to_regclass('public.alembic_version')")):
                raise RuntimeError(
                    "This database has migration history. Provision a fresh disposable NEC test database; "
                    "do not erase migration history to bypass this check"
                )

            # Only this application's metadata, only the validated test database.
            await conn.run_sync(NECBase.metadata.drop_all)
            await conn.run_sync(NECBase.metadata.create_all)
            tables = await conn.run_sync(
                lambda sync_conn: set(inspect(sync_conn).get_table_names(schema="public"))
            )
            if not required.issubset(tables):
                raise RuntimeError(f"Missing NEC test tables: {sorted(required - tables)}")
        print(f"NEC pytest database: {url.database}; schema=public; initialization=metadata")
        yield engine
    finally:
        # Per-test transaction fixtures handle data isolation; do not drop at teardown.
        await engine.dispose()