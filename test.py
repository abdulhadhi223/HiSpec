
# tests/nec/conftest.py

import os
import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from dotenv import load_dotenv
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema

from alembic import command
from alembic.config import Config


# ---------------------------------------------------------
# 1. PROJECT CONFIGURATION
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(
    PROJECT_ROOT / ".env.local",
    override=False,
)

NEC_SCHEMA = os.environ.get(
    "NEC_SCHEMA", "nec"
).strip()

EXPECTED_TEST_DB = os.environ.get(
    "NEC_EXPECTED_TEST_DB", "test_db"
).strip()


def validate_schema_name(schema: str):
    """
    Validate PostgreSQL schema identifier.
    Prevent accidental access to system schemas.
    """

    if not re.fullmatch(
        r"[a-z_][a-z0-9_]*", schema
    ):
        raise RuntimeError(
            f"Invalid NEC_SCHEMA: {schema}"
        )

    if schema in (
        "public",
        "information_schema",
        "pg_catalog",
    ) or schema.startswith("pg_"):
        raise RuntimeError(
            f"Protected schema cannot be used: {schema}"
        )


validate_schema_name(NEC_SCHEMA)


# ---------------------------------------------------------
# 2. NEC ALEMBIC MIGRATIONS
# ---------------------------------------------------------

def run_nec_migrations(connection, project_root):
    """
    Run NEC migrations using the supplied
    SQLAlchemy synchronous connection.

    alembic.nec.ini / env.py must support
    config.attributes["connection"].
    """

    ini_path = project_root / "alembic.nec.ini"

    if not ini_path.exists():
        raise RuntimeError(
            f"NEC Alembic config missing: {ini_path}"
        )

    config = Config(str(ini_path))

    config.attributes["connection"] = connection

    command.upgrade(config, "head")


# ---------------------------------------------------------
# 3. TEST DATABASE URL
# ---------------------------------------------------------

@pytest.fixture(scope="session")
def pg_test_url():
    """
    Prefer dedicated NEC test database URL.
    Otherwise reuse the regular test DB.

    Never fall back to production DATABASE_URL.
    """

    url = (
        os.environ.get("NEC_TEST_DATABASE_URL")
        or os.environ.get("TEST_DATABASE_URL")
    )

    if not url:
        raise RuntimeError(
            "NEC_TEST_DATABASE_URL or "
            "TEST_DATABASE_URL must be configured"
        )

    return url.strip()


# ---------------------------------------------------------
# 4. ASYNC DATABASE ENGINE
# ---------------------------------------------------------

