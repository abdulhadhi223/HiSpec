"""
Tests for Activity Report endpoints (prefix: /activity-reports).

Endpoints under test:
  POST/GET/PATCH/DELETE /activity-reports
  POST/GET/DELETE       /activity-reports/{id}/instances
  GET                   /activity-reports/{id}/instances/{instance_id}
  POST/GET/DELETE       /activity-reports/{id}/missions/{mission_id}

Fixtures from conftest.py: client, mission, ew_track
Fixtures defined here:     activity_report
"""
import pytest

BASE = "/activity-reports"
CLS = "SECRET"
MISSING_UUID = "00000000-0000-0000-0000-000000000000"


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures — only used in this file
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def activity_report(client):
    resp = client.post(
        BASE, json={"submitted_by": "operator1", "classification": CLS}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _report_payload(**overrides):
    return {"submitted_by": "operator1", "classification": CLS, **overrides}


def _instance_payload(activity_report_id, **overrides):
    return {
        "activity_report_id": activity_report_id,
        "signal_type": "RADAR",
        "hostility": "HOSTILE",
        "first_seen_dtg": "2024-06-01T10:00:00Z",
        "last_seen_dtg": "2024-06-01T10:30:00Z",
        "last_position_longitude_dd": 54.3773,
        "last_position_latitude_dd": 24.4539,
        "classification": CLS,
        "source_system": "Thor",
        **overrides,
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /activity-reports
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateReport:
    def test_create_minimal_returns_201(self, client):
        resp = client.post(BASE, json=_report_payload())
        assert resp.status_code == 201
        data = resp.json()
        assert data["submitted_by"] == "operator1"
        assert data["id"] is not None

    def test_create_with_name(self, client):
        resp = client.post(
            BASE, json=_report_payload(name="Daily EW Report")
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "Daily EW Report"

    def test_create_with_time_window(self, client):
        resp = client.post(
            BASE,
            json=_report_payload(
                start_at="2024-06-01T08:00:00Z",
                end_at="2024-06-01T20:00:00Z",
            ),
        )
        assert resp.status_code == 201

    def test_create_with_mission_ids(self, client, mission):
        resp = client.post(
            BASE, json=_report_payload(mission_ids=[mission["id"]])
        )
        assert resp.status_code == 201

    def test_create_end_before_start_returns_422(self, client):
        resp = client.post(
            BASE,
            json=_report_payload(
                start_at="2024-06-01T20:00:00Z",
                end_at="2024-06-01T08:00:00Z",
            ),
        )
        assert resp.status_code == 422

    def test_create_missing_submitted_by_returns_422(self, client):
        assert (
            client.post(BASE, json={"classification": CLS}).status_code
            == 422
        )

    def test_create_missing_classification_returns_422(self, client):
        assert (
            client.post(
                BASE, json={"submitted_by": "op1"}
            ).status_code
            == 422
        )

    def test_create_invalid_classification_returns_422(self, client):
        assert (
            client.post(
                BASE, json=_report_payload(classification="ULTRA_SECRET")
            ).status_code
            == 422
        )


# ─────────────────────────────────────────────────────────────────────────────
# GET /activity-reports
# ─────────────────────────────────────────────────────────────────────────────


class TestGetReport:
    def test_list_returns_created_report(self, client, activity_report):
        ids = [r["id"] for r in client.get(BASE).json()]
        assert activity_report["id"] in ids

    def test_list_filter_by_submitted_by(self, client):
        client.post(BASE, json=_report_payload(submitted_by="alice"))
        client.post(BASE, json=_report_payload(submitted_by="bob"))
        results = client.get(
            BASE, params={"submitted_by": "alice"}
        ).json()
        assert all(r["submitted_by"] == "alice" for r in results)

    def test_list_pagination(self, client):
        for i in range(5):
            client.post(BASE, json=_report_payload(submitted_by=f"op-{i}"))
        assert len(client.get(BASE, params={"limit": 3}).json()) <= 3

    def test_list_filter_by_date_range(self, client):
        client.post(
            BASE,
            json=_report_payload(
                start_at="2024-06-01T08:00:00Z",
                end_at="2024-06-01T20:00:00Z",
            ),
        )
        client.post(
            BASE,
            json=_report_payload(
                start_at="2024-08-01T08:00:00Z",
                end_at="2024-08-01T20:00:00Z",
            ),
        )
        results = client.get(
            BASE,
            params={
                "from_dt": "2024-06-01T08:00:00Z",
                "to_dt": "2024-06-30T23:59:00Z",
            },
        ).json()
        assert len(results) >= 1
        assert all(
            r["start_at"] >= "2024-06-01T00:00:00Z" for r in results
        )

    def test_list_from_dt_after_to_dt_returns_422(self, client):
        resp = client.get(
            BASE,
            params={
                "from_dt": "2024-06-30T00:00:00Z",
                "to_dt": "2024-06-01T00:00:00Z",
            },
        )
        assert resp.status_code == 422

    def test_list_filter_by_mission_id(self, client, mission):
        client.post(
            BASE, json=_report_payload(mission_ids=[mission["id"]])
        )
        client.post(BASE, json=_report_payload())
        results = client.get(
            BASE, params={"mission_id": mission["id"]}
        ).json()
        assert len(results) >= 1
        assert all(
            mission["id"]
            in [
                m["mission_id"]
                for m in client.get(
                    f"{BASE}/{r['id']}/missions"
                ).json()
            ]
            for r in results
        )

    def test_list_filter_no_match_returns_empty(self, client):
        assert (
            client.get(
                BASE,
                params={
                    "from_dt": "2066-06-01T08:00:00Z",
                    "to_dt": "2066-06-01T20:00:00Z",
                },
            ).json()
            == []
        )

    def test_get_detail_returns_nested_lists(
        self, client, activity_report
    ):
        resp = client.get(f"{BASE}/{activity_report['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert "instances" in data
        assert "report_missions" in data

    def test_get_not_found_returns_404(self, client):
        assert (
            client.get(f"{BASE}/{MISSING_UUID}").status_code == 404
        )


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /activity-reports/{id}
# ─────────────────────────────────────────────────────────────────────────────


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
        resp = client.patch(
            f"{BASE}/{activity_report['id']}",
            json={
                "start_at": "2024-07-01T06:00:00Z",
                "end_at": "2024-07-01T18:00:00Z",
            },
        )
        assert resp.status_code == 200

    def test_patch_not_found_returns_404(self, client):
        assert (
            client.patch(
                f"{BASE}/{MISSING_UUID}", json={"name": "X"}
            ).status_code
            == 404
        )


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /activity-reports/{id}
# ─────────────────────────────────────────────────────────────────────────────


class TestDeleteReport:
    def test_delete_returns_204(self, client):
        report_id = client.post(
            BASE, json=_report_payload()
        ).json()["id"]
        assert client.delete(f"{BASE}/{report_id}").status_code == 204

    def test_deleted_report_returns_404(self, client):
        report_id = client.post(
            BASE, json=_report_payload()
        ).json()["id"]
        client.delete(f"{BASE}/{report_id}")
        assert client.get(f"{BASE}/{report_id}").status_code == 404

    def test_delete_cascades_instances(self, client, activity_report):
        client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(activity_report["id"]),
        )
        client.delete(f"{BASE}/{activity_report['id']}")
        assert (
            client.get(
                f"{BASE}/{activity_report['id']}"
            ).status_code
            == 404
        )


# ─────────────────────────────────────────────────────────────────────────────
# POST/GET/DELETE /activity-reports/{id}/instances
# ─────────────────────────────────────────────────────────────────────────────


class TestInstances:
    def test_add_instance_with_all_fields(self, client, activity_report):
        resp = client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(
                activity_report["id"],
                emitter_name="AN/ALQ-99",
                emitter_confidence=0.85,
                emitter_country_code="RUS",
                platform_category="AIRCRAFT",
                platform_name="Su-35",
                platform_class="Flanker",
                last_position_error_m=100,
            ),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["emitter_name"] == "AN/ALQ-99"
        assert data["platform_category"] == "AIRCRAFT"

    def test_error_m_negative_returns_422(self, client, activity_report):
        """last_position_error_m must be >= 0 per schema v5."""
        assert (
            client.post(
                f"{BASE}/{activity_report['id']}/instances",
                json=_instance_payload(
                    activity_report["id"],
                    last_position_error_m=-1,
                ),
            ).status_code
            == 422
        )

    def test_error_m_zero_is_valid(self, client, activity_report):
        resp = client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(
                activity_report["id"],
                last_position_error_m=0,
            ),
        )
        assert resp.status_code == 201
        assert resp.json()["last_position_error_m"] == 0

    def test_emitter_confidence_above_1_returns_422(
        self, client, activity_report
    ):
        """emitter_confidence must be in [0.0, 1.0] per schema v5."""
        assert (
            client.post(
                f"{BASE}/{activity_report['id']}/instances",
                json=_instance_payload(
                    activity_report["id"],
                    emitter_confidence=1.5,
                ),
            ).status_code
            == 422
        )

    def test_emitter_confidence_below_0_returns_422(
        self, client, activity_report
    ):
        assert (
            client.post(
                f"{BASE}/{activity_report['id']}/instances",
                json=_instance_payload(
                    activity_report["id"],
                    emitter_confidence=-0.1,
                ),
            ).status_code
            == 422
        )

    def test_emitter_confidence_boundary_values_valid(
        self, client, activity_report
    ):
        """0.0 and 1.0 are both valid boundary values."""
        for confidence in [0.0, 1.0]:
            resp = client.post(
                f"{BASE}/{activity_report['id']}/instances",
                json=_instance_payload(
                    activity_report["id"],
                    emitter_confidence=confidence,
                    first_seen_dtg=f"2024-06-0{int(confidence) + 1}T10:00:00Z",
                    last_seen_dtg=f"2024-06-0{int(confidence) + 1}T11:00:00Z",
                ),
            )
            assert resp.status_code == 201

    def test_duplicate_instance_for_same_track_returns_409(
        self, client, activity_report, ew_track
    ):
        payload = _instance_payload(
            activity_report["id"], track_id=ew_track["id"]
        )
        client.post(
            f"{BASE}/{activity_report['id']}/instances", json=payload
        )
        resp = client.post(
            f"{BASE}/{activity_report['id']}/instances", json=payload
        )
        assert resp.status_code == 409

    def test_auto_mode_no_track_points(
        self, client, activity_report, ew_track
    ):
        """Auto mode with a track that has no EWTrackPoints.

        Fields derived from track points should be None.
        Instance should still be created successfully.
        """
        payload = _instance_payload(
            activity_report["id"], track_id=ew_track["id"]
        )
        resp = client.post(
            f"{BASE}/{activity_report['id']}/instances", json=payload
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["first_seen_dtg"] is None
        assert data["last_seen_dtg"] is None
        assert data["last_position_latitude_dd"] is None
        assert data["last_position_longitude_dd"] is None

    def test_last_seen_before_first_seen_returns_422(
        self, client, activity_report
    ):
        resp = client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(
                activity_report["id"],
                first_seen_dtg="2024-06-01T10:30:00Z",
                last_seen_dtg="2024-06-01T09:00:00Z",
            ),
        )
        assert resp.status_code == 422

    def test_invalid_lat_returns_422(self, client, activity_report):
        assert (
            client.post(
                f"{BASE}/{activity_report['id']}/instances",
                json=_instance_payload(
                    activity_report["id"],
                    last_position_latitude_dd=95.0,
                ),
            ).status_code
            == 422
        )

    def test_invalid_lon_returns_422(self, client, activity_report):
        assert (
            client.post(
                f"{BASE}/{activity_report['id']}/instances",
                json=_instance_payload(
                    activity_report["id"],
                    last_position_longitude_dd=190.0,
                ),
            ).status_code
            == 422
        )

    def test_list_instances_returns_all(self, client, activity_report):
        for i in range(3):
            client.post(
                f"{BASE}/{activity_report['id']}/instances",
                json=_instance_payload(
                    activity_report["id"],
                    last_position_latitude_dd=24.0 + i * 0.1,
                    first_seen_dtg=f"2024-06-0{i + 1}T10:00:00Z",
                    last_seen_dtg=f"2024-06-0{i + 1}T11:00:00Z",
                ),
            )
        assert (
            len(
                client.get(
                    f"{BASE}/{activity_report['id']}/instances"
                ).json()
            )
            == 3
        )

    def test_get_single_instance(self, client, activity_report):
        instance = client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(activity_report["id"]),
        ).json()
        resp = client.get(
            f"{BASE}/{activity_report['id']}/instances/{instance['id']}"
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == instance["id"]

    def test_get_instance_wrong_report_returns_404(
        self, client, activity_report
    ):
        instance = client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(activity_report["id"]),
        ).json()
        assert (
            client.get(
                f"{BASE}/{MISSING_UUID}/instances/{instance['id']}"
            ).status_code
            == 404
        )

    def test_delete_instance_returns_204(self, client, activity_report):
        instance = client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(activity_report["id"]),
        ).json()
        assert (
            client.delete(
                f"{BASE}/{activity_report['id']}/instances/{instance['id']}"
            ).status_code
            == 204
        )


