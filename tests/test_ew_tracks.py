"""
tests/ew_track/test_ew_tracks.py
Tests for EW Track endpoints (prefix: /ew).

Endpoints under test:
  POST   /ew/tracks              POST   /ew/tracks/upsert
  GET    /ew/tracks              GET    /ew/tracks/{id}
  PATCH  /ew/tracks/{id}         DELETE /ew/tracks/{id}
  POST   /ew/tracks/{id}/points  GET    /ew/tracks/{id}/points
  POST   /ew/points/{id}/sensors
  POST   /ew/tracks/{id}/emitters
  GET    /ew/tracks/{id}/emitters

Fixtures from conftest.py: client, mission, ew_track
Fixtures defined here:     track_point, sensor_catalog
"""
import uuid

import pytest
from sqlalchemy import text

BASE = "/ew/tracks"
CLS = "SECRET"


# ---------------------------------------------------------------------------
# Fixtures — only used in this file
# ---------------------------------------------------------------------------

@pytest.fixture()
def sensor_catalog(db_session):
    new_id = uuid.uuid4()
    db_session.execute(
        text("INSERT INTO sensor_catalog (id) VALUES (:id)"),
        {"id": new_id},
    )
    db_session.flush()
    return {"id": str(new_id)}


@pytest.fixture()
def track_point(client, ew_track):
    resp = client.post(f"{BASE}/{ew_track['id']}/points", json={
        "observed_at": "2024-06-01T10:00:00Z",
        "lat": 24.4539,
        "lon": 54.3773,
        "error_m": 50.0,
        "classification": CLS,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _track_payload(**overrides):
    return {
        "source_system": "Thor",
        "source_track_id": "TRK-001",
        "hostility": "HOSTILE",
        "classification": CLS,
        **overrides,
    }


def _point_payload(**overrides):
    return {
        "observed_at": "2024-06-01T10:00:00Z",
        "lat": 24.4539,
        "lon": 54.3773,
        "classification": CLS,
        **overrides,
    }


def _emitter_payload(**overrides):
    return {
        "first_seen_at": "2024-06-01T10:00:00Z",
        "last_seen_at":  "2024-06-01T10:30:00Z",
        "signal_type":   "RADAR",
        "emitter_mode":  "search",
        **overrides,
    }


# ---------------------------------------------------------------------------
# POST /ew/tracks
# ---------------------------------------------------------------------------

class TestCreateTrack:

    def test_create_minimal(self, client):
        resp = client.post(BASE, json=_track_payload())
        assert resp.status_code == 201
        data = resp.json()
        assert data["source_system"] == "Thor"
        assert data["hostility"] == "HOSTILE"
        assert data["classification"] == CLS
        assert data["id"] is not None

    def test_create_with_mission(self, client, mission):
        resp = client.post(BASE, json=_track_payload(mission_id=mission["id"]))
        assert resp.status_code == 201
        assert resp.json()["mission_id"] == mission["id"]

    def test_create_duplicate_source_key_returns_409(self, client):
        client.post(BASE, json=_track_payload())
        assert client.post(BASE, json=_track_payload()).status_code == 409

    def test_create_missing_source_system_returns_422(self, client):
        assert client.post(BASE, json={"hostility": "HOSTILE", "classification": CLS}).status_code == 422

    def test_create_missing_hostility_returns_422(self, client):
        assert client.post(BASE, json={"source_system": "Thor", "classification": CLS}).status_code == 422

    def test_create_invalid_hostility_enum_returns_422(self, client):
        assert client.post(BASE, json=_track_payload(hostility="INVALID")).status_code == 422

    def test_create_invalid_classification_enum_returns_422(self, client):
        assert client.post(BASE, json=_track_payload(classification="TOP_MOST_SECRET")).status_code == 422


# ---------------------------------------------------------------------------
# POST /ew/tracks/upsert
# ---------------------------------------------------------------------------

class TestUpsertTrack:

    def test_upsert_creates_new(self, client):
        resp = client.post(f"{BASE}/upsert", json=_track_payload())
        assert resp.status_code == 200
        assert resp.json()["id"] is not None

    def test_upsert_updates_existing(self, client):
        client.post(f"{BASE}/upsert", json=_track_payload(hostility="FRIENDLY"))
        resp = client.post(f"{BASE}/upsert", json=_track_payload(hostility="HOSTILE"))
        assert resp.status_code == 200
        assert resp.json()["hostility"] == "HOSTILE"

    def test_upsert_same_source_key_returns_same_id(self, client):
        r1 = client.post(f"{BASE}/upsert", json=_track_payload())
        r2 = client.post(f"{BASE}/upsert", json=_track_payload())
        assert r1.json()["id"] == r2.json()["id"]


# ---------------------------------------------------------------------------
# GET /ew/tracks  and  GET /ew/tracks/{id}
# ---------------------------------------------------------------------------

class TestGetTrack:

    def test_get_existing_returns_200(self, client, ew_track):
        resp = client.get(f"{BASE}/{ew_track['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == ew_track["id"]

    def test_get_detail_includes_nested_lists(self, client, ew_track):
        data = client.get(f"{BASE}/{ew_track['id']}").json()
        assert isinstance(data["track_points"], list)
        assert isinstance(data["track_emitters"], list)

    def test_get_not_found_returns_404(self, client):
        assert client.get(f"{BASE}/00000000-0000-0000-0000-000000000000").status_code == 404


class TestListTracks:

    def test_list_returns_created_track(self, client, ew_track):
        ids = [t["id"] for t in client.get(BASE).json()]
        assert ew_track["id"] in ids

    def test_filter_by_source_system(self, client):
        client.post(BASE, json=_track_payload(source_system="Thor",    source_track_id="F-TRK-1"))
        client.post(BASE, json=_track_payload(source_system="Trident", source_track_id="F-TRK-2"))
        results = client.get(BASE, params={"source_system": "Thor"}).json()
        assert all(t["source_system"] == "Thor" for t in results)

    def test_filter_by_mission_id(self, client, mission):
        client.post(BASE, json=_track_payload(mission_id=mission["id"], source_track_id="M-TRK"))
        results = client.get(BASE, params={"mission_id": mission["id"]}).json()
        assert all(t["mission_id"] == mission["id"] for t in results)

    def test_pagination_limit(self, client):
        for i in range(5):
            client.post(BASE, json=_track_payload(source_track_id=f"PAG-{i}"))
        assert len(client.get(BASE, params={"limit": 3}).json()) <= 3

    def test_pagination_skip(self, client):
        for i in range(4):
            client.post(BASE, json=_track_payload(source_track_id=f"SKIP-{i}"))
        total = len(client.get(BASE).json())
        paged = len(client.get(BASE, params={"skip": 2}).json())
        assert paged == total - 2


# ---------------------------------------------------------------------------
# PATCH /ew/tracks/{id}
# ---------------------------------------------------------------------------

class TestUpdateTrack:

    def test_patch_hostility(self, client, ew_track):
        resp = client.patch(f"{BASE}/{ew_track['id']}", json={"hostility": "FRIENDLY"})
        assert resp.status_code == 200
        assert resp.json()["hostility"] == "FRIENDLY"

    def test_patch_classification(self, client, ew_track):
        resp = client.patch(f"{BASE}/{ew_track['id']}", json={"classification": "UNCLASSIFIED"})
        assert resp.status_code == 200
        assert resp.json()["classification"] == "UNCLASSIFIED"

    def test_patch_mission_id(self, client, ew_track, mission):
        resp = client.patch(f"{BASE}/{ew_track['id']}", json={"mission_id": mission["id"]})
        assert resp.status_code == 200
        assert resp.json()["mission_id"] == mission["id"]

    def test_patch_invalid_enum_returns_422(self, client, ew_track):
        assert client.patch(f"{BASE}/{ew_track['id']}", json={"hostility": "NOPE"}).status_code == 422

    def test_patch_not_found_returns_404(self, client):
        assert client.patch(
            f"{BASE}/00000000-0000-0000-0000-000000000000",
            json={"hostility": "NEUTRAL"},
        ).status_code == 404


# ---------------------------------------------------------------------------
# DELETE /ew/tracks/{id}
# ---------------------------------------------------------------------------

class TestDeleteTrack:

    def test_delete_returns_204(self, client):
        track_id = client.post(BASE, json=_track_payload(source_track_id="DEL-1")).json()["id"]
        assert client.delete(f"{BASE}/{track_id}").status_code == 204

    def test_deleted_track_returns_404(self, client):
        track_id = client.post(BASE, json=_track_payload(source_track_id="DEL-2")).json()["id"]
        client.delete(f"{BASE}/{track_id}")
        assert client.get(f"{BASE}/{track_id}").status_code == 404

    def test_delete_not_found_returns_404(self, client):
        assert client.delete(f"{BASE}/00000000-0000-0000-0000-000000000000").status_code == 404

    def test_delete_cascades_track_points(self, client, ew_track, track_point):
        client.delete(f"{BASE}/{ew_track['id']}")
        assert client.get(f"{BASE}/{ew_track['id']}").status_code == 404


# ---------------------------------------------------------------------------
# Track Points
# ---------------------------------------------------------------------------

class TestTrackPoints:

    def test_append_point_returns_201(self, client, ew_track):
        resp = client.post(f"{BASE}/{ew_track['id']}/points", json=_point_payload())
        assert resp.status_code == 201
        data = resp.json()
        assert data["track_id"] == ew_track["id"]
        assert data["lat"] == pytest.approx(24.4539)
        assert data["lon"] == pytest.approx(54.3773)

    def test_append_point_with_error_m(self, client, ew_track):
        resp = client.post(f"{BASE}/{ew_track['id']}/points", json=_point_payload(error_m=100.0))
        assert resp.status_code == 201
        assert resp.json()["error_m"] == pytest.approx(100.0)

    def test_duplicate_point_returns_409(self, client, ew_track):
        client.post(f"{BASE}/{ew_track['id']}/points", json=_point_payload())
        assert client.post(f"{BASE}/{ew_track['id']}/points", json=_point_payload()).status_code == 409

    def test_invalid_lat_too_high_returns_422(self, client, ew_track):
        assert client.post(f"{BASE}/{ew_track['id']}/points", json=_point_payload(lat=91.0)).status_code == 422

    def test_invalid_lat_too_low_returns_422(self, client, ew_track):
        assert client.post(f"{BASE}/{ew_track['id']}/points", json=_point_payload(lat=-91.0)).status_code == 422

    def test_invalid_lon_too_high_returns_422(self, client, ew_track):
        assert client.post(f"{BASE}/{ew_track['id']}/points", json=_point_payload(lon=181.0)).status_code == 422

    def test_invalid_lon_too_low_returns_422(self, client, ew_track):
        assert client.post(f"{BASE}/{ew_track['id']}/points", json=_point_payload(lon=-181.0)).status_code == 422

    def test_negative_error_m_returns_422(self, client, ew_track):
        assert client.post(f"{BASE}/{ew_track['id']}/points", json=_point_payload(error_m=-1.0)).status_code == 422

    def test_missing_classification_returns_422(self, client, ew_track):
        payload = {k: v for k, v in _point_payload().items() if k != "classification"}
        assert client.post(f"{BASE}/{ew_track['id']}/points", json=payload).status_code == 422

    def test_missing_observed_at_returns_422(self, client, ew_track):
        payload = {k: v for k, v in _point_payload().items() if k != "observed_at"}
        assert client.post(f"{BASE}/{ew_track['id']}/points", json=payload).status_code == 422

    def test_list_points_ordered_by_observed_at(self, client, ew_track):
        timestamps = [
            "2024-06-01T12:00:00Z",
            "2024-06-01T09:00:00Z",
            "2024-06-01T11:00:00Z",
        ]
        for i, ts in enumerate(timestamps):
            client.post(
                f"{BASE}/{ew_track['id']}/points",
                json=_point_payload(observed_at=ts, lat=24.0 + i * 0.1),
            )
        pts = client.get(f"{BASE}/{ew_track['id']}/points").json()
        ts_list = [p["observed_at"] for p in pts]
        assert ts_list == sorted(ts_list)

    def test_list_points_returns_empty_for_new_track(self, client, ew_track):
        assert client.get(f"{BASE}/{ew_track['id']}/points").json() == []


# ---------------------------------------------------------------------------
# Track Point Sensors
# ---------------------------------------------------------------------------

class TestTrackPointSensors:

    def test_link_sensor_to_point_returns_201(self, client, track_point, sensor_catalog):
        resp = client.post(
            f"/ew/points/{track_point['id']}/sensors",
            json={"sensor_catalog_id": sensor_catalog["id"], "role": "ORIGIN"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["point_id"] == track_point["id"]
        assert data["sensor_catalog_id"] == sensor_catalog["id"]

    def test_duplicate_sensor_link_returns_409(self, client, track_point, sensor_catalog):
        client.post(f"/ew/points/{track_point['id']}/sensors",
                    json={"sensor_catalog_id": sensor_catalog["id"]})
        assert client.post(
            f"/ew/points/{track_point['id']}/sensors",
            json={"sensor_catalog_id": sensor_catalog["id"]},
        ).status_code == 409

    def test_link_sensor_with_role(self, client, track_point, sensor_catalog):
        resp = client.post(
            f"/ew/points/{track_point['id']}/sensors",
            json={"sensor_catalog_id": sensor_catalog["id"], "role": "ORIGIN"},
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "ORIGIN"


# ---------------------------------------------------------------------------
# Track Emitters
# ---------------------------------------------------------------------------

class TestTrackEmitters:

    def test_upsert_emitter_creates_new(self, client, ew_track):
        resp = client.post(f"{BASE}/{ew_track['id']}/emitters", json=_emitter_payload())
        assert resp.status_code == 201
        data = resp.json()
        assert data["track_id"] == ew_track["id"]
        assert data["signal_type"] == "RADAR"
        assert data["emitter_mode"] == "search"

    def test_upsert_emitter_with_identity_fields(self, client, ew_track):
        resp = client.post(f"{BASE}/{ew_track['id']}/emitters", json=_emitter_payload(
            emitter_id_sensor="42",
            emitter_name="AN/ALQ-99",
            emitter_country_code="USA",
            emitter_country_name="United States",
        ))
        assert resp.status_code == 201
        data = resp.json()
        assert data["emitter_name"] == "AN/ALQ-99"
        assert data["emitter_country_code"] == "USA"
        assert data["emitter_id_sensor"] == "42"

    def test_upsert_emitter_updates_existing(self, client, ew_track):
        client.post(f"{BASE}/{ew_track['id']}/emitters", json=_emitter_payload(emitter_confidence=0.5))
        resp = client.post(f"{BASE}/{ew_track['id']}/emitters", json=_emitter_payload(emitter_confidence=0.9))
        assert resp.status_code == 201
        assert resp.json()["emitter_confidence"] == pytest.approx(0.9)

    def test_upsert_emitter_with_rf_parameters(self, client, ew_track):
        resp = client.post(f"{BASE}/{ew_track['id']}/emitters", json=_emitter_payload(
            freq_low_mhz=9000.0, freq_high_mhz=9500.0, freq_center_mhz=9250.0,
            pulse_width_low_us=0.5, pulse_width_center_us=1.0,
            pri_low_us=1.0, pri_high_us=2.0, pri_center_us=1.5,
        ))
        assert resp.status_code == 201
        data = resp.json()
        assert data["freq_center_mhz"] == pytest.approx(9250.0)
        assert data["pri_center_us"] == pytest.approx(1.5)

    def test_invalid_confidence_over_1_returns_422(self, client, ew_track):
        assert client.post(f"{BASE}/{ew_track['id']}/emitters",
                           json=_emitter_payload(emitter_confidence=1.5)).status_code == 422

    def test_invalid_confidence_negative_returns_422(self, client, ew_track):
        assert client.post(f"{BASE}/{ew_track['id']}/emitters",
                           json=_emitter_payload(emitter_confidence=-0.1)).status_code == 422

    def test_list_emitters_for_track(self, client, ew_track):
        client.post(f"{BASE}/{ew_track['id']}/emitters", json=_emitter_payload())
        resp = client.get(f"{BASE}/{ew_track['id']}/emitters")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_list_emitters_empty_for_new_track(self, client, ew_track):
        assert client.get(f"{BASE}/{ew_track['id']}/emitters").json() == []