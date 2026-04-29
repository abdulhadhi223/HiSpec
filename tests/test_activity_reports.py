"""
tests/test_activity_reports.py
Tests for Activity Report endpoints (prefix: /activity-reports).

Endpoints under test:
  POST   /activity-reports
  GET    /activity-reports
  GET    /activity-reports/{id}
  PATCH  /activity-reports/{id}
  DELETE /activity-reports/{id}
  POST   /activity-reports/{report_id}/instances
  GET    /activity-reports/{report_id}/instances
  GET    /activity-reports/{report_id}/instances/{instance_id}
  DELETE /activity-reports/{report_id}/instances/{instance_id}
  POST   /activity-reports/{report_id}/missions/{mission_id}
  GET    /activity-reports/{report_id}/missions
  DELETE /activity-reports/{report_id}/missions/{mission_id}
"""
import pytest

BASE = "/activity-reports"
CLS = "SECRET"
MISSING_UUID = "00000000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _report_payload(**overrides):
    return {"submitted_by": "operator1", "classification": CLS, **overrides}


def _instance_payload(activity_report_id, **overrides):
    return {
        "activity_report_id": activity_report_id,
        "signal_type": "RADAR",
        "hostility": "HOSTILE",
        "first_seen_dtg": "2024-06-01T10:00:00Z",
        "last_seen_dtg":  "2024-06-01T10:30:00Z",
        "last_position_longitude_dd": 54.3773,
        "last_position_latitude_dd":  24.4539,
        "classification": CLS,
        "source_system": "Thor",
        **overrides,
    }


# ===========================================================================
# POST /activity-reports
# ===========================================================================

class TestCreateReport:

    def test_create_minimal_returns_201(self, client):
        resp = client.post(BASE, json=_report_payload())
        assert resp.status_code == 201
        data = resp.json()
        assert data["submitted_by"] == "operator1"
        assert data["classification"] == CLS
        assert data["id"] is not None

    def test_create_with_optional_fields(self, client):
        resp = client.post(BASE, json=_report_payload(
            name="Daily EW Report",
            start_at="2024-06-01T08:00:00Z",
            end_at="2024-06-01T20:00:00Z",
        ))
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Daily EW Report"
        assert "2024-06-01" in data["start_at"]

    def test_create_with_mission_ids(self, client, mission):
        resp = client.post(BASE, json=_report_payload(mission_ids=[mission["id"]]))
        assert resp.status_code == 201

    def test_create_end_before_start_returns_422(self, client):
        resp = client.post(BASE, json=_report_payload(
            start_at="2024-06-01T20:00:00Z",
            end_at="2024-06-01T08:00:00Z",
        ))
        assert resp.status_code == 422

    def test_create_missing_submitted_by_returns_422(self, client):
        resp = client.post(BASE, json={"classification": CLS})
        assert resp.status_code == 422

    def test_create_missing_classification_returns_422(self, client):
        resp = client.post(BASE, json={"submitted_by": "op1"})
        assert resp.status_code == 422

    def test_create_invalid_classification_returns_422(self, client):
        resp = client.post(BASE, json=_report_payload(classification="ULTRA_SECRET"))
        assert resp.status_code == 422


# ===========================================================================
# GET /activity-reports  and  GET /activity-reports/{id}
# ===========================================================================

