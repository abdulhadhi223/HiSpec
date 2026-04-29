"""
tests/conftest.py
Shared pytest fixtures for NMDB EW Feature API tests.

Strategy:
- Real PostgreSQL database (connection from app.core.config / app.core.database)
- PostgreSQL enum types created idempotently before table creation
- Tables created once per session with checkfirst=True; NOT dropped after session
- All rows deleted between tests for isolation (reverse FK order)
- Seed fixtures create data through the API so the full stack is exercised
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
    SignalType,
)

# Register all models so Base.metadata includes every table
import app.models.orm_models       # noqa: F401
import app.models.common_models    # noqa: F401
import app.models.ew_track_models  # noqa: F401

_ENUM_TYPES = [
    ("classification_type", Classification),
    ("signal_type", SignalType),
    ("hostility_type", HostilityType),
    ("platform_category_type", PlatformCategoryType),
    ("sensor_role_type", SensorRoleType),
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
def db():
    session: Session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def client(db):
    """TestClient with get_db overridden to use the isolated test session."""
    def _override_get_db():
        try:
            yield db
        finally:
            pass

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    with TestClient(fastapi_app, raise_server_exceptions=True) as c:
        yield c
    fastapi_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# API-level seed fixtures — create data through the API so the full
# request/validation/service stack is exercised in every test.
# ---------------------------------------------------------------------------

CLASSIFICATION = "SECRET"


@pytest.fixture()
def sensor_catalog(db):
    """SensorCatalog — used by EWTrackPointSensor tests."""
    from app.models.orm_models import SensorCatalog
    entry = SensorCatalog()
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {"id": str(entry.id)}


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


@pytest.fixture()
def track_point(client, ew_track):
    resp = client.post(f"/ew/tracks/{ew_track['id']}/points", json={
        "observed_at": "2024-06-01T10:00:00Z",
        "lat": 24.4539,
        "lon": 54.3773,
        "error_m": 50.0,
        "classification": CLASSIFICATION,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture()
def activity_report(client):
    resp = client.post("/activity-reports", json={
        "submitted_by": "operator1",
        "classification": CLASSIFICATION,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()