@pytest_asyncio.fixture(
    scope="session",
    loop_scope="session",
)
async def async_engine(pg_test_url):
    """
    Create NEC test engine.

    1. Validate database.
    2. Create NEC schema.
    3. Verify search_path.
    4. Run NEC migrations.
    5. Dispose engine after testing.
    """

    db_url = make_url(pg_test_url)

    async_url = db_url.set(
        drivername="postgresql+asyncpg"
    )

    engine = create_async_engine(
        async_url,
        echo=False,
        poolclass=NullPool,
        connect_args={
            "server_settings": {
                "search_path": (
                    f"{NEC_SCHEMA},public"
                )
            }
        },
    )

    try:

        # STEP 1: Validate database name
        # before creating any objects.

        async with engine.connect() as conn:

            database = await conn.scalar(
                text("SELECT current_database()")
            )

            print(
                f"\nNEC Test Database: {database}"
            )

            if database != EXPECTED_TEST_DB:
                raise RuntimeError(
                    "Unsafe NEC test database. "
                    f"Expected '{EXPECTED_TEST_DB}', "
                    f"connected to '{database}'"
                )

        # STEP 2: Create NEC schema.
        # No NMDB or public schema deletion.

        async with engine.begin() as conn:

            await conn.execute(
                CreateSchema(
                    NEC_SCHEMA,
                    if_not_exists=True,
                )
            )

        # STEP 3: Verify active schema.

        async with engine.connect() as conn:

            active_schema = await conn.scalar(
                text("SELECT current_schema()")
            )

            search_path = await conn.scalar(
                text(
                    "SELECT current_setting("
                    "'search_path')"
                )
            )

            print(
                f"NEC Active Schema: {active_schema}"
            )
            print(
                f"NEC Search Path: {search_path}"
            )

            if active_schema != NEC_SCHEMA:
                raise RuntimeError(
                    "NEC schema mismatch. "
                    f"Expected '{NEC_SCHEMA}', "
                    f"got '{active_schema}'"
                )

        # STEP 4: Run NEC migrations.

        print("\nRunning NEC Alembic migrations")

        async with engine.begin() as conn:

            await conn.run_sync(
                run_nec_migrations,
                PROJECT_ROOT,
            )

        print("NEC migration setup completed")

        # STEP 5: Check NEC tables.

        async with engine.connect() as conn:

            result = await conn.execute(
                text("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = :schema
                    ORDER BY table_name
                """),
                {"schema": NEC_SCHEMA},
            )

            tables = result.scalars().all()

            print(
                "NEC Tables:",
                tables,
            )

            # Validate the known application tables.
            # Adjust only if your actual model names differ.

            required_tables = {
                "cached_mission",
                "cached_sensor_catalog",
                "nec_sync_log",
            }

            missing_tables = (
                required_tables - set(tables)
            )

            if missing_tables:
                raise RuntimeError(
                    "NEC migrations completed but "
                    "required tables are missing: "
                    f"{sorted(missing_tables)}"
                )

        yield engine

    finally:

        await engine.dispose()


# ---------------------------------------------------------
# 5. ASYNC CONNECTION
# ---------------------------------------------------------

@pytest_asyncio.fixture(
    loop_scope="session",
)
async def async_connection(async_engine):
    """
    Per-test connection with an outer transaction.
    Roll back all changes after each test.
    """

    async with async_engine.connect() as conn:

        transaction = await conn.begin()

        try:
            yield conn

        finally:

            if transaction.is_active:
                await transaction.rollback()


# ---------------------------------------------------------
# 6. ASYNC SESSION FACTORY
# ---------------------------------------------------------

@pytest.fixture
def async_session_factory(async_connection):
    """
    SQLAlchemy session factory using a savepoint.
    """

    return async_sessionmaker(
        bind=async_connection,
        expire_on_commit=False,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
    )


# ---------------------------------------------------------
# 7. ASYNC DATABASE SESSION
# ---------------------------------------------------------

@pytest_asyncio.fixture(
    loop_scope="session",
)
async def async_session(async_session_factory):
    """
    Create an isolated session for each test.
    """

    async with async_session_factory() as session:

        yield session


# ---------------------------------------------------------
# 8. CONNECTIVITY CHECKER MOCK
# ---------------------------------------------------------

@pytest.fixture
def connectivity_checker():

    from app.services.nec.connectivity_checker import (
        ConnectivityResult,
    )

    checker = AsyncMock()

    checker.check_connectivity.return_value = (
        ConnectivityResult(
            can_sync=True,
            latency_ms=1.0,
            reason="None",
        )
    )

    return checker


# ---------------------------------------------------------
# 9. SYNC ENGINE
# ---------------------------------------------------------

@pytest.fixture
def sync_engine(
    async_engine,
    async_session_factory,
    connectivity_checker,
):
    """
    NEC SyncEngine using the test engine.
    """

    from app.services.nec.sync_engine import (
        SyncEngine,
    )

    engine = SyncEngine(
        nec_dsn=(
            "postgresql+asyncpg://"
            "should_not_matter"
        ),
        connectivity_checker=connectivity_checker,
        nmdb_api_base_url="http://nmdb",
        nec_engine=async_engine,
        nec_session_factory=async_session_factory,
    )

    return engine


# ---------------------------------------------------------
# 10. AUTHENTICATION OVERRIDE HELPER
# ---------------------------------------------------------

def apply_nec_auth_override(
    fastapi_app,
    override_get_current_user,
):
    """
    Locate get_current_user dependencies registered
    by the NEC router.

    Use the actual callable object registered with
    FastAPI to avoid import/reload identity mismatch.

    Does not bypass unrelated security dependencies.
    """

    matched = 0
    seen = set()

    def inspect_dependant(dependant):

        nonlocal matched

        for dependency in dependant.dependencies:

            call = dependency.call

            if (
                call is not None
                and getattr(
                    call, "__name__", None
                ) == "get_current_user"
                and getattr(
                    call, "__module__", ""
                ).startswith("app.")
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
# 11. NEC FASTAPI APP
# Combined nec_app_startup + nec_app
# ---------------------------------------------------------

@pytest.fixture
def nec_app(
    sync_engine,
    async_session,
):
    """
    Standalone NEC FastAPI app with database,
    sync-engine and authentication overrides.
    """

    from app.api.nec import nec_sync

    from app.api.dependencies.auth import (
        get_current_user,
    )

    from app.core.nec_db import (
        get_nec_session,
    )

    from app.services.nec.nec_dependencies import (
        get_sync_engine,
    )

    # Create application.

    fastapi_app = FastAPI()

    # Register NEC routes.

    fastapi_app.include_router(
        nec_sync.router
    )

    # -----------------------------------------
    # Dependency override: NEC sync engine
    # -----------------------------------------

    def override_get_sync_engine():
        return sync_engine

    # -----------------------------------------
    # Dependency override: authenticated user
    # -----------------------------------------

    def override_get_current_user():
        return {
            "user_id": "test-user",
            "is_superuser": True,
        }

    # -----------------------------------------
    # Dependency override: NEC DB session
    # -----------------------------------------

    async def override_get_nec_session():
        yield async_session

    # -----------------------------------------
    # Register dependency overrides
    # -----------------------------------------

    fastapi_app.dependency_overrides[
        get_sync_engine
    ] = override_get_sync_engine

    fastapi_app.dependency_overrides[
        get_nec_session
    ] = override_get_nec_session

    fastapi_app.dependency_overrides[
        get_current_user
    ] = override_get_current_user

    # Handle reimported get_current_user callables
    # that may be registered on the router.

    apply_nec_auth_override(
        fastapi_app,
        override_get_current_user,
    )

    try:

        yield fastapi_app

    finally:

        fastapi_app.dependency_overrides.clear()


# ---------------------------------------------------------
# 12. ASYNC HTTP CLIENT
# ---------------------------------------------------------

@pytest_asyncio.fixture(
    loop_scope="session",
)
async def async_client(nec_app):
    """
    HTTPX client for NEC API tests.
    """

    transport = ASGITransport(
        app=nec_app,
    )

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:

        yield client
