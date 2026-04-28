"""
tests/test_reference.py
Tests for all Reference Data endpoints (User Story 2).

Endpoints under test:
  POST  /sensors        GET /sensors       GET /sensors/{key}   PATCH /sensors/{key}
  POST  /platforms      GET /platforms     GET /platforms/{id}  PATCH /platforms/{id}
  POST  /missions       GET /missions      GET /missions/{id}   PATCH /missions/{id}
  POST  /emitters       GET /emitters      GET /emitters/{key}  PATCH /emitters/{key}
"""
import pytest

CLS = "SECRET"
MISSING_UUID = "00000000-0000-0000-0000-000000000000"
MISSING_INT = 999999


# ===========================================================================
# Sensors  —  key: UUID  (catalog convention)
# ===========================================================================

class TestSensorCreate:

    def test_create_returns_201_with_uuid_key(self, client):
        resp = client.post("/sensors", json={"name": "Sensor-A", "type": "ELINT", "classification": CLS})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Sensor-A"
        assert data["type"] == "ELINT"
        assert "key" in data                # UUID public identifier
        assert "id" not in data             # internal int PK not exposed

    def test_create_missing_name_returns_422(self, client):
        resp = client.post("/sensors", json={"type": "ELINT", "classification": CLS})
        assert resp.status_code == 422

    def test_create_missing_type_returns_422(self, client):
        resp = client.post("/sensors", json={"name": "X", "classification": CLS})
        assert resp.status_code == 422

    def test_create_missing_classification_returns_422(self, client):
        resp = client.post("/sensors", json={"name": "X", "type": "ELINT"})
        assert resp.status_code == 422

    def test_create_invalid_classification_returns_422(self, client):
        resp = client.post("/sensors", json={"name": "X", "type": "ELINT", "classification": "EYES_ONLY"})
        assert resp.status_code == 422


class TestSensorRead:

    def test_list_returns_created_sensor(self, client, sensor):
        keys = [s["key"] for s in client.get("/sensors").json()]
        assert sensor["key"] in keys

    def test_list_pagination(self, client):
        for i in range(4):
            client.post("/sensors", json={"name": f"S-{i}", "type": "ELINT", "classification": CLS})
        resp = client.get("/sensors", params={"limit": 2})
        assert resp.status_code == 200
        assert len(resp.json()) <= 2

    def test_get_by_key_returns_200(self, client, sensor):
        resp = client.get(f"/sensors/{sensor['key']}")
        assert resp.status_code == 200
        assert resp.json()["key"] == sensor["key"]

    def test_get_not_found_returns_404(self, client):
        assert client.get(f"/sensors/{MISSING_UUID}").status_code == 404