class TestGetReport:

    def test_list_returns_created_report(self, client, activity_report):
        ids = [r["id"] for r in client.get(BASE).json()]
        assert activity_report["id"] in ids

    def test_list_filter_by_submitted_by(self, client):
        client.post(BASE, json=_report_payload(submitted_by="alice"))
        client.post(BASE, json=_report_payload(submitted_by="bob"))
        results = client.get(BASE, params={"submitted_by": "alice"}).json()
        assert all(r["submitted_by"] == "alice" for r in results)

    def test_list_pagination(self, client):
        for i in range(5):
            client.post(BASE, json=_report_payload(submitted_by=f"op-{i}"))
        resp = client.get(BASE, params={"limit": 3})
        assert resp.status_code == 200
        assert len(resp.json()) <= 3

    def test_get_detail_returns_nested_lists(self, client, activity_report):
        resp = client.get(f"{BASE}/{activity_report['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == activity_report["id"]
        assert "instances" in data
        assert "report_missions" in data

    def test_get_not_found_returns_404(self, client):
        assert client.get(f"{BASE}/{MISSING_UUID}").status_code == 404


# ===========================================================================
# PATCH /activity-reports/{id}
# ===========================================================================

class TestUpdateReport:

    def test_patch_name(self, client, activity_report):
        resp = client.patch(
            f"{BASE}/{activity_report['id']}",
            json={"name": "Updated Report"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Report"

    def test_patch_classification(self, client, activity_report):
        resp = client.patch(
            f"{BASE}/{activity_report['id']}",
            json={"classification": "UNCLASSIFIED"},
        )
        assert resp.status_code == 200
        assert resp.json()["classification"] == "UNCLASSIFIED"

    def test_patch_time_window(self, client, activity_report):
        resp = client.patch(f"{BASE}/{activity_report['id']}", json={
            "start_at": "2024-07-01T06:00:00Z",
            "end_at":   "2024-07-01T18:00:00Z",
        })
        assert resp.status_code == 200

    def test_patch_not_found_returns_404(self, client):
        resp = client.patch(f"{BASE}/{MISSING_UUID}", json={"name": "X"})
        assert resp.status_code == 404


# ===========================================================================
# DELETE /activity-reports/{id}
# ===========================================================================

class TestDeleteReport:

    def test_delete_returns_204(self, client):
        report_id = client.post(BASE, json=_report_payload()).json()["id"]
        assert client.delete(f"{BASE}/{report_id}").status_code == 204

    def test_deleted_report_returns_404(self, client):
        report_id = client.post(BASE, json=_report_payload()).json()["id"]
        client.delete(f"{BASE}/{report_id}")
        assert client.get(f"{BASE}/{report_id}").status_code == 404

    def test_delete_cascades_instances(self, client, activity_report):
        client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(activity_report["id"]),
        )
        client.delete(f"{BASE}/{activity_report['id']}")
        assert client.get(f"{BASE}/{activity_report['id']}").status_code == 404

    def test_delete_not_found_returns_404(self, client):
        assert client.delete(f"{BASE}/{MISSING_UUID}").status_code == 404


# ===========================================================================
# POST /activity-reports/{report_id}/instances
# GET  /activity-reports/{report_id}/instances
# GET  /activity-reports/{report_id}/instances/{instance_id}
# DELETE /activity-reports/{report_id}/instances/{instance_id}
# ===========================================================================

class TestInstances:

    def test_add_instance_returns_201(self, client, activity_report):
        resp = client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(activity_report["id"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["activity_report_id"] == activity_report["id"]
        assert data["signal_type"] == "RADAR"
        assert data["hostility"] == "HOSTILE"

    def test_add_instance_with_track_link(self, client, activity_report, ew_track):
        resp = client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(activity_report["id"], track_id=ew_track["id"]),
        )
        assert resp.status_code == 201
        assert resp.json()["track_id"] == ew_track["id"]

    def test_add_instance_with_all_fields(self, client, activity_report):
        payload = _instance_payload(
            activity_report["id"],
            emitter_name="AN/ALQ-99",
            emitter_confidence=0.85,
            emitter_country_code="RUS",
            platform_category="AIRCRAFT",
            platform_name="Su-35",
            platform_class="Flanker",
            last_position_error_m=100,
        )
        resp = client.post(f"{BASE}/{activity_report['id']}/instances", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["emitter_name"] == "AN/ALQ-99"
        assert data["platform_category"] == "AIRCRAFT"

    def test_duplicate_instance_for_same_track_returns_409(self, client, activity_report, ew_track):
        payload = _instance_payload(activity_report["id"], track_id=ew_track["id"])
        client.post(f"{BASE}/{activity_report['id']}/instances", json=payload)
        resp = client.post(f"{BASE}/{activity_report['id']}/instances", json=payload)
        assert resp.status_code == 409

    def test_add_instance_last_seen_before_first_seen_returns_422(self, client, activity_report):
        resp = client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(
                activity_report["id"],
                first_seen_dtg="2024-06-01T10:30:00Z",
                last_seen_dtg="2024-06-01T09:00:00Z",
            ),
        )
        assert resp.status_code == 422

    def test_invalid_lat_in_instance_returns_422(self, client, activity_report):
        resp = client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(activity_report["id"], last_position_latitude_dd=95.0),
        )
        assert resp.status_code == 422

    def test_invalid_lon_in_instance_returns_422(self, client, activity_report):
        resp = client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(activity_report["id"], last_position_longitude_dd=190.0),
        )
        assert resp.status_code == 422

    def test_list_instances_returns_all(self, client, activity_report):
        for i in range(3):
            client.post(
                f"{BASE}/{activity_report['id']}/instances",
                json=_instance_payload(
                    activity_report["id"],
                    last_position_latitude_dd=24.0 + i * 0.1,
                    first_seen_dtg=f"2024-06-0{i+1}T10:00:00Z",
                    last_seen_dtg=f"2024-06-0{i+1}T11:00:00Z",
                ),
            )
        resp = client.get(f"{BASE}/{activity_report['id']}/instances")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    def test_get_single_instance(self, client, activity_report):
        instance = client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(activity_report["id"]),
        ).json()

        resp = client.get(f"{BASE}/{activity_report['id']}/instances/{instance['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == instance["id"]

    def test_get_instance_wrong_report_returns_404(self, client, activity_report):
        instance = client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(activity_report["id"]),
        ).json()

        resp = client.get(f"{BASE}/{MISSING_UUID}/instances/{instance['id']}")
        assert resp.status_code == 404

    def test_delete_instance_returns_204(self, client, activity_report):
        instance = client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(activity_report["id"]),
        ).json()

        resp = client.delete(f"{BASE}/{activity_report['id']}/instances/{instance['id']}")
        assert resp.status_code == 204


