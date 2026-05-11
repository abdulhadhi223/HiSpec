"""
tests/ew_track/test_mission.py
Tests for Mission reference endpoints.

Endpoints under test:
  POST  /missions
  GET   /missions
  GET   /missions/{id}
  PATCH /missions/{id}
"""

CLS = "SECRET"
MISSING_UUID = "00000000-0000-0000-0000-000000000000"


class TestMissionCreate:

    def test_create_minimal_returns_201(self, client):
        resp = client.post("/missions", json={"name": "Op Alpha", "classification": CLS})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Op Alpha"
        assert data["id"] is not None

    def test_create_with_time_window(self, client):
        resp = client.post("/missions", json={
            "name": "Op Bravo",
            "classification": CLS,
            "start_at": "2024-06-01T08:00:00Z",
            "end_at":   "2024-06-01T12:00:00Z",
        })
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
        assert client.post("/missions", json={"classification": CLS}).status_code == 422

    def test_create_missing_classification_returns_422(self, client):
        assert client.post("/missions", json={"name": "Op"}).status_code == 422


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

    def test_patch_end_before_start_returns_422(self, client, mission):
        resp = client.patch(f"/missions/{mission['id']}", json={
            "start_at": "2024-07-01T20:00:00Z",
            "end_at":   "2024-07-01T08:00:00Z",
        })
        assert resp.status_code == 422

    def test_patch_not_found_returns_404(self, client):
        assert client.patch(f"/missions/{MISSING_UUID}", json={"name": "X"}).status_code == 404