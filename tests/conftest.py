"""
tests/conftest.py

Root-level pytest configuration and shared fixtures.

Strategy:
- Real PostgreSQL database (connection from app.core.database)
- PostgreSQL enum types created idempotently before table creation
- Tables created once per session with checkfirst=True; NOT dropped after session
- All rows deleted between tests in reverse FK order for isolation
- Shared seed fixtures (mission, ew_track) available to all test files
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.main import app as fastapi_app
from app.core.database import Base, SessionLocal, engine, get_db
from app.core.enum import (
    Classification,
    HostilityType,
    PlatformCategoryType,
    SensorRoleType,
    SensorSourceType,
    SensorStatusType,
    SensorType,
    SignalType,
)

# Register all models so Base.metadata includes every table
import app.models.orm_models            # noqa: F401
import app.models.common_models         # noqa: F401
import app.models.ew_track_models       # noqa: F401
import app.models.sensor_status_models  # noqa: F401

_ENUM_TYPES = [
    ("classification_type",       Classification),
    ("signal_type",               SignalType),
    ("hostility_type",            HostilityType),
    ("platform_category_type",    PlatformCategoryType),
    ("sensor_role_type",          SensorRoleType),
    ("sensor_type_enum",          SensorType),
    ("sensor_status_enum",        SensorStatusType),
    ("sensor_status_source_enum", SensorSourceType),
]


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """Create PostgreSQL enum types (idempotent) then create all tables."""
    with engine.begin() as conn:
        for type_name, enum_cls in _ENUM_TYPES:
            values_sql = ", ".join(f"'{v.value}'" for v in enum_cls)
            conn.execute(text(
                f"DO $$ BEGIN "
                f"  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{type_name}') "
                f"  THEN CREATE TYPE {type_name} AS ENUM ({values_sql}); "
                f"  END IF; "
                f"END $$;"
            ))
        # entity_id exists on the real TechPlatformInstance but not in the migration stub
        conn.execute(text(
            "ALTER TABLE tech_platform_instance "
            "ADD COLUMN IF NOT EXISTS entity_id VARCHAR(50) UNIQUE;"
        ))
        # Allow NULL in auto mode (track with no points has no time/position data yet)
        conn.execute(text("""
            ALTER TABLE activity_report_instance
                ALTER COLUMN first_seen_dtg            DROP NOT NULL,
                ALTER COLUMN last_seen_dtg             DROP NOT NULL,
                ALTER COLUMN last_position_longitude_dd DROP NOT NULL,
                ALTER COLUMN last_position_latitude_dd  DROP NOT NULL
        """))
    Base.metadata.create_all(bind=engine, checkfirst=True)
    yield
    # Tables intentionally NOT dropped — keep schema in place for inspection


@pytest.fixture(autouse=True)
def clean_db():
    """Delete all rows between tests in reverse FK order."""
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture()
def db_session():
    session: Session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def client(db_session):
    """TestClient with get_db overridden to use the isolated test session."""
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    with TestClient(fastapi_app, raise_server_exceptions=True) as c:
        yield c
    fastapi_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Shared seed fixtures — used by more than one test file
# ---------------------------------------------------------------------------

CLASSIFICATION = "SECRET"


@pytest.fixture()
def mission(client):
    resp = client.post("/missions", json={
        "name": "Op Thunder",
        "classification": CLASSIFICATION,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture()
def ew_track(client, mission):
    resp = client.post("/ew/tracks", json={
        "source_system": "Thor",
        "source_track_id": "TRK-SEED-001",
        "hostility": "HOSTILE",
        "classification": CLASSIFICATION,
        "mission_id": mission["id"],
    })
    assert resp.status_code == 201, resp.text
    return resp.json()