# ===========================================================================
# POST   /activity-reports/{report_id}/missions/{mission_id}
# GET    /activity-reports/{report_id}/missions
# DELETE /activity-reports/{report_id}/missions/{mission_id}
# ===========================================================================

class TestMissionLinks:

    def test_link_mission_returns_201(self, client, activity_report, mission):
        resp = client.post(f"{BASE}/{activity_report['id']}/missions/{mission['id']}")
        assert resp.status_code == 201
        data = resp.json()
        assert data["activity_report_id"] == activity_report["id"]
        assert data["mission_id"] == mission["id"]

    def test_duplicate_link_returns_409(self, client, activity_report, mission):
        client.post(f"{BASE}/{activity_report['id']}/missions/{mission['id']}")
        resp = client.post(f"{BASE}/{activity_report['id']}/missions/{mission['id']}")
        assert resp.status_code == 409

    def test_list_linked_missions(self, client, activity_report, mission):
        client.post(f"{BASE}/{activity_report['id']}/missions/{mission['id']}")
        resp = client.get(f"{BASE}/{activity_report['id']}/missions")
        assert resp.status_code == 200
        mission_ids = [m["mission_id"] for m in resp.json()]
        assert mission["id"] in mission_ids

    def test_unlink_mission_returns_204(self, client, activity_report, mission):
        client.post(f"{BASE}/{activity_report['id']}/missions/{mission['id']}")
        resp = client.delete(f"{BASE}/{activity_report['id']}/missions/{mission['id']}")
        assert resp.status_code == 204

    def test_unlink_not_found_returns_404(self, client, activity_report, mission):
        resp = client.delete(f"{BASE}/{activity_report['id']}/missions/{mission['id']}")
        assert resp.status_code == 404

    def test_list_missions_empty_for_new_report(self, client, activity_report):
        resp = client.get(f"{BASE}/{activity_report['id']}/missions")
        assert resp.status_code == 200
        assert resp.json() == []
