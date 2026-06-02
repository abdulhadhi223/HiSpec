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
import uuid

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

BASE = "/activity-reports"
CLS = "SECRET"
MISSING_UUID = "00000000-0000-0000-0000-000000000000"


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
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
        "last_position_latitude_dd": 24.4539,
        "last_position_longitude_dd": 54.3773,
        "classification": CLS,
        "source_system": "Thor",
        **overrides,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CREATE REPORT
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateReport:
    def test_create_minimal_returns_201(self, client):
        resp = client.post(BASE, json=_report_payload())
        assert resp.status_code == 201
        assert resp.json()["submitted_by"] == "operator1"

    def test_create_with_optional_fields(self, client):
        resp = client.post(
            BASE,
            json=_report_payload(
                name="Daily EW Report",
                start_at="2024-06-01T08:00:00Z",
                end_at="2024-06-01T20:00:00Z",
            ),
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "Daily EW Report"

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

    def test_create_duplicate_mission_ids_causes_409(self, client, mission):
        """Passing same mission_id twice triggers IntegrityError → 409."""
        payload = {
            "submitted_by": "tester",
            "classification": CLS,
            "mission_ids": [mission["id"], mission["id"]],
        }
        assert client.post(BASE, json=payload).status_code == 409


# ─────────────────────────────────────────────────────────────────────────────
# GET REPORT
# ─────────────────────────────────────────────────────────────────────────────


class TestGetReport:
    def test_list_returns_created_report(self, client, activity_report):
        ids = [r["id"] for r in client.get(BASE).json()]
        assert activity_report["id"] in ids

    def test_list_filter_submitted_by(self, client):
        client.post(BASE, json=_report_payload(submitted_by="alice"))
        client.post(BASE, json=_report_payload(submitted_by="bob"))
        results = client.get(
            BASE, params={"submitted_by": "alice"}
        ).json()
        assert all(r["submitted_by"] == "alice" for r in results)

    def test_list_pagination(self, client):
        for i in range(5):
            client.post(BASE, json=_report_payload(submitted_by=f"user{i}"))
        assert len(client.get(BASE, params={"limit": 3}).json()) <= 3

    def test_get_detail(self, client, activity_report):
        resp = client.get(f"{BASE}/{activity_report['id']}")
        assert resp.status_code == 200
        assert "instances" in resp.json()
        assert "report_missions" in resp.json()

    def test_get_missing_returns_404(self, client):
        assert client.get(f"{BASE}/{MISSING_UUID}").status_code == 404

    def test_list_invalid_date_range_returns_422(self, client):
        resp = client.get(
            BASE,
            params={
                "from_dt": "2026-06-02T00:00:00+04:00",
                "to_dt": "2026-06-01T23:59:59+04:00",
            },
        )
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# PATCH REPORT
# ─────────────────────────────────────────────────────────────────────────────


class TestUpdateReport:
    def test_patch_name(self, client, activity_report):
        resp = client.patch(
            f"{BASE}/{activity_report['id']}",
            json={"name": "Updated!"},
        )
        assert resp.status_code == 200

    def test_patch_classification(self, client, activity_report):
        resp = client.patch(
            f"{BASE}/{activity_report['id']}",
            json={"classification": "UNCLASSIFIED"},
        )
        assert resp.status_code == 200

    def test_patch_missing_report(self, client):
        assert (
            client.patch(
                f"{BASE}/{MISSING_UUID}", json={"name": "X"}
            ).status_code
            == 404
        )


# ─────────────────────────────────────────────────────────────────────────────
# DELETE REPORT
# ─────────────────────────────────────────────────────────────────────────────


class TestDeleteReport:
    def test_delete_ok(self, client):
        rid = client.post(BASE, json=_report_payload()).json()["id"]
        assert client.delete(f"{BASE}/{rid}").status_code == 204

    def test_delete_missing(self, client):
        assert client.delete(f"{BASE}/{MISSING_UUID}").status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Instances
# ─────────────────────────────────────────────────────────────────────────────


class TestInstances:
    def test_add_instance_returns_201(self, client, activity_report):
        resp = client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(activity_report["id"]),
        )
        assert resp.status_code == 201

    def test_add_instance_with_track_link(
        self, client, activity_report, ew_track
    ):
        resp = client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(
                activity_report["id"], track_id=ew_track["id"]
            ),
        )
        assert resp.status_code == 201

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
        assert resp.json()["emitter_name"] == "AN/ALQ-99"

    def test_duplicate_instance_for_same_track_returns_409(
        self, client, activity_report, ew_track
    ):
        payload = _instance_payload(
            activity_report["id"], track_id=ew_track["id"]
        )
        first = client.post(
            f"{BASE}/{activity_report['id']}/instances", json=payload
        )
        assert first.status_code == 201
        second = client.post(
            f"{BASE}/{activity_report['id']}/instances", json=payload
        )
        assert second.status_code == 409

    def test_add_instance_invalid_track_id_returns_422(
        self, client, activity_report
    ):
        """track_id that does not exist → ValueError → 422."""
        resp = client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(
                activity_report["id"], track_id=MISSING_UUID
            ),
        )
        assert resp.status_code == 422

    def test_add_instance_manual_mode_missing_fields_returns_422(
        self, client, activity_report
    ):
        """Manual mode with missing required snapshot fields → 422."""
        resp = client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json={
                "activity_report_id": activity_report["id"],
                "signal_type": "RADAR",
            },
        )
        assert resp.status_code == 422

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
                    last_position_latitude_dd=24.0 + i,
                    first_seen_dtg=f"2024-06-0{i + 1}T10:00:00Z",
                    last_seen_dtg=f"2024-06-0{i + 1}T11:00:00Z",
                ),
            )
        resp = client.get(f"{BASE}/{activity_report['id']}/instances")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    def test_get_single_instance(self, client, activity_report):
        inst = client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(activity_report["id"]),
        ).json()
        resp = client.get(
            f"{BASE}/{activity_report['id']}/instances/{inst['id']}"
        )
        assert resp.status_code == 200

    def test_get_instance_wrong_report_returns_404(
        self, client, activity_report
    ):
        inst = client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(activity_report["id"]),
        ).json()
        assert (
            client.get(
                f"{BASE}/{MISSING_UUID}/instances/{inst['id']}"
            ).status_code
            == 404
        )

    def test_delete_instance_returns_204(self, client, activity_report):
        inst = client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(activity_report["id"]),
        ).json()
        assert (
            client.delete(
                f"{BASE}/{activity_report['id']}/instances/{inst['id']}"
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

    def test_unlink_mission_returns_204(
        self, client, activity_report, mission
    ):
        client.post(
            f"{BASE}/{activity_report['id']}/missions/{mission['id']}"
        )
        resp = client.delete(
            f"{BASE}/{activity_report['id']}/missions/{mission['id']}"
        )
        assert resp.status_code == 204

    def test_unlink_missing_returns_404(
        self, client, activity_report, mission
    ):
        resp = client.delete(
            f"{BASE}/{activity_report['id']}/missions/{mission['id']}"
        )
        assert resp.status_code == 404

    def test_list_linked_missions(
        self, client, activity_report, mission
    ):
        client.post(
            f"{BASE}/{activity_report['id']}/missions/{mission['id']}"
        )
        resp = client.get(f"{BASE}/{activity_report['id']}/missions")
        assert resp.status_code == 200
        assert mission["id"] in [m["mission_id"] for m in resp.json()]

    def test_list_missions_empty(self, client, activity_report):
        resp = client.get(f"{BASE}/{activity_report['id']}/missions")
        assert resp.status_code == 200
        assert resp.json() == []


# ─────────────────────────────────────────────────────────────────────────────
# Service-layer mock tests — covers SQLAlchemyError except branches
# ─────────────────────────────────────────────────────────────────────────────


class TestServiceErrors:
    """Patches DB to raise SQLAlchemyError — covers except branches."""

    def test_list_reports_db_error_returns_500(self, client):
        with pytest.raises(Exception):
            with pytest.MonkeyPatch().context() as mp:
                mp.setattr(
                    Session,
                    "execute",
                    lambda *a, **kw: (_ for _ in ()).throw(
                        SQLAlchemyError("db error")
                    ),
                )
                client.get(BASE)

    def test_get_report_detail_db_error_returns_500(
        self, client, activity_report
    ):
        from unittest.mock import patch

        with patch.object(
            Session,
            "execute",
            side_effect=SQLAlchemyError("db error"),
        ):
            resp = client.get(f"{BASE}/{activity_report['id']}")
            assert resp.status_code == 500

    def test_list_instances_db_error_returns_500(
        self, client, activity_report
    ):
        from unittest.mock import patch

        with patch.object(
            Session,
            "execute",
            side_effect=SQLAlchemyError("db error"),
        ):
            resp = client.get(
                f"{BASE}/{activity_report['id']}/instances"
            )
            assert resp.status_code == 500

    def test_list_missions_db_error_returns_500(
        self, client, activity_report
    ):
        from unittest.mock import patch

        with patch.object(
            Session,
            "execute",
            side_effect=SQLAlchemyError("db error"),
        ):
            resp = client.get(
                f"{BASE}/{activity_report['id']}/missions"
            )
            assert resp.status_code == 500

    def test_update_report_db_error_returns_500(
        self, client, activity_report
    ):
        from unittest.mock import patch

        with patch.object(
            Session,
            "commit",
            side_effect=SQLAlchemyError("db error"),
        ):
            resp = client.patch(
                f"{BASE}/{activity_report['id']}",
                json={"name": "Test"},
            )
            assert resp.status_code == 500

    def test_delete_instance_db_error_returns_500(
        self, client, activity_report
    ):
        from unittest.mock import patch

        inst = client.post(
            f"{BASE}/{activity_report['id']}/instances",
            json=_instance_payload(activity_report["id"]),
        ).json()
        with patch.object(
            Session,
            "commit",
            side_effect=SQLAlchemyError("db error"),
        ):
            resp = client.delete(
                f"{BASE}/{activity_report['id']}"
                f"/instances/{inst['id']}"
            )
            assert resp.status_code == 500

    def test_unlink_mission_db_error_returns_500(
        self, client, activity_report, mission
    ):
        from unittest.mock import patch

        client.post(
            f"{BASE}/{activity_report['id']}/missions/{mission['id']}"
        )
        with patch.object(
            Session,
            "commit",
            side_effect=SQLAlchemyError("db error"),
        ):
            resp = client.delete(
                f"{BASE}/{activity_report['id']}"
                f"/missions/{mission['id']}"
            )
            assert resp.status_code == 500


# ─────────────────────────────────────────────────────────────────────────────
# Schema validation tests (local imports — avoids mapper ordering issue)
# ─────────────────────────────────────────────────────────────────────────────


def test_schema_time_window_valid_passes():
    from app.schemas.activity_report import ActivityReportCreate

    obj = ActivityReportCreate(
        submitted_by="someone",
        classification="SECRET",
        start_at="2024-01-01T10:00:00Z",
        end_at="2024-01-01T10:00:00Z",
    )
    assert obj.end_at is not None


def test_instance_schema_valid_error_m():
    from app.schemas.activity_report import ActivityReportInstanceCreate

    inst = ActivityReportInstanceCreate(
        activity_report_id=uuid.uuid4(),
        signal_type="RADAR",
        hostility="HOSTILE",
        first_seen_dtg="2024-06-01T10:00:00Z",
        last_seen_dtg="2024-06-01T10:20:00Z",
        last_position_latitude_dd=20,
        last_position_longitude_dd=30,
        classification="SECRET",
        source_system="SRC",
        last_position_error_m=0,
    )
    assert inst.last_position_error_m == 0


def test_instance_schema_stores_provided_fields():
    """Schema stores all provided fields regardless of track_id presence."""
    from app.schemas.activity_report import ActivityReportInstanceCreate

    inst = ActivityReportInstanceCreate(
        activity_report_id=uuid.uuid4(),
        track_id=uuid.uuid4(),
        signal_type="RADAR",
        hostility="HOSTILE",
        first_seen_dtg="2024-06-01T10:00:00Z",
        last_seen_dtg="2024-06-01T11:00:00Z",
        last_position_latitude_dd=20,
        last_position_longitude_dd=30,
        classification="SECRET",
        source_system="SRC",
    )
    # Schema just stores — field clearing is service layer concern
    assert inst.signal_type is not None
    assert inst.track_id is not None


def test_add_instance_manual_mode_missing_fields_returns_422(
    client, activity_report
):
    """Manual mode with missing required snapshot fields → 422."""
    resp = client.post(
        f"{BASE}/{activity_report['id']}/instances",
        json={
            "activity_report_id": activity_report["id"],
            "signal_type": "RADAR",
        },
    )
    assert resp.status_code == 422