class TestSensorUpdate:

    def test_patch_name(self, client, sensor):
        resp = client.patch(f"/sensors/{sensor['key']}", json={"name": "Updated-Sensor"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated-Sensor"

    def test_patch_type(self, client, sensor):
        resp = client.patch(f"/sensors/{sensor['key']}", json={"type": "SIGINT"})
        assert resp.status_code == 200
        assert resp.json()["type"] == "SIGINT"

    def test_patch_classification(self, client, sensor):
        resp = client.patch(f"/sensors/{sensor['key']}", json={"classification": "UNCLASSIFIED"})
        assert resp.status_code == 200
        assert resp.json()["classification"] == "UNCLASSIFIED"

    def test_patch_empty_body_no_op(self, client, sensor):
        resp = client.patch(f"/sensors/{sensor['key']}", json={})
        assert resp.status_code == 200
        assert resp.json()["name"] == sensor["name"]  # unchanged

    def test_patch_not_found_returns_404(self, client):
        resp = client.patch(f"/sensors/{MISSING_UUID}", json={"name": "X"})
        assert resp.status_code == 404


# ===========================================================================
# Platforms  —  id: Integer
# ===========================================================================

class TestPlatformCreate:

    def test_create_minimal_returns_201(self, client):
        resp = client.post("/platforms", json={"classification": CLS})
        assert resp.status_code == 201
        assert "id" in resp.json()

    def test_create_full_returns_201(self, client):
        payload = {
            "name": "F-16 Block 52",
            "category": "aircraft",
            "platform_country_code": "USA",
            "platform_country_name": "United States",
            "classification": CLS,
        }
        resp = client.post("/platforms", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "F-16 Block 52"
        assert data["category"] == "aircraft"
        assert data["platform_country_code"] == "USA"

    def test_create_missing_classification_returns_422(self, client):
        resp = client.post("/platforms", json={"name": "X"})
        assert resp.status_code == 422

    def test_create_invalid_category_returns_422(self, client):
        resp = client.post("/platforms", json={"classification": CLS, "category": "spaceship"})
        assert resp.status_code == 422


class TestPlatformRead:

    def test_list_returns_created_platform(self, client, platform):
        ids = [p["id"] for p in client.get("/platforms").json()]
        assert platform["id"] in ids

    def test_get_by_id_returns_200(self, client, platform):
        resp = client.get(f"/platforms/{platform['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == platform["id"]

    def test_get_not_found_returns_404(self, client):
        assert client.get(f"/platforms/{MISSING_INT}").status_code == 404


class TestPlatformUpdate:

    def test_patch_name(self, client, platform):
        resp = client.patch(f"/platforms/{platform['id']}", json={"name": "Updated Platform"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Platform"

    def test_patch_category(self, client, platform):
        resp = client.patch(f"/platforms/{platform['id']}", json={"category": "surface"})
        assert resp.status_code == 200
        assert resp.json()["category"] == "surface"

    def test_patch_country_fields(self, client, platform):
        resp = client.patch(
            f"/platforms/{platform['id']}",
            json={"platform_country_code": "GBR", "platform_country_name": "United Kingdom"},
        )
        assert resp.status_code == 200
        assert resp.json()["platform_country_code"] == "GBR"

    def test_patch_not_found_returns_404(self, client):
        resp = client.patch(f"/platforms/{MISSING_INT}", json={"name": "X"})
        assert resp.status_code == 404


# ===========================================================================
# Missions  —  id: UUID
# ===========================================================================

class TestMissionCreate:

    def test_create_minimal_returns_201(self, client):
        resp = client.post("/missions", json={"name": "Op Alpha", "classification": CLS})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Op Alpha"
        assert data["id"] is not None

    def test_create_with_time_window(self, client):
        payload = {
            "name": "Op Bravo",
            "classification": CLS,
            "start_at": "2024-06-01T08:00:00Z",
            "end_at":   "2024-06-01T20:00:00Z",
        }
        resp = client.post("/missions", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert "2024-06-01" in data["start_at"]
        assert "2024-06-01" in data["end_at"]

    def test_create_end_before_start_returns_422(self, client):
        resp = client.post("/missions", json={
            "name": "Bad",
            "classification": CLS,
            "start_at": "2024-06-01T20:00:00Z",
            "end_at":   "2024-06-01T08:00:00Z",
        })
        assert resp.status_code == 422

    def test_create_missing_name_returns_422(self, client):
        resp = client.post("/missions", json={"classification": CLS})
        assert resp.status_code == 422

    def test_create_missing_classification_returns_422(self, client):
        resp = client.post("/missions", json={"name": "Op"})
        assert resp.status_code == 422


class TestMissionRead:

    def test_list_returns_created_mission(self, client, mission):
        ids = [m["id"] for m in client.get("/missions").json()]
        assert mission["id"] in ids

    def test_list_pagination(self, client):
        for i in range(4):
            client.post("/missions", json={"name": f"M-{i}", "classification": CLS})
        resp = client.get("/missions", params={"skip": 0, "limit": 2})
        assert resp.status_code == 200
        assert len(resp.json()) <= 2

    def test_get_by_id_returns_200(self, client, mission):
        resp = client.get(f"/missions/{mission['id']}")
        assert resp.status_code == 200
        assert resp.json()["name"] == mission["name"]

    def test_get_not_found_returns_404(self, client):
        assert client.get(f"/missions/{MISSING_UUID}").status_code == 404


class TestMissionUpdate:

    def test_patch_name(self, client, mission):
        resp = client.patch(f"/missions/{mission['id']}", json={"name": "Op Charlie"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Op Charlie"

    def test_patch_classification(self, client, mission):
        resp = client.patch(f"/missions/{mission['id']}", json={"classification": "UNCLASSIFIED"})
        assert resp.status_code == 200
        assert resp.json()["classification"] == "UNCLASSIFIED"

    def test_patch_both_times_valid(self, client, mission):
        resp = client.patch(f"/missions/{mission['id']}", json={
            "start_at": "2024-07-01T08:00:00Z",
            "end_at":   "2024-07-01T18:00:00Z",
        })
        assert resp.status_code == 200

    def test_patch_end_before_start_in_payload_returns_422(self, client, mission):
        resp = client.patch(f"/missions/{mission['id']}", json={
            "start_at": "2024-07-01T20:00:00Z",
            "end_at":   "2024-07-01T08:00:00Z",
        })
        assert resp.status_code == 422

    def test_patch_not_found_returns_404(self, client):
        resp = client.patch(f"/missions/{MISSING_UUID}", json={"name": "X"})
        assert resp.status_code == 404


# ===========================================================================
# Emitters  —  key: UUID  (catalog convention)
# ===========================================================================

class TestEmitterCreate:

    def test_create_all_optional_fields_returns_201(self, client):
        resp = client.post("/emitters", json={})
        assert resp.status_code == 201
        assert "key" in resp.json()

    def test_create_with_fields_returns_201(self, client):
        payload = {
            "emitter_name": "AN/ALQ-99",
            "emitter_country_code": "USA",
            "emitter_country_name": "United States",
            "emitter_id_sensor": 42,
        }
        resp = client.post("/emitters", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["emitter_name"] == "AN/ALQ-99"
        assert data["emitter_country_code"] == "USA"

    def test_country_code_over_3_chars_returns_422(self, client):
        resp = client.post("/emitters", json={"emitter_country_code": "USAA"})
        assert resp.status_code == 422


class TestEmitterRead:

    def test_list_returns_created_emitter(self, client, emitter):
        keys = [e["key"] for e in client.get("/emitters").json()]
        assert emitter["key"] in keys

    def test_get_by_key_returns_200(self, client, emitter):
        resp = client.get(f"/emitters/{emitter['key']}")
        assert resp.status_code == 200
        assert resp.json()["key"] == emitter["key"]

    def test_get_not_found_returns_404(self, client):
        assert client.get(f"/emitters/{MISSING_UUID}").status_code == 404


class TestEmitterUpdate:

    def test_patch_name(self, client, emitter):
        resp = client.patch(f"/emitters/{emitter['key']}", json={"emitter_name": "Updated Emitter"})
        assert resp.status_code == 200
        assert resp.json()["emitter_name"] == "Updated Emitter"

    def test_patch_country(self, client, emitter):
        resp = client.patch(f"/emitters/{emitter['key']}", json={
            "emitter_country_code": "GBR",
            "emitter_country_name": "United Kingdom",
        })
        assert resp.status_code == 200
        assert resp.json()["emitter_country_code"] == "GBR"

    def test_patch_sensor_id(self, client, emitter):
        resp = client.patch(f"/emitters/{emitter['key']}", json={"emitter_id_sensor": 99})
        assert resp.status_code == 200
        assert resp.json()["emitter_id_sensor"] == 99

    def test_patch_not_found_returns_404(self, client):
        resp = client.patch(f"/emitters/{MISSING_UUID}", json={"emitter_name": "X"})
        assert resp.status_code == 404
