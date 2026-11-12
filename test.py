# tests_nec/conftest.py

import os
import re
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Enum as SAEnum
from sqlalchemy import MetaData, inspect, text
from sqlalchemy.engine import URL, Connection, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool


# ---------------------------------------------------------
# 1. PROJECT AND TEST DATABASE CONFIGURATION
# ---------------------------------------------------------

# This file must be located at:
# <repository-root>/tests_nec/conftest.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(
    PROJECT_ROOT / ".env.local",
    override=False,
)

# Dedicated NEC databases use the public schema.
NEC_SCHEMA = "public"

# Explicit disposable-test-database naming policy.
LOCAL_TEST_DB = "test_nec"
CI_TEST_DB_PATTERN = re.compile(r"nec_ci_[0-9a-f]{32}")

REQUIRED_TABLES = {
    "cached_mission",
    "cached_sensor_catalog",
    "nec_sync_log",
}


def _read_test_url() -> URL:
    """
    Read only the dedicated NEC test database URL.

    Never fall back to DATABASE_URL, NEC_DATABASE_URL,
    or the NMDB test database.
    """
    raw_url = os.getenv(
        "NEC_TEST_DATABASE_URL",
        "",
    ).strip()

    if not raw_url:
        raise RuntimeError(
            "NEC_TEST_DATABASE_URL is required. "
            "Use test_nec locally or a dedicated NEC CI test database."
        )

    try:
        url = make_url(raw_url)
    except (ArgumentError, ValueError):
        # Do not expose a credential-bearing URL in an exception.
        raise RuntimeError(
            "NEC_TEST_DATABASE_URL is invalid"
        ) from None

    if url.get_backend_name() != "postgresql":
        raise RuntimeError(
            "NEC tests require PostgreSQL"
        )

    database = url.database or ""

    if (
        database != LOCAL_TEST_DB
        and not CI_TEST_DB_PATTERN.fullmatch(database)
    ):
        raise RuntimeError(
            f"Unsafe NEC test database: {database!r}. "
            "Allowed databases are test_nec or "
            "nec_ci_<32 lowercase hexadecimal characters>."
        )

    # Remove the psycopg2-specific options parameter.
    # The async search_path is configured through server_settings.
    return (
        url.set(drivername="postgresql+asyncpg")
        .difference_update_query(["options"])
    )


# Set test configuration before test modules import application code.
_TEST_URL = _read_test_url()

os.environ["TESTING"] = "1"
os.environ["APP_MODE"] = "nec"

# Compatibility with existing model/configuration readers.
# This is now fixed by the fixture, not a developer-supplied schema.
os.environ["NEC_SCHEMA"] = NEC_SCHEMA

# Any NEC application engine created during these tests must also
# point to the validated test database, never the runtime database.
os.environ["NEC_DATABASE_URL"] = _TEST_URL.render_as_string(
    hide_password=False
)


# ---------------------------------------------------------
# 2. PYTEST OPTION FOR JENKINS-PREPARED DATABASES
# ---------------------------------------------------------

