"""Tests for the threat library filter-options and entity listing endpoints."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

_ALL_ENTITY_TYPES = {
    "SpacePlatformClass",
    "AirPlatformClass",
    "GroundPlatformClass",
    "SeaSurfacePlatformClass",
    "SubsurfacePlatformClass",
    "RadarClass",
    "COMEquipment",
    "Laser",
    "Gun",
    "Missile",
    "WeaponSystem",
}


@pytest.fixture
def seeded_nrd(db_session: Session) -> None:
    """Seeds a minimal NRD technical dataset covering active and removed rows."""
    from app.models import enums
    from app.models import nrd_tech_models as tech

    active = enums.BooleanEnum.FALSE
    removed = enums.BooleanEnum.TRUE

    db_session.add_all(
        [
            tech.AirPlatformClass(
                object_id="AIR-001",
                name="MiG-29",
                english_name="Fulcrum",
                to_be_removed=active,
            ),
            tech.AirPlatformClass(
                object_id="AIR-002",
                name="Su-27",
                english_name="Flanker",
                to_be_removed=active,
            ),
            tech.AirPlatformClass(
                object_id="AIR-003",
                name="Retired Airframe",
                english_name="Retired Airframe",
                to_be_removed=removed,
            ),
            tech.SpacePlatformClass(
                object_id="SPC-001",
                name="Kosmos-2558",
                english_name="Recon Satellite",
                to_be_removed=active,
            ),
            tech.RadarClass(
                object_id="RAD-001",
                name="SNR-75",
                english_name="Fan Song",
                to_be_removed=active,
            ),
            tech.RadarClass(
                object_id="RAD-002",
                name="N001",
                english_name="Flanker",
                to_be_removed=active,
            ),
        ]
    )
    db_session.commit()


# ---------------------------------------------------------------------------
# GET /threat-library/filter-options
# ---------------------------------------------------------------------------
class TestGetFilterOptions:
    def test_returns_every_supported_entity_type(self, client: TestClient) -> None:
        """Returns one descriptor for every entity type in the tech.xsd subset."""
        response = client.get("/threat-library/filter-options")

        assert response.status_code == 200
        returned = {option["entity_type"] for option in response.json()["options"]}
        assert returned == _ALL_ENTITY_TYPES

    def test_excludes_passive_sensor_and_instance_level_types(
        self, client: TestClient
    ) -> None:
        """Omits entity types deliberately left out of the export scope."""
        response = client.get("/threat-library/filter-options")

        returned = {option["entity_type"] for option in response.json()["options"]}
        assert "PassiveSensor" not in returned
        assert "RadarInstance" not in returned
        assert "AirPlatformInstance" not in returned

    def test_returns_a_label_for_each_entity_type(self, client: TestClient) -> None:
        """Returns a non-empty display label alongside each entity type."""
        response = client.get("/threat-library/filter-options")

        assert all(option["label"] for option in response.json()["options"])

    def test_counts_exclude_entities_flagged_for_removal(
        self, client: TestClient, seeded_nrd: None
    ) -> None:
        """Excludes entities flagged ToBeRemoved from the reported counts."""
        response = client.get("/threat-library/filter-options")

        counts = {
            option["entity_type"]: option["entity_count"]
            for option in response.json()["options"]
        }
        assert counts["AirPlatformClass"] == 2

    def test_returns_zero_count_for_unpopulated_entity_type(
        self, client: TestClient, seeded_nrd: None
    ) -> None:
        """Returns a zero count rather than omitting an unpopulated entity type."""
        response = client.get("/threat-library/filter-options")

        counts = {
            option["entity_type"]: option["entity_count"]
            for option in response.json()["options"]
        }
        assert counts["Gun"] == 0

    def test_returns_all_zero_counts_on_an_empty_dataset(
        self, client: TestClient
    ) -> None:
        """Returns every entity type with a zero count when the NRD is empty."""
        response = client.get("/threat-library/filter-options")

        assert all(
            option["entity_count"] == 0 for option in response.json()["options"]
        )

    def test_requires_no_mission_context(
        self, client: TestClient, seeded_nrd: None
    ) -> None:
        """Resolves without a mission id, confirming the endpoint is dataset-level."""
        response = client.get("/threat-library/filter-options")

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /threat-library/entities
# ---------------------------------------------------------------------------
class TestListThreatEntities:
    def test_returns_a_single_group_for_one_entity_type(
        self, client: TestClient, seeded_nrd: None
    ) -> None:
        """Returns one group containing the entities of the requested type."""
        response = client.get(
            "/threat-library/entities", params={"entity_types": ["AirPlatformClass"]}
        )

        assert response.status_code == 200
        groups = response.json()["groups"]
        assert len(groups) == 1
        assert groups[0]["entity_type"] == "AirPlatformClass"
        assert groups[0]["total"] == 2

    def test_returns_one_group_per_requested_entity_type(
        self, client: TestClient, seeded_nrd: None
    ) -> None:
        """Returns a separate group for each requested entity type."""
        response = client.get(
            "/threat-library/entities",
            params={"entity_types": ["AirPlatformClass", "SpacePlatformClass"]},
        )

        groups = response.json()["groups"]
        assert [group["entity_type"] for group in groups] == [
            "AirPlatformClass",
            "SpacePlatformClass",
        ]

    def test_preserves_requested_entity_type_ordering(
        self, client: TestClient, seeded_nrd: None
    ) -> None:
        """Returns groups in the order the entity types were requested."""
        response = client.get(
            "/threat-library/entities",
            params={"entity_types": ["SpacePlatformClass", "AirPlatformClass"]},
        )

        groups = response.json()["groups"]
        assert [group["entity_type"] for group in groups] == [
            "SpacePlatformClass",
            "AirPlatformClass",
        ]

    def test_collapses_repeated_entity_types_into_one_group(
        self, client: TestClient, seeded_nrd: None
    ) -> None:
        """Returns a single group when an entity type is requested twice."""
        response = client.get(
            "/threat-library/entities",
            params={"entity_types": ["AirPlatformClass", "AirPlatformClass"]},
        )

        assert len(response.json()["groups"]) == 1

    def test_returns_object_id_and_english_name_for_each_entity(
        self, client: TestClient, seeded_nrd: None
    ) -> None:
        """Returns object_id as the selection value alongside the display name."""
        response = client.get(
            "/threat-library/entities", params={"entity_types": ["SpacePlatformClass"]}
        )

        item = response.json()["groups"][0]["items"][0]
        assert item["object_id"] == "SPC-001"
        assert item["english_name"] == "Recon Satellite"

    def test_excludes_entities_flagged_for_removal(
        self, client: TestClient, seeded_nrd: None
    ) -> None:
        """Omits entities flagged ToBeRemoved from the returned items."""
        response = client.get(
            "/threat-library/entities", params={"entity_types": ["AirPlatformClass"]}
        )

        returned = {
            item["object_id"] for item in response.json()["groups"][0]["items"]
        }
        assert "AIR-003" not in returned

    def test_orders_items_by_english_name(
        self, client: TestClient, seeded_nrd: None
    ) -> None:
        """Returns items ordered by english_name within a group."""
        response = client.get(
            "/threat-library/entities", params={"entity_types": ["AirPlatformClass"]}
        )

        names = [item["english_name"] for item in response.json()["groups"][0]["items"]]
        assert names == sorted(names)

    def test_returns_an_empty_group_for_an_unpopulated_entity_type(
        self, client: TestClient, seeded_nrd: None
    ) -> None:
        """Returns a group with a zero total rather than omitting the type."""
        response = client.get(
            "/threat-library/entities", params={"entity_types": ["Gun"]}
        )

        group = response.json()["groups"][0]
        assert group["total"] == 0
        assert group["items"] == []

    def test_filters_by_case_insensitive_search_term(
        self, client: TestClient, seeded_nrd: None
    ) -> None:
        """Matches the search term against english_name without case sensitivity."""
        response = client.get(
            "/threat-library/entities",
            params={"entity_types": ["AirPlatformClass"], "search": "fulc"},
        )

        group = response.json()["groups"][0]
        assert group["total"] == 1
        assert group["items"][0]["object_id"] == "AIR-001"

    def test_applies_search_independently_to_each_group(
        self, client: TestClient, seeded_nrd: None
    ) -> None:
        """Applies the search term within every requested entity type."""
        response = client.get(
            "/threat-library/entities",
            params={
                "entity_types": ["AirPlatformClass", "RadarClass"],
                "search": "Flanker",
            },
        )

        totals = {
            group["entity_type"]: group["total"] for group in response.json()["groups"]
        }
        assert totals == {"AirPlatformClass": 1, "RadarClass": 1}

    def test_returns_duplicate_english_names_as_distinct_entities(
        self, client: TestClient, seeded_nrd: None
    ) -> None:
        """Returns entities sharing an english_name as separately selectable rows."""
        response = client.get(
            "/threat-library/entities",
            params={
                "entity_types": ["AirPlatformClass", "RadarClass"],
                "search": "Flanker",
            },
        )

        object_ids = {
            item["object_id"]
            for group in response.json()["groups"]
            for item in group["items"]
        }
        assert object_ids == {"AIR-002", "RAD-002"}

    def test_returns_empty_groups_for_an_unmatched_search(
        self, client: TestClient, seeded_nrd: None
    ) -> None:
        """Returns zero totals across all groups when nothing matches."""
        response = client.get(
            "/threat-library/entities",
            params={"entity_types": ["AirPlatformClass"], "search": "zzzz"},
        )

        group = response.json()["groups"][0]
        assert group["total"] == 0
        assert group["items"] == []

    def test_applies_limit_within_each_group(
        self, client: TestClient, seeded_nrd: None
    ) -> None:
        """Caps items per group at the limit while reporting the full total."""
        response = client.get(
            "/threat-library/entities",
            params={
                "entity_types": ["AirPlatformClass", "RadarClass"],
                "limit": 1,
            },
        )

        for group in response.json()["groups"]:
            assert len(group["items"]) == 1
            assert group["total"] == 2

    def test_applies_offset_within_each_group(
        self, client: TestClient, seeded_nrd: None
    ) -> None:
        """Skips the offset independently inside every group."""
        response = client.get(
            "/threat-library/entities",
            params={"entity_types": ["AirPlatformClass"], "limit": 10, "offset": 1},
        )

        group = response.json()["groups"][0]
        assert group["total"] == 2
        assert len(group["items"]) == 1
        assert group["items"][0]["english_name"] == "Fulcrum"

    def test_paginates_a_group_without_overlap_or_omission(
        self, client: TestClient, seeded_nrd: None
    ) -> None:
        """Returns every entity in a group exactly once when paged sequentially."""
        collected: list[str] = []
        for offset in range(2):
            response = client.get(
                "/threat-library/entities",
                params={
                    "entity_types": ["AirPlatformClass"],
                    "limit": 1,
                    "offset": offset,
                },
            )
            collected.extend(
                item["object_id"] for item in response.json()["groups"][0]["items"]
            )

        assert sorted(collected) == ["AIR-001", "AIR-002"]

    def test_echoes_pagination_parameters(
        self, client: TestClient, seeded_nrd: None
    ) -> None:
        """Returns the applied limit and offset alongside the groups."""
        response = client.get(
            "/threat-library/entities",
            params={"entity_types": ["AirPlatformClass"], "limit": 5, "offset": 1},
        )

        body = response.json()
        assert body["limit"] == 5
        assert body["offset"] == 1

    def test_returns_422_when_entity_types_omitted(self, client: TestClient) -> None:
        """Returns 422 when the required entity_types parameter is absent."""
        response = client.get("/threat-library/entities")

        assert response.status_code == 422

    @pytest.mark.parametrize(
        "entity_type",
        ["PassiveSensor", "RadarInstance", "TechnicalRelations", "NotAType"],
    )
    def test_returns_422_for_out_of_scope_entity_type(
        self, client: TestClient, entity_type: str
    ) -> None:
        """Returns 422 for entity types outside the supported export subset."""
        response = client.get(
            "/threat-library/entities", params={"entity_types": [entity_type]}
        )

        assert response.status_code == 422

    def test_returns_422_when_one_of_several_entity_types_is_invalid(
        self, client: TestClient, seeded_nrd: None
    ) -> None:
        """Rejects the whole request when any requested entity type is unsupported."""
        response = client.get(
            "/threat-library/entities",
            params={"entity_types": ["AirPlatformClass", "PassiveSensor"]},
        )

        assert response.status_code == 422

    @pytest.mark.parametrize(
        ("params", "reason"),
        [
            ({"limit": 0}, "limit below minimum"),
            ({"limit": 501}, "limit above maximum"),
            ({"offset": -1}, "negative offset"),
            ({"search": "a"}, "search below minimum length"),
        ],
    )
    def test_returns_422_for_out_of_range_query_parameters(
        self, client: TestClient, params: dict[str, Any], reason: str
    ) -> None:
        """Returns 422 for pagination and search parameters outside their bounds."""
        response = client.get(
            "/threat-library/entities",
            params={"entity_types": ["AirPlatformClass"], **params},
        )

        assert response.status_code == 422, reason


        """Tests for the mission-scoped threat library export endpoint."""

import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

_MISSION_PAYLOAD: dict[str, Any] = {
    "name": "Threat Export Test Mission",
    "mission_type": "Training",
}


@pytest.fixture
def mission_id(client: TestClient) -> str:
    """Creates a mission and returns its id."""
    response = client.post("/missions", json=_MISSION_PAYLOAD)
    assert response.status_code == 201
    return response.json()["id"]


@pytest.fixture
def seeded_nrd(db_session: Session) -> None:
    """Seeds a minimal NRD technical dataset covering active and removed rows."""
    from app.models import enums
    from app.models import nrd_tech_models as tech

    active = enums.BooleanEnum.FALSE
    removed = enums.BooleanEnum.TRUE

    db_session.add_all(
        [
            tech.AirPlatformClass(
                object_id="AIR-001",
                name="MiG-29",
                english_name="Fulcrum",
                to_be_removed=active,
            ),
            tech.AirPlatformClass(
                object_id="AIR-002",
                name="Su-27",
                english_name="Flanker",
                to_be_removed=active,
            ),
            tech.AirPlatformClass(
                object_id="AIR-003",
                name="Retired Airframe",
                english_name="Retired Airframe",
                to_be_removed=removed,
            ),
            tech.SpacePlatformClass(
                object_id="SPC-001",
                name="Kosmos-2558",
                english_name="Recon Satellite",
                to_be_removed=active,
            ),
            tech.RadarClass(
                object_id="RAD-001",
                name="SNR-75",
                english_name="Fan Song",
                to_be_removed=active,
            ),
        ]
    )
    db_session.commit()


def _selection(entity_type: str, *object_ids: str) -> dict[str, Any]:
    return {"entity_type": entity_type, "object_ids": list(object_ids)}


def _export(client: TestClient, mission_id: str, *selections: dict[str, Any]) -> Any:
    return client.post(
        f"/missions/{mission_id}/exports/threat",
        json={"selections": list(selections)},
    )


def _parse_artifact(db_session: Session, export_id: str) -> ET.Element:
    """Loads the generated XML artifact for an export from disk."""
    from app.models.mission_models import ThreatExport

    record = db_session.get(ThreatExport, uuid.UUID(export_id))
    assert record is not None
    return ET.parse(Path(record.file_path)).getroot()


# ---------------------------------------------------------------------------
# Successful export
# ---------------------------------------------------------------------------
class TestCreateThreatExportSuccess:
    def test_returns_201_for_a_single_entity_type(
        self, client: TestClient, mission_id: str, seeded_nrd: None
    ) -> None:
        """Creates an export from a selection covering one entity type."""
        response = _export(
            client, mission_id, _selection("AirPlatformClass", "AIR-001", "AIR-002")
        )

        assert response.status_code == 201
        assert response.json()["exported_entity_count"] == 2

    def test_returns_201_for_multiple_entity_types(
        self, client: TestClient, mission_id: str, seeded_nrd: None
    ) -> None:
        """Creates an export from a selection spanning several entity types."""
        response = _export(
            client,
            mission_id,
            _selection("AirPlatformClass", "AIR-001", "AIR-002"),
            _selection("SpacePlatformClass", "SPC-001"),
            _selection("RadarClass", "RAD-001"),
        )

        assert response.status_code == 201
        assert response.json()["exported_entity_count"] == 4

    def test_returns_the_owning_mission_id(
        self, client: TestClient, mission_id: str, seeded_nrd: None
    ) -> None:
        """Returns the mission the export was generated under."""
        response = _export(client, mission_id, _selection("AirPlatformClass", "AIR-001"))

        assert response.json()["mission_id"] == mission_id

    def test_returns_a_download_url_and_future_expiry(
        self, client: TestClient, mission_id: str, seeded_nrd: None
    ) -> None:
        """Returns a download link whose expiry lies in the future."""
        response = _export(client, mission_id, _selection("AirPlatformClass", "AIR-001"))

        file_entry = response.json()["files"][0]
        assert file_entry["download_url"]
        expires_at = datetime.fromisoformat(file_entry["expires_at"])
        assert expires_at > datetime.now(timezone.utc)

    def test_persists_a_threat_export_row(
        self,
        client: TestClient,
        mission_id: str,
        seeded_nrd: None,
        db_session: Session,
    ) -> None:
        """Persists export metadata linked to the owning mission."""
        from app.models.mission_models import ThreatExport

        response = _export(client, mission_id, _selection("AirPlatformClass", "AIR-001"))

        record = db_session.get(
            ThreatExport, uuid.UUID(response.json()["files"][0]["id"])
        )
        assert record is not None
        assert str(record.mission_id) == mission_id

    def test_creates_a_new_row_for_each_export(
        self, client: TestClient, mission_id: str, seeded_nrd: None
    ) -> None:
        """Returns distinct export ids for two exports on the same mission."""
        first = _export(client, mission_id, _selection("AirPlatformClass", "AIR-001"))
        second = _export(client, mission_id, _selection("AirPlatformClass", "AIR-002"))

        assert first.json()["files"][0]["id"] != second.json()["files"][0]["id"]


# ---------------------------------------------------------------------------
# Generated artifact
# ---------------------------------------------------------------------------
class TestGeneratedArtifact:
    def test_writes_a_file_to_the_recorded_path(
        self,
        client: TestClient,
        mission_id: str,
        seeded_nrd: None,
        db_session: Session,
    ) -> None:
        """Writes the export artifact to the path stored on the export row."""
        from app.models.mission_models import ThreatExport

        response = _export(client, mission_id, _selection("AirPlatformClass", "AIR-001"))

        record = db_session.get(
            ThreatExport, uuid.UUID(response.json()["files"][0]["id"])
        )
        assert Path(record.file_path).is_file()

    def test_records_the_mission_on_the_document_root(
        self,
        client: TestClient,
        mission_id: str,
        seeded_nrd: None,
        db_session: Session,
    ) -> None:
        """Records the owning mission id on the generated document root."""
        response = _export(client, mission_id, _selection("AirPlatformClass", "AIR-001"))

        root = _parse_artifact(db_session, response.json()["files"][0]["id"])
        assert root.get("missionId") == mission_id

    def test_marks_the_document_as_a_placeholder(
        self,
        client: TestClient,
        mission_id: str,
        seeded_nrd: None,
        db_session: Session,
    ) -> None:
        """Marks the artifact as a placeholder pending the export XSD."""
        response = _export(client, mission_id, _selection("AirPlatformClass", "AIR-001"))

        root = _parse_artifact(db_session, response.json()["files"][0]["id"])
        assert root.get("schemaStatus") == "PLACEHOLDER"

    def test_groups_entities_under_their_entity_type(
        self,
        client: TestClient,
        mission_id: str,
        seeded_nrd: None,
        db_session: Session,
    ) -> None:
        """Emits one element per selected entity type under Technical."""
        response = _export(
            client,
            mission_id,
            _selection("AirPlatformClass", "AIR-001"),
            _selection("SpacePlatformClass", "SPC-001"),
        )

        root = _parse_artifact(db_session, response.json()["files"][0]["id"])
        groups = {child.tag for child in root.find("Technical")}
        assert groups == {"AirPlatformClass", "SpacePlatformClass"}

    def test_writes_name_and_english_name_for_each_entity(
        self,
        client: TestClient,
        mission_id: str,
        seeded_nrd: None,
        db_session: Session,
    ) -> None:
        """Writes the identifying fields of each selected entity."""
        response = _export(client, mission_id, _selection("AirPlatformClass", "AIR-001"))

        root = _parse_artifact(db_session, response.json()["files"][0]["id"])
        entity = root.find("./Technical/AirPlatformClass/Entity")
        assert entity.get("ObjectId") == "AIR-001"
        assert entity.findtext("Name") == "MiG-29"
        assert entity.findtext("EnglishName") == "Fulcrum"
        assert entity.findtext("EntityType") == "AirPlatformClass"

    def test_records_a_count_per_entity_type_group(
        self,
        client: TestClient,
        mission_id: str,
        seeded_nrd: None,
        db_session: Session,
    ) -> None:
        """Records the number of entities emitted under each entity type."""
        response = _export(
            client, mission_id, _selection("AirPlatformClass", "AIR-001", "AIR-002")
        )

        root = _parse_artifact(db_session, response.json()["files"][0]["id"])
        group = root.find("./Technical/AirPlatformClass")
        assert group.get("count") == "2"

    def test_excludes_entities_absent_from_the_selection(
        self,
        client: TestClient,
        mission_id: str,
        seeded_nrd: None,
        db_session: Session,
    ) -> None:
        """Emits only the selected entities, not the full entity type."""
        response = _export(client, mission_id, _selection("AirPlatformClass", "AIR-001"))

        root = _parse_artifact(db_session, response.json()["files"][0]["id"])
        emitted = {
            entity.get("ObjectId")
            for entity in root.findall("./Technical/AirPlatformClass/Entity")
        }
        assert emitted == {"AIR-001"}

    def test_omits_entity_types_that_were_not_selected(
        self,
        client: TestClient,
        mission_id: str,
        seeded_nrd: None,
        db_session: Session,
    ) -> None:
        """Omits unselected entity types entirely from the document."""
        response = _export(client, mission_id, _selection("AirPlatformClass", "AIR-001"))

        root = _parse_artifact(db_session, response.json()["files"][0]["id"])
        assert root.find("./Technical/RadarClass") is None


# ---------------------------------------------------------------------------
# Rejected selections
# ---------------------------------------------------------------------------
class TestCreateThreatExportRejections:
    def test_returns_404_for_unknown_mission(
        self, client: TestClient, seeded_nrd: None
    ) -> None:
        """Returns 404 for a well-formed but unmapped mission id."""
        response = _export(
            client, str(uuid.uuid4()), _selection("AirPlatformClass", "AIR-001")
        )

        assert response.status_code == 404

    def test_returns_404_for_soft_deleted_mission(
        self, client: TestClient, mission_id: str, seeded_nrd: None
    ) -> None:
        """Returns 404 once the parent mission has been soft deleted."""
        client.delete(f"/missions/{mission_id}")

        response = _export(client, mission_id, _selection("AirPlatformClass", "AIR-001"))

        assert response.status_code == 404

    def test_returns_422_for_malformed_mission_id(
        self, client: TestClient, seeded_nrd: None
    ) -> None:
        """Returns 422 for a mission id that is not a valid UUID."""
        response = _export(
            client, "not-a-uuid", _selection("AirPlatformClass", "AIR-001")
        )

        assert response.status_code == 422

    def test_returns_404_for_unknown_object_id(
        self, client: TestClient, mission_id: str, seeded_nrd: None
    ) -> None:
        """Returns 404 when a selected object id is absent from the dataset."""
        response = _export(
            client, mission_id, _selection("AirPlatformClass", "AIR-001", "AIR-999")
        )

        assert response.status_code == 404

    def test_returns_404_for_entity_flagged_for_removal(
        self, client: TestClient, mission_id: str, seeded_nrd: None
    ) -> None:
        """Rejects a selection referencing an entity flagged ToBeRemoved."""
        response = _export(client, mission_id, _selection("AirPlatformClass", "AIR-003"))

        assert response.status_code == 404

    def test_returns_404_when_object_id_belongs_to_another_entity_type(
        self, client: TestClient, mission_id: str, seeded_nrd: None
    ) -> None:
        """Rejects an object id that exists only under a different entity type."""
        response = _export(client, mission_id, _selection("AirPlatformClass", "RAD-001"))

        assert response.status_code == 404

    def test_writes_no_artifact_when_a_selection_is_rejected(
        self,
        client: TestClient,
        mission_id: str,
        seeded_nrd: None,
        db_session: Session,
    ) -> None:
        """Persists no export row when any selected object id is invalid."""
        from app.models.mission_models import ThreatExport

        _export(client, mission_id, _selection("AirPlatformClass", "AIR-999"))

        rows = (
            db_session.query(ThreatExport)
            .filter(ThreatExport.mission_id == uuid.UUID(mission_id))
            .all()
        )
        assert rows == []

    def test_returns_422_for_empty_selections(
        self, client: TestClient, mission_id: str
    ) -> None:
        """Returns 422 when the selections list is empty."""
        response = client.post(
            f"/missions/{mission_id}/exports/threat", json={"selections": []}
        )

        assert response.status_code == 422

    def test_returns_422_for_empty_object_ids(
        self, client: TestClient, mission_id: str
    ) -> None:
        """Returns 422 when a selection carries no object ids."""
        response = _export(client, mission_id, _selection("AirPlatformClass"))

        assert response.status_code == 422

    def test_returns_422_for_duplicate_object_ids_within_a_selection(
        self, client: TestClient, mission_id: str
    ) -> None:
        """Returns 422 when a selection repeats the same object id."""
        response = _export(
            client, mission_id, _selection("AirPlatformClass", "AIR-001", "AIR-001")
        )

        assert response.status_code == 422

    def test_returns_422_for_repeated_entity_type(
        self, client: TestClient, mission_id: str
    ) -> None:
        """Returns 422 when the same entity type appears in two selections."""
        response = _export(
            client,
            mission_id,
            _selection("AirPlatformClass", "AIR-001"),
            _selection("AirPlatformClass", "AIR-002"),
        )

        assert response.status_code == 422

    @pytest.mark.parametrize(
        "entity_type", ["PassiveSensor", "RadarInstance", "NotAType"]
    )
    def test_returns_422_for_out_of_scope_entity_type(
        self, client: TestClient, mission_id: str, entity_type: str
    ) -> None:
        """Returns 422 for entity types outside the supported export subset."""
        response = _export(client, mission_id, _selection(entity_type, "XXX-001"))

        assert response.status_code == 422

    def test_returns_422_for_unexpected_field(
        self, client: TestClient, mission_id: str
    ) -> None:
        """Returns 422 for a request body carrying an undeclared field."""
        response = client.post(
            f"/missions/{mission_id}/exports/threat",
            json={
                "selections": [_selection("AirPlatformClass", "AIR-001")],
                "persist_filter": True,
            },
        )

        assert response.status_code == 422

    def test_returns_422_when_object_ids_exceed_maximum(
        self, client: TestClient, mission_id: str
    ) -> None:
        """Returns 422 when a selection exceeds the per-type object id ceiling."""
        response = _export(
            client,
            mission_id,
            _selection(
                "AirPlatformClass", *[f"AIR-{index:05d}" for index in range(5001)]
            ),
        )

        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Cross-endpoint contract
# ---------------------------------------------------------------------------
class TestThreatExportContract:
    def test_listed_entities_are_accepted_by_the_export_endpoint(
        self, client: TestClient, mission_id: str, seeded_nrd: None
    ) -> None:
        """Accepts every object id returned by the entity listing endpoint."""
        listed = client.get(
            "/threat-library/entities",
            params={"entity_types": ["AirPlatformClass", "SpacePlatformClass"]},
        ).json()

        response = _export(
            client,
            mission_id,
            *[
                _selection(
                    group["entity_type"],
                    *[item["object_id"] for item in group["items"]],
                )
                for group in listed["groups"]
                if group["items"]
            ],
        )

        assert response.status_code == 201

    def test_export_count_matches_the_listed_totals(
        self, client: TestClient, mission_id: str, seeded_nrd: None
    ) -> None:
        """Exports exactly as many entities as the listing reported available."""
        listed = client.get(
            "/threat-library/entities", params={"entity_types": ["AirPlatformClass"]}
        ).json()
        group = listed["groups"][0]

        response = _export(
            client,
            mission_id,
            _selection(
                "AirPlatformClass", *[item["object_id"] for item in group["items"]]
            ),
        )

        assert response.json()["exported_entity_count"] == group["total"]