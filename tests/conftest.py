"""
tests/ew_track/conftest.py

Shared seed fixtures for the ew_track test package.
Only fixtures used by MORE THAN ONE test file live here.

Fixtures from tests/conftest.py available automatically:
    test_engine, db_session, app, client
"""
import pytest

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