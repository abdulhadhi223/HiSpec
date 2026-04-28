"""
tests/conftest.py
Shared pytest fixtures for NMDB EW Feature API tests.

Strategy:
- SQLite in-memory DB (no live PostgreSQL required)
- gen_random_uuid() registered as a SQLite custom function
- Tables created once per session; all rows deleted between tests (autouse)
- Seed fixtures create data through the API so the full stack is exercised
"""
import uuid as uuid_module

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app as fastapi_app
from app.core.database import Base, get_db

# Import all models so SQLAlchemy registers every table with Base.metadata
import app.models.orm_models       # noqa: F401
import app.models.common_models    # noqa: F401
import app.models.ew_track_models  # noqa: F401

SQLITE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLITE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False,
)


@event.listens_for(engine, "connect")
def _setup_sqlite(dbapi_conn, _):
    """Register gen_random_uuid() and enable FK enforcement in SQLite."""
    dbapi_conn.create_function(
        "gen_random_uuid", 0, lambda: str(uuid_module.uuid4())
    )
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def clean_db():
    """Truncate every table before each test for full isolation."""
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture()
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
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
def sensor(client):
    resp = client.post("/sensors", json={
        "name": "ELINT Sensor 1",
        "type": "ELINT",
        "classification": CLASSIFICATION,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture()
def platform(client):
    resp = client.post("/platforms", json={
        "name": "EW Platform Alpha",
        "category": "aircraft",
        "classification": CLASSIFICATION,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture()
def mission(client):
    resp = client.post("/missions", json={
        "name": "Op Thunder",
        "classification": CLASSIFICATION,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture()
def emitter(client):
    resp = client.post("/emitters", json={
        "emitter_name": "AN/ALQ-99",
        "emitter_country_code": "USA",
        "emitter_country_name": "United States",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture()
def ew_track(client, mission):
    resp = client.post("/ew/tracks", json={
        "source_system": "Thor",
        "source_track_id": "TRK-SEED-001",
        "hostility": "hostile",
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