def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--nec-db-prepared",
        action="store_true",
        default=False,
        help=(
            "Use NEC tables already migrated by Jenkins. "
            "Do not create or drop tables inside pytest."
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    db_prepared = config.getoption("--nec-db-prepared")

    # Prevent CI from accidentally using the local ORM-reset path.
    if not db_prepared and (
        _TEST_URL.database != LOCAL_TEST_DB
        or os.getenv("JENKINS_URL")
    ):
        raise pytest.UsageError(
            "CI NEC tests require --nec-db-prepared. "
            "Run NEC Alembic migrations in Jenkins before pytest."
        )


# ---------------------------------------------------------
# 3. TEST DATABASE URL FIXTURE
# ---------------------------------------------------------

@pytest.fixture(scope="session")
def pg_test_url() -> str:
    """
    Return the validated NEC test URL.

    Retains the fixture name used by existing tests.
    """
    return _TEST_URL.render_as_string(hide_password=False)


# ---------------------------------------------------------
# 4. DATABASE INITIALIZATION HELPERS
# ---------------------------------------------------------

def _get_nec_metadata() -> MetaData:
    """
    Load NEC-only metadata.

    NEC models must inherit from NECBase, not the main Base.
    """
    from app.core.nec_base import NECBase
    from app.models.nec import nec_models  # noqa: F401

    metadata = NECBase.metadata
    names = {
        table.name
        for table in metadata.tables.values()
    }

    # Fail rather than silently initialize shared/main metadata.
    if names != REQUIRED_TABLES:
        raise RuntimeError(
            "NECBase must contain the NEC application tables only. "
            f"Missing: {sorted(REQUIRED_TABLES - names)}; "
            f"unexpected: {sorted(names - REQUIRED_TABLES)}"
        )

    for table in metadata.tables.values():
        if table.schema not in (None, NEC_SCHEMA):
            raise RuntimeError(
                f"{table.fullname} must use the public schema. "
                "Update the NEC model mapping before running tests."
            )

        for column in table.columns:
            if (
                isinstance(column.type, SAEnum)
                and column.type.native_enum
            ):
                if column.type.schema not in (None, NEC_SCHEMA):
                    raise RuntimeError(
                        f"ENUM for {table.name}.{column.name} "
                        "must use the public schema."
                    )

    return metadata


async def _validate_connection(
    conn: AsyncConnection,
    expected_db: str,
) -> None:
    """
    Confirm the actual connection matches the validated test URL.
    """
    database = await conn.scalar(
        text("SELECT current_database()")
    )

    schema = await conn.scalar(
        text("SELECT current_schema()")
    )

    if database != expected_db or schema != NEC_SCHEMA:
        raise RuntimeError(
            f"Unexpected NEC test target: {database}.{schema}. "
            f"Expected {expected_db}.{NEC_SCHEMA}."
        )


async def _public_tables(
    conn: AsyncConnection,
) -> set[str]:
    names = await conn.run_sync(
        lambda sync_conn: inspect(sync_conn).get_table_names(
            schema=NEC_SCHEMA
        )
    )

    return set(names)


def _prepare_local_tables(
    connection: Connection,
    metadata: MetaData,
    existing: set[str],
) -> None:
    """
    Reset NEC model tables only in a validated local test database.

    This helper is never called with --nec-db-prepared.
    """
    if "alembic_version" in existing:
        raise RuntimeError(
            "Local table initialization refuses an "
            "Alembic-managed database. "
            "Use a fresh disposable test_nec database."
        )

    unexpected = existing - REQUIRED_TABLES

    if unexpected:
        raise RuntimeError(
            "The local NEC test database contains unrelated tables: "
            f"{sorted(unexpected)}. "
            "Use a dedicated test_nec database."
        )

    # Local ORM initialization must be able to create native ENUMs.
    # Do not silently depend on a migration that local tests never run.
    for table in metadata.tables.values():
        for column in table.columns:
            if (
                isinstance(column.type, SAEnum)
                and column.type.native_enum
                and getattr(column.type, "create_type", True) is False
            ):
                raise RuntimeError(
                    f"{table.name}.{column.name} uses "
                    "create_type=False. Its ENUM needs model/test "
                    "DDL creation for local pytest without Alembic."
                )

    # Reset only the NEC-owned metadata.
    # Never drop the database or public schema.
    metadata.drop_all(bind=connection)
    metadata.create_all(bind=connection)


# ---------------------------------------------------------
# 5. ASYNC DATABASE ENGINE
# ---------------------------------------------------------

@pytest_asyncio.fixture(
    scope="session",
    loop_scope="session",
)
async def async_engine(
    pg_test_url: str,
    pytestconfig: pytest.Config,
) -> AsyncIterator[AsyncEngine]:
    """
    Local:
        Validate test database.
        Reset/create NEC tables from ORM metadata.
        Run tests.
        Drop locally created NEC tables at teardown.

    Jenkins --nec-db-prepared:
        Validate test database.
        Verify Alembic history and required tables.
        Run tests.
        Dispose connections only.

    Alembic is never invoked from this fixture.
    """
    db_prepared = pytestconfig.getoption("--nec-db-prepared")
    url = make_url(pg_test_url)
    metadata = _get_nec_metadata()

    local_tables_created = False

    engine = create_async_engine(
        url,
        echo=False,
        poolclass=NullPool,
        connect_args={
            "server_settings": {
                "search_path": NEC_SCHEMA,
            }
        },
    )

    try:
        async with engine.begin() as conn:
            # Validate before any structural database operation.
            await _validate_connection(
                conn,
                url.database or "",
            )

            existing = await _public_tables(conn)

            if db_prepared:
                # Jenkins has already migrated the database.
                # Do not call create_all() or drop_all() here.
                if "alembic_version" not in existing:
                    raise RuntimeError(
                        "--nec-db-prepared was supplied, but "
                        "public.alembic_version is missing. "
                        "Run NEC Alembic against this CI database "
                        "before pytest."
                    )

                has_revision = await conn.scalar(
                    text(
                        "SELECT EXISTS "
                        "(SELECT 1 FROM public.alembic_version)"
                    )
                )

                if not has_revision:
                    raise RuntimeError(
                        "NEC Alembic version table is empty"
                    )

            else:
                # Local setup: ORM table creation, no Alembic.
                await conn.run_sync(
                    _prepare_local_tables,
                    metadata,
                    existing,
                )

            tables = await _public_tables(conn)
            missing_tables = REQUIRED_TABLES - tables

            if missing_tables:
                raise RuntimeError(
                    "NEC tables are missing: "
                    f"{sorted(missing_tables)}"
                )

        # Set only after the initialization transaction commits.
        local_tables_created = not db_prepared

        setup_mode = (
            "Jenkins-prepared tables"
            if db_prepared
            else "local ORM tables"
        )

        print(
            f"\nNEC test database: {url.database}; "
            f"schema: {NEC_SCHEMA}; "
            f"setup: {setup_mode}"
        )

        yield engine

    finally:
        try:
            if local_tables_created:
                # Dependent session and connection fixtures have
                # already completed their teardown.
                async with engine.begin() as conn:
                    await _validate_connection(
                        conn,
                        url.database or "",
                    )

                    await conn.run_sync(
                        metadata.drop_all
                    )

            # Jenkins-prepared tables are deliberately left intact.
            # Jenkins owns its final CI database cleanup.

        finally:
            await engine.dispose()


# ---------------------------------------------------------
# 6. ASYNC CONNECTION — EXISTING BEHAVIOR
# ---------------------------------------------------------

@pytest_asyncio.fixture(loop_scope="session")
async def async_connection(
    async_engine: AsyncEngine,
) -> AsyncIterator[AsyncConnection]:
    """
    Per-test connection with an outer transaction.
    """
    async with async_engine.connect() as conn:
        transaction = await conn.begin()

        try:
            yield conn

        finally:
            if transaction.is_active:
                await transaction.rollback()


# ---------------------------------------------------------
# 7. ASYNC SESSION FACTORY — EXISTING BEHAVIOR
# ---------------------------------------------------------

@pytest.fixture
def async_session_factory(
    async_connection: AsyncConnection,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=async_connection,
        expire_on_commit=False,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
    )


# ---------------------------------------------------------
# 8. ASYNC DATABASE SESSION — EXISTING BEHAVIOR
# ---------------------------------------------------------

@pytest_asyncio.fixture(loop_scope="session")
async def async_session(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


# ---------------------------------------------------------
# 9. CONNECTIVITY CHECKER MOCK — EXISTING BEHAVIOR
# ---------------------------------------------------------

@pytest.fixture
def connectivity_checker() -> AsyncMock:
    from app.services.nec.connectivity_checker import (
        ConnectivityResult,
    )

    checker = AsyncMock()

    checker.check_connectivity.return_value = ConnectivityResult(
        can_sync=True,
        latency_ms=1.0,
        reason="None",
    )

    return checker


# ---------------------------------------------------------
# 10. NEC SYNC ENGINE — EXISTING BEHAVIOR
# ---------------------------------------------------------

@pytest.fixture
def sync_engine(
    async_engine: AsyncEngine,
    async_session_factory: async_sessionmaker[AsyncSession],
    connectivity_checker: AsyncMock,
) -> Any:
    from app.services.nec.sync_engine import SyncEngine

    return SyncEngine(
        nec_dsn="postgresql+asyncpg://should_not_matter",
        connectivity_checker=connectivity_checker,
        nmdb_api_base_url="http://nmdb",
        nec_engine=async_engine,
        nec_session_factory=async_session_factory,
    )


# ---------------------------------------------------------
# 11. AUTHENTICATION OVERRIDE HELPER — EXISTING BEHAVIOR
# ---------------------------------------------------------

def apply_nec_auth_override(
    fastapi_app: FastAPI,
    override_get_current_user: Callable[[], dict[str, Any]],
) -> int:
    matched = 0
    seen: set[int] = set()

    def inspect_dependant(dependant: Any) -> None:
        nonlocal matched

        for dependency in dependant.dependencies:
            call = dependency.call

            if (
                call is not None
                and getattr(call, "__name__", None)
                == "get_current_user"
                and getattr(call, "__module__", "").startswith("app.")
                and id(call) not in seen
            ):
                fastapi_app.dependency_overrides[
                    call
                ] = override_get_current_user

                seen.add(id(call))
                matched += 1

            inspect_dependant(dependency)

    for route in fastapi_app.routes:
        dependant = getattr(
            route,
            "dependant",
            None,
        )

        if dependant is not None:
            inspect_dependant(dependant)

    print(
        "NEC auth dependencies overridden:",
        matched,
    )

    return matched


# ---------------------------------------------------------
# 12. NEC FASTAPI APP — EXISTING BEHAVIOR
# ---------------------------------------------------------

@pytest.fixture
def nec_app(
    sync_engine: Any,
    async_session: AsyncSession,
) -> Iterator[FastAPI]:
    from app.api.nec import nec_sync
    from app.api.dependencies.auth import get_current_user
    from app.core.nec_db import get_nec_session
    from app.services.nec.nec_dependencies import get_sync_engine

    fastapi_app = FastAPI()
    fastapi_app.include_router(nec_sync.router)

    def override_get_sync_engine() -> Any:
        return sync_engine

    def override_get_current_user() -> dict[str, Any]:
        return {
            "user_id": "test-user",
            "is_superuser": True,
        }

    async def override_get_nec_session() -> AsyncIterator[AsyncSession]:
        yield async_session

    fastapi_app.dependency_overrides[
        get_sync_engine
    ] = override_get_sync_engine

    fastapi_app.dependency_overrides[
        get_nec_session
    ] = override_get_nec_session

    fastapi_app.dependency_overrides[
        get_current_user
    ] = override_get_current_user

    apply_nec_auth_override(
        fastapi_app,
        override_get_current_user,
    )

    try:
        yield fastapi_app

    finally:
        fastapi_app.dependency_overrides.clear()


# ---------------------------------------------------------
# 13. ASYNC HTTP CLIENT — EXISTING BEHAVIOR
# ---------------------------------------------------------

@pytest_asyncio.fixture(loop_scope="session")
async def async_client(
    nec_app: FastAPI,
) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=nec_app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield client