# ─────────────────────────────────────────────────────────────────────────────
# Mission Links
# ─────────────────────────────────────────────────────────────────────────────


class TestMissionLinks:
    def test_link_mission_returns_201(
        self, client, activity_report, mission
    ):
        resp = client.post(
            f"{BASE}/{activity_report['id']}/missions/{mission['id']}"
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["activity_report_id"] == activity_report["id"]
        assert data["mission_id"] == mission["id"]

    def test_duplicate_link_returns_409(
        self, client, activity_report, mission
    ):
        client.post(
            f"{BASE}/{activity_report['id']}/missions/{mission['id']}"
        )
        resp = client.post(
            f"{BASE}/{activity_report['id']}/missions/{mission['id']}"
        )
        assert resp.status_code == 409

    def test_link_nonexistent_mission_returns_404(
        self, client, activity_report
    ):
        resp = client.post(
            f"{BASE}/{activity_report['id']}/missions/{MISSING_UUID}"
        )
        assert resp.status_code == 404

    def test_list_linked_missions(
        self, client, activity_report, mission
    ):
        client.post(
            f"{BASE}/{activity_report['id']}/missions/{mission['id']}"
        )
        mission_ids = [
            m["mission_id"]
            for m in client.get(
                f"{BASE}/{activity_report['id']}/missions"
            ).json()
        ]
        assert mission["id"] in mission_ids

    def test_list_missions_empty_for_new_report(
        self, client, activity_report
    ):
        assert (
            client.get(
                f"{BASE}/{activity_report['id']}/missions"
            ).json()
            == []
        )

    def test_unlink_mission_returns_204(
        self, client, activity_report, mission
    ):
        client.post(
            f"{BASE}/{activity_report['id']}/missions/{mission['id']}"
        )
        assert (
            client.delete(
                f"{BASE}/{activity_report['id']}/missions/{mission['id']}"
            ).status_code
            == 204
        )

    def test_unlink_not_found_returns_404(
        self, client, activity_report, mission
    ):
        assert (
            client.delete(
                f"{BASE}/{activity_report['id']}/missions/{mission['id']}"
            ).status_code
            == 404
        )

    def test_list_filter_by_mission_id(self, client, mission):
        client.post(
            BASE, json=_report_payload(mission_ids=[mission["id"]])
        )
        client.post(BASE, json=_report_payload())
        results = client.get(
            BASE, params={"mission_id": mission["id"]}
        ).json()
        assert len(results) >= 1
        assert all(
            mission["id"]
            in [
                m["mission_id"]
                for m in client.get(
                    f"{BASE}/{r['id']}/missions"
                ).json()
            ]
            for r in results
        )
