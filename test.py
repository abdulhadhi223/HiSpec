app/schemas/threat_export_schemas.py
python
"""Schemas for the threat library export filter and selection API."""

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import enums


class TechnicalEntityType(str, Enum):
    """Filterable top-level elements of TechnicalType (tech.xsd)."""

    SPACE_PLATFORM_CLASS = "SpacePlatformClass"
    AIR_PLATFORM_CLASS = "AirPlatformClass"
    GROUND_PLATFORM_CLASS = "GroundPlatformClass"
    SEA_SURFACE_PLATFORM_CLASS = "SeaSurfacePlatformClass"
    SUBSURFACE_PLATFORM_CLASS = "SubsurfacePlatformClass"
    RADAR_CLASS = "RadarClass"
    COM_EQUIPMENT = "COMEquipment"
    LASER = "Laser"
    GUN = "Gun"
    MISSILE = "Missile"
    WEAPON_SYSTEM = "WeaponSystem"


# ---------------------------------------------------------------------------
# Step 1 — available filter options
# ---------------------------------------------------------------------------
class FilterOptionDescriptor(BaseModel):
    """One selectable entity type, with a live count of available entities."""

    entity_type: TechnicalEntityType
    label: str
    entity_count: int


class FilterOptionsResponse(BaseModel):
    options: list[FilterOptionDescriptor]


# ---------------------------------------------------------------------------
# Step 2 — entities under the selected types
# ---------------------------------------------------------------------------
class ThreatEntityOption(BaseModel):
    """A single selectable threat entity. `object_id` is the value LP must send
    back; `english_name` is display only and is not guaranteed unique."""

    model_config = ConfigDict(from_attributes=True)

    entity_type: TechnicalEntityType
    object_id: str
    english_name: str


class ThreatEntityListResponse(BaseModel):
    items: list[ThreatEntityOption]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Step 3 — export request
# ---------------------------------------------------------------------------
class ThreatEntitySelection(BaseModel):
    """Selected entities for one entity type."""

    model_config = ConfigDict(extra="forbid")

    entity_type: TechnicalEntityType
    object_ids: list[str] = Field(min_length=1, max_length=5000)

    @model_validator(mode="after")
    def _check_unique_object_ids(self) -> "ThreatEntitySelection":
        if len(set(self.object_ids)) != len(self.object_ids):
            raise ValueError(
                f"duplicate object_ids for entity type '{self.entity_type.value}'"
            )
        return self


class ThreatExportRequest(BaseModel):
    """Body for POST /missions/{id}/exports/threat.

    The selection is transient: it is applied to the NRD dataset at export time
    and is not persisted as filter criteria.
    """

    model_config = ConfigDict(extra="forbid")

    selections: list[ThreatEntitySelection] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_unique_entity_types(self) -> "ThreatExportRequest":
        seen = [selection.entity_type for selection in self.selections]
        if len(set(seen)) != len(seen):
            raise ValueError("each entity type may appear at most once in 'selections'")
        return self


# ---------------------------------------------------------------------------
# Export response
# ---------------------------------------------------------------------------
class ThreatExportFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    file_type: enums.FileType
    download_url: str
    expires_at: datetime
    generated_at: datetime


class ThreatExportResponse(BaseModel):
    mission_id: uuid.UUID
    exported_entity_count: int
    files: list[ThreatExportFileResponse]
2. app/api/routers/threat_export_router.py
python
"""Threat library export endpoints. Thin router — no ORM access, no try/except."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.schemas.threat_export_schemas import (
    FilterOptionsResponse,
    TechnicalEntityType,
    ThreatEntityListResponse,
    ThreatExportRequest,
    ThreatExportResponse,
)

router = APIRouter(prefix="/missions", tags=["Threat Export"])


@router.get(
    "/{mission_id}/exports/threat/filter-options",
    response_model=FilterOptionsResponse,
    status_code=status.HTTP_200_OK,
)
def get_threat_export_filter_options(
    mission_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> FilterOptionsResponse:
    from app.services import threat_export_service

    return threat_export_service.get_filter_options(db=db, mission_id=mission_id)


@router.get(
    "/{mission_id}/exports/threat/entities",
    response_model=ThreatEntityListResponse,
    status_code=status.HTTP_200_OK,
)
def list_threat_entities(
    mission_id: uuid.UUID,
    entity_types: Annotated[list[TechnicalEntityType], Query(min_length=1)],
    db: Annotated[Session, Depends(get_db)],
    search: Annotated[str | None, Query(min_length=2, max_length=255)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ThreatEntityListResponse:
    from app.services import threat_export_service

    return threat_export_service.list_threat_entities(
        db=db,
        mission_id=mission_id,
        entity_types=entity_types,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{mission_id}/exports/threat",
    response_model=ThreatExportResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_threat_export(
    mission_id: uuid.UUID,
    payload: ThreatExportRequest,
    db: Annotated[Session, Depends(get_db)],
) -> ThreatExportResponse:
    from app.services import threat_export_service

    return threat_export_service.create_threat_export(
        db=db, mission_id=mission_id, request=payload
    )
3. app/services/threat_export_service.py
python
"""Threat library export service."""

import uuid
from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models import nrd_tech_models as tech
from app.models.mission_models import Mission
from app.schemas.threat_export_schemas import (
    FilterOptionDescriptor,
    FilterOptionsResponse,
    TechnicalEntityType,
    ThreatEntityListResponse,
    ThreatEntityOption,
    ThreatExportRequest,
    ThreatExportResponse,
)


@dataclass(frozen=True)
class _EntityBinding:
    """Maps a tech.xsd entity type to its ORM model and display label."""

    model: type
    label: str


# A single relationship() cannot span multiple mapped classes, so the entity
# type is resolved to its table through this dispatch map instead.
_ENTITY_QUERY_MAP: dict[TechnicalEntityType, _EntityBinding] = {
    TechnicalEntityType.SPACE_PLATFORM_CLASS: _EntityBinding(
        tech.SpacePlatformClass, "Space Platform Class"
    ),
    TechnicalEntityType.AIR_PLATFORM_CLASS: _EntityBinding(
        tech.AirPlatformClass, "Air Platform Class"
    ),
    TechnicalEntityType.GROUND_PLATFORM_CLASS: _EntityBinding(
        tech.GroundPlatformClass, "Ground Platform Class"
    ),
    TechnicalEntityType.SEA_SURFACE_PLATFORM_CLASS: _EntityBinding(
        tech.SeaSurfacePlatformClass, "Sea Surface Platform Class"
    ),
    TechnicalEntityType.SUBSURFACE_PLATFORM_CLASS: _EntityBinding(
        tech.SubsurfacePlatformClass, "Subsurface Platform Class"
    ),
    TechnicalEntityType.RADAR_CLASS: _EntityBinding(tech.RadarClass, "Radar Class"),
    TechnicalEntityType.COM_EQUIPMENT: _EntityBinding(
        tech.COMEquipment, "COM Equipment"
    ),
    TechnicalEntityType.LASER: _EntityBinding(tech.Laser, "Laser"),
    TechnicalEntityType.GUN: _EntityBinding(tech.Gun, "Gun"),
    TechnicalEntityType.MISSILE: _EntityBinding(tech.Missile, "Missile"),
    TechnicalEntityType.WEAPON_SYSTEM: _EntityBinding(
        tech.WeaponSystem, "Weapon System"
    ),
}


def _get_mission_or_raise(db: Session, mission_id: uuid.UUID) -> Mission:
    stmt = select(Mission).where(
        Mission.id == mission_id, Mission.deleted_at.is_(None)
    )
    mission = db.execute(stmt).scalar_one_or_none()
    if mission is None:
        raise NotFoundError(f"Mission {mission_id} not found")
    return mission


def _resolve_binding(entity_type: TechnicalEntityType) -> _EntityBinding:
    binding = _ENTITY_QUERY_MAP.get(entity_type)
    if binding is None:
        raise BusinessValidationError(
            f"Unsupported entity type: {entity_type.value}"
        )
    return binding


def _base_statement(binding: _EntityBinding, search: str | None) -> Select:
    model = binding.model
    stmt = select(model).where(model.to_be_removed.is_(False))
    if search is not None:
        stmt = stmt.where(model.english_name.ilike(f"%{search}%"))
    return stmt


def get_filter_options(db: Session, mission_id: uuid.UUID) -> FilterOptionsResponse:
    _get_mission_or_raise(db, mission_id)

    options: list[FilterOptionDescriptor] = []
    for entity_type, binding in _ENTITY_QUERY_MAP.items():
        count_stmt = select(func.count()).select_from(binding.model).where(
            binding.model.to_be_removed.is_(False)
        )
        options.append(
            FilterOptionDescriptor(
                entity_type=entity_type,
                label=binding.label,
                entity_count=db.execute(count_stmt).scalar_one(),
            )
        )
    return FilterOptionsResponse(options=options)


def list_threat_entities(
    db: Session,
    mission_id: uuid.UUID,
    entity_types: list[TechnicalEntityType],
    search: str | None,
    limit: int,
    offset: int,
) -> ThreatEntityListResponse:
    _get_mission_or_raise(db, mission_id)

    total = 0
    items: list[ThreatEntityOption] = []
    remaining_offset = offset

    for entity_type in entity_types:
        binding = _resolve_binding(entity_type)
        model = binding.model

        count_stmt = select(func.count()).select_from(
            _base_statement(binding, search).subquery()
        )
        entity_total = db.execute(count_stmt).scalar_one()
        total += entity_total

        if len(items) >= limit:
            continue
        if remaining_offset >= entity_total:
            remaining_offset -= entity_total
            continue

        stmt = (
            _base_statement(binding, search)
            .order_by(model.english_name, model.object_id)
            .offset(remaining_offset)
            .limit(limit - len(items))
        )
        remaining_offset = 0

        for row in db.execute(stmt).scalars():
            items.append(
                ThreatEntityOption(
                    entity_type=entity_type,
                    object_id=row.object_id,
                    english_name=row.english_name,
                )
            )

    return ThreatEntityListResponse(
        items=items, total=total, limit=limit, offset=offset
    )


def _validate_selection(
    db: Session, entity_type: TechnicalEntityType, object_ids: list[str]
) -> None:
    binding = _resolve_binding(entity_type)
    model = binding.model

    stmt = select(model.object_id).where(
        model.object_id.in_(object_ids), model.to_be_removed.is_(False)
    )
    found = set(db.execute(stmt).scalars())
    missing = sorted(set(object_ids) - found)
    if missing:
        preview = ", ".join(missing[:5])
        suffix = f" (and {len(missing) - 5} more)" if len(missing) > 5 else ""
        raise NotFoundError(
            f"Unknown or removed {entity_type.value} object_ids: {preview}{suffix}"
        )


def create_threat_export(
    db: Session, mission_id: uuid.UUID, request: ThreatExportRequest
) -> ThreatExportResponse:
    mission = _get_mission_or_raise(db, mission_id)

    for selection in request.selections:
        _validate_selection(db, selection.entity_type, selection.object_ids)

    # 1. load the selected entities and their nested children
    #    (EmMode/WaveForm for radar, OptronicMode for laser)
    # 2. serialise to tech.xml / tact.xml / comms.xml + NRD per the XSD
    # 3. persist ThreatExport rows, mint pre-signed URLs with expiry
    raise NotImplementedError

Design points worth confirming:

english_name isn't unique and isn't a stable key, so the list endpoint returns object_id as the value and english_name as the label. LP must send back object_id. If you return names only, two identically-named radar classes become unselectable.

The list endpoint needs pagination and search — some of these tables will have thousands of rows and LP can't render an unbounded dropdown. Offset paging across multiple entity types in one call is a bit awkward (the loop above handles it); if Mikkel prefers, one call per entity type is cleaner but chattier for LP.

_validate_selection rejects unknown or tombstoned IDs rather than silently dropping them, so an operator can't get a quietly incomplete export.

filter-options returns counts so LP can grey out empty types. It's mission-scoped to match the doc even though nothing about it depends on the mission — still your open question for Mikkel.

nrd_tech_models is assumed as the module holding the ingested NRD technical entities, with object_id, english_name, to_be_removed on each. Adjust names to whatever the ingest side actually produced.

Send the XSD when you're ready and I'll do the XML generation layer.

test cases for this feature

Thought for 11s

Test file below, following the HTTP-client-only convention with local imports and your docstring style.

tests/test_threat_export.py
python
"""Tests for the threat library export filter, selection and export endpoints."""

import uuid
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
def seeded_nrd(db_session: Session) -> dict[str, list[str]]:
    """Seeds a minimal NRD technical dataset and returns object ids by type."""
    from app.models import nrd_tech_models as tech

    air = [
        tech.AirPlatformClass(
            object_id="AIR-001", english_name="Fulcrum", to_be_removed=False
        ),
        tech.AirPlatformClass(
            object_id="AIR-002", english_name="Flanker", to_be_removed=False
        ),
        tech.AirPlatformClass(
            object_id="AIR-003", english_name="Retired Airframe", to_be_removed=True
        ),
    ]
    space = [
        tech.SpacePlatformClass(
            object_id="SPC-001", english_name="Recon Satellite", to_be_removed=False
        ),
    ]
    radar = [
        tech.RadarClass(
            object_id="RAD-001", english_name="Fan Song", to_be_removed=False
        ),
        tech.RadarClass(
            object_id="RAD-002", english_name="Flanker", to_be_removed=False
        ),
    ]
    db_session.add_all([*air, *space, *radar])
    db_session.commit()

    return {
        "AirPlatformClass": ["AIR-001", "AIR-002"],
        "SpacePlatformClass": ["SPC-001"],
        "RadarClass": ["RAD-001", "RAD-002"],
        "removed": ["AIR-003"],
    }


# ---------------------------------------------------------------------------
# GET /missions/{id}/exports/threat/filter-options
# ---------------------------------------------------------------------------
class TestGetFilterOptions:
    def test_returns_all_eleven_entity_types(
        self, client: TestClient, mission_id: str
    ) -> None:
        """Returns one descriptor for every supported technical entity type."""
        response = client.get(f"/missions/{mission_id}/exports/threat/filter-options")

        assert response.status_code == 200
        options = response.json()["options"]
        assert len(options) == 11

    def test_returns_expected_entity_type_values(
        self, client: TestClient, mission_id: str
    ) -> None:
        """Returns entity type values matching the tech.xsd element names."""
        response = client.get(f"/missions/{mission_id}/exports/threat/filter-options")

        returned = {option["entity_type"] for option in response.json()["options"]}
        assert returned == {
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

    def test_returns_counts_excluding_removed_entities(
        self, client: TestClient, mission_id: str, seeded_nrd: dict[str, list[str]]
    ) -> None:
        """Excludes entities flagged ToBeRemoved from the reported counts."""
        response = client.get(f"/missions/{mission_id}/exports/threat/filter-options")

        counts = {
            option["entity_type"]: option["entity_count"]
            for option in response.json()["options"]
        }
        assert counts["AirPlatformClass"] == 2

    def test_returns_zero_count_for_unpopulated_entity_type(
        self, client: TestClient, mission_id: str, seeded_nrd: dict[str, list[str]]
    ) -> None:
        """Returns a zero count rather than omitting an unpopulated entity type."""
        response = client.get(f"/missions/{mission_id}/exports/threat/filter-options")

        counts = {
            option["entity_type"]: option["entity_count"]
            for option in response.json()["options"]
        }
        assert counts["Gun"] == 0

    def test_returns_404_for_unknown_mission(self, client: TestClient) -> None:
        """Returns 404 for a well-formed but unmapped mission id."""
        response = client.get(
            f"/missions/{uuid.uuid4()}/exports/threat/filter-options"
        )

        assert response.status_code == 404

    def test_returns_404_for_soft_deleted_mission(
        self, client: TestClient, mission_id: str
    ) -> None:
        """Returns 404 once the parent mission has been soft deleted."""
        client.delete(f"/missions/{mission_id}")

        response = client.get(f"/missions/{mission_id}/exports/threat/filter-options")

        assert response.status_code == 404

    def test_returns_422_for_malformed_mission_id(self, client: TestClient) -> None:
        """Returns 422 for a mission id that is not a valid UUID."""
        response = client.get("/missions/not-a-uuid/exports/threat/filter-options")

        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /missions/{id}/exports/threat/entities
# ---------------------------------------------------------------------------
class TestListThreatEntities:
    def test_returns_entities_for_a_single_type(
        self, client: TestClient, mission_id: str, seeded_nrd: dict[str, list[str]]
    ) -> None:
        """Returns only entities belonging to the requested entity type."""
        response = client.get(
            f"/missions/{mission_id}/exports/threat/entities",
            params={"entity_types": ["AirPlatformClass"]},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert {item["object_id"] for item in body["items"]} == {"AIR-001", "AIR-002"}

    def test_returns_entities_across_multiple_types(
        self, client: TestClient, mission_id: str, seeded_nrd: dict[str, list[str]]
    ) -> None:
        """Aggregates entities from every requested entity type into one page."""
        response = client.get(
            f"/missions/{mission_id}/exports/threat/entities",
            params={"entity_types": ["AirPlatformClass", "SpacePlatformClass"]},
        )

        body = response.json()
        assert body["total"] == 3
        assert {item["entity_type"] for item in body["items"]} == {
            "AirPlatformClass",
            "SpacePlatformClass",
        }

    def test_returns_object_id_and_english_name_for_each_entity(
        self, client: TestClient, mission_id: str, seeded_nrd: dict[str, list[str]]
    ) -> None:
        """Returns object_id as the selection value alongside the display name."""
        response = client.get(
            f"/missions/{mission_id}/exports/threat/entities",
            params={"entity_types": ["SpacePlatformClass"]},
        )

        item = response.json()["items"][0]
        assert item["object_id"] == "SPC-001"
        assert item["english_name"] == "Recon Satellite"

    def test_excludes_entities_flagged_for_removal(
        self, client: TestClient, mission_id: str, seeded_nrd: dict[str, list[str]]
    ) -> None:
        """Omits entities flagged ToBeRemoved from the entity list."""
        response = client.get(
            f"/missions/{mission_id}/exports/threat/entities",
            params={"entity_types": ["AirPlatformClass"]},
        )

        returned = {item["object_id"] for item in response.json()["items"]}
        assert "AIR-003" not in returned

    def test_filters_by_case_insensitive_search_term(
        self, client: TestClient, mission_id: str, seeded_nrd: dict[str, list[str]]
    ) -> None:
        """Matches the search term against english_name without case sensitivity."""
        response = client.get(
            f"/missions/{mission_id}/exports/threat/entities",
            params={"entity_types": ["AirPlatformClass"], "search": "fulc"},
        )

        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["object_id"] == "AIR-001"

    def test_returns_duplicate_english_names_as_distinct_entities(
        self, client: TestClient, mission_id: str, seeded_nrd: dict[str, list[str]]
    ) -> None:
        """Returns entities sharing an english_name as separate selectable rows."""
        response = client.get(
            f"/missions/{mission_id}/exports/threat/entities",
            params={
                "entity_types": ["AirPlatformClass", "RadarClass"],
                "search": "Flanker",
            },
        )

        body = response.json()
        assert body["total"] == 2
        assert {item["object_id"] for item in body["items"]} == {"AIR-002", "RAD-002"}

    def test_returns_empty_page_for_unmatched_search(
        self, client: TestClient, mission_id: str, seeded_nrd: dict[str, list[str]]
    ) -> None:
        """Returns an empty item list and zero total when nothing matches."""
        response = client.get(
            f"/missions/{mission_id}/exports/threat/entities",
            params={"entity_types": ["AirPlatformClass"], "search": "zzzz"},
        )

        body = response.json()
        assert body["items"] == []
        assert body["total"] == 0

    def test_applies_limit_to_returned_items(
        self, client: TestClient, mission_id: str, seeded_nrd: dict[str, list[str]]
    ) -> None:
        """Caps the returned item count at the requested limit."""
        response = client.get(
            f"/missions/{mission_id}/exports/threat/entities",
            params={"entity_types": ["AirPlatformClass"], "limit": 1},
        )

        body = response.json()
        assert len(body["items"]) == 1
        assert body["total"] == 2

    def test_applies_offset_across_entity_type_boundary(
        self, client: TestClient, mission_id: str, seeded_nrd: dict[str, list[str]]
    ) -> None:
        """Continues paging into the next entity type once the first is exhausted."""
        response = client.get(
            f"/missions/{mission_id}/exports/threat/entities",
            params={
                "entity_types": ["AirPlatformClass", "SpacePlatformClass"],
                "limit": 10,
                "offset": 2,
            },
        )

        body = response.json()
        assert body["total"] == 3
        assert [item["object_id"] for item in body["items"]] == ["SPC-001"]

    def test_paginates_without_overlap_or_omission(
        self, client: TestClient, mission_id: str, seeded_nrd: dict[str, list[str]]
    ) -> None:
        """Returns every entity exactly once when paged through sequentially."""
        collected: list[str] = []
        for offset in range(0, 3):
            response = client.get(
                f"/missions/{mission_id}/exports/threat/entities",
                params={
                    "entity_types": ["AirPlatformClass", "SpacePlatformClass"],
                    "limit": 1,
                    "offset": offset,
                },
            )
            collected.extend(item["object_id"] for item in response.json()["items"])

        assert sorted(collected) == ["AIR-001", "AIR-002", "SPC-001"]

    def test_returns_422_when_entity_types_omitted(
        self, client: TestClient, mission_id: str
    ) -> None:
        """Returns 422 when the required entity_types parameter is absent."""
        response = client.get(f"/missions/{mission_id}/exports/threat/entities")

        assert response.status_code == 422

    def test_returns_422_for_unrecognised_entity_type(
        self, client: TestClient, mission_id: str
    ) -> None:
        """Returns 422 for an entity type outside the tech.xsd element set."""
        response = client.get(
            f"/missions/{mission_id}/exports/threat/entities",
            params={"entity_types": ["PassiveSensor"]},
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
        self,
        client: TestClient,
        mission_id: str,
        params: dict[str, Any],
        reason: str,
    ) -> None:
        """Returns 422 for pagination and search parameters outside their bounds."""
        response = client.get(
            f"/missions/{mission_id}/exports/threat/entities",
            params={"entity_types": ["AirPlatformClass"], **params},
        )

        assert response.status_code == 422, reason

    def test_returns_404_for_unknown_mission(
        self, client: TestClient, seeded_nrd: dict[str, list[str]]
    ) -> None:
        """Returns 404 for a well-formed but unmapped mission id."""
        response = client.get(
            f"/missions/{uuid.uuid4()}/exports/threat/entities",
            params={"entity_types": ["AirPlatformClass"]},
        )

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /missions/{id}/exports/threat
# ---------------------------------------------------------------------------
class TestCreateThreatExport:
    def test_returns_404_for_unknown_mission(
        self, client: TestClient, seeded_nrd: dict[str, list[str]]
    ) -> None:
        """Returns 404 for a well-formed but unmapped mission id."""
        response = client.post(
            f"/missions/{uuid.uuid4()}/exports/threat",
            json={
                "selections": [
                    {"entity_type": "AirPlatformClass", "object_ids": ["AIR-001"]}
                ]
            },
        )

        assert response.status_code == 404

    def test_returns_404_for_unknown_object_id(
        self, client: TestClient, mission_id: str, seeded_nrd: dict[str, list[str]]
    ) -> None:
        """Returns 404 when a selected object id is absent from the dataset."""
        response = client.post(
            f"/missions/{mission_id}/exports/threat",
            json={
                "selections": [
                    {
                        "entity_type": "AirPlatformClass",
                        "object_ids": ["AIR-001", "AIR-999"],
                    }
                ]
            },
        )

        assert response.status_code == 404

    def test_returns_404_for_entity_flagged_for_removal(
        self, client: TestClient, mission_id: str, seeded_nrd: dict[str, list[str]]
    ) -> None:
        """Rejects a selection referencing an entity flagged ToBeRemoved."""
        response = client.post(
            f"/missions/{mission_id}/exports/threat",
            json={
                "selections": [
                    {"entity_type": "AirPlatformClass", "object_ids": ["AIR-003"]}
                ]
            },
        )

        assert response.status_code == 404

    def test_returns_404_when_object_id_belongs_to_another_entity_type(
        self, client: TestClient, mission_id: str, seeded_nrd: dict[str, list[str]]
    ) -> None:
        """Rejects an object id that exists only under a different entity type."""
        response = client.post(
            f"/missions/{mission_id}/exports/threat",
            json={
                "selections": [
                    {"entity_type": "AirPlatformClass", "object_ids": ["RAD-001"]}
                ]
            },
        )

        assert response.status_code == 404

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
        response = client.post(
            f"/missions/{mission_id}/exports/threat",
            json={
                "selections": [{"entity_type": "AirPlatformClass", "object_ids": []}]
            },
        )

        assert response.status_code == 422

    def test_returns_422_for_duplicate_object_ids_within_a_selection(
        self, client: TestClient, mission_id: str
    ) -> None:
        """Returns 422 when a selection repeats the same object id."""
        response = client.post(
            f"/missions/{mission_id}/exports/threat",
            json={
                "selections": [
                    {
                        "entity_type": "AirPlatformClass",
                        "object_ids": ["AIR-001", "AIR-001"],
                    }
                ]
            },
        )

        assert response.status_code == 422

    def test_returns_422_for_repeated_entity_type(
        self, client: TestClient, mission_id: str
    ) -> None:
        """Returns 422 when the same entity type appears in two selections."""
        response = client.post(
            f"/missions/{mission_id}/exports/threat",
            json={
                "selections": [
                    {"entity_type": "AirPlatformClass", "object_ids": ["AIR-001"]},
                    {"entity_type": "AirPlatformClass", "object_ids": ["AIR-002"]},
                ]
            },
        )

        assert response.status_code == 422

    def test_returns_422_for_unrecognised_entity_type(
        self, client: TestClient, mission_id: str
    ) -> None:
        """Returns 422 for an entity type outside the tech.xsd element set."""
        response = client.post(
            f"/missions/{mission_id}/exports/threat",
            json={
                "selections": [
                    {"entity_type": "PassiveSensor", "object_ids": ["PSV-001"]}
                ]
            },
        )

        assert response.status_code == 422

    def test_returns_422_for_unexpected_field(
        self, client: TestClient, mission_id: str
    ) -> None:
        """Returns 422 for a request body carrying an undeclared field."""
        response = client.post(
            f"/missions/{mission_id}/exports/threat",
            json={
                "selections": [
                    {"entity_type": "AirPlatformClass", "object_ids": ["AIR-001"]}
                ],
                "persist_filter": True,
            },
        )

        assert response.status_code == 422

    def test_returns_422_when_object_ids_exceed_maximum(
        self, client: TestClient, mission_id: str
    ) -> None:
        """Returns 422 when a selection exceeds the per-type object id ceiling."""
        response = client.post(
            f"/missions/{mission_id}/exports/threat",
            json={
                "selections": [
                    {
                        "entity_type": "AirPlatformClass",
                        "object_ids": [f"AIR-{index:05d}" for index in range(5001)],
                    }
                ]
            },
        )

        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Cross-cutting
# ---------------------------------------------------------------------------
class TestThreatExportContract:
    def test_filter_options_are_independent_of_mission(
        self, client: TestClient, seeded_nrd: dict[str, list[str]]
    ) -> None:
        """Returns identical filter options for two distinct missions."""
        first = client.post("/missions", json=_MISSION_PAYLOAD).json()["id"]
        second = client.post("/missions", json=_MISSION_PAYLOAD).json()["id"]

        first_body = client.get(
            f"/missions/{first}/exports/threat/filter-options"
        ).json()
        second_body = client.get(
            f"/missions/{second}/exports/threat/filter-options"
        ).json()

        assert first_body == second_body

    def test_listed_entities_are_accepted_by_the_export_endpoint(
        self, client: TestClient, mission_id: str, seeded_nrd: dict[str, list[str]]
    ) -> None:
        """Accepts object ids returned by the entity list without a 404."""
        listed = client.get(
            f"/missions/{mission_id}/exports/threat/entities",
            params={"entity_types": ["AirPlatformClass"]},
        ).json()

        response = client.post(
            f"/missions/{mission_id}/exports/threat",
            json={
                "selections": [
                    {
                        "entity_type": "AirPlatformClass",
                        "object_ids": [item["object_id"] for item in listed["items"]],
                    }
                ]
            },
        )

        assert response.status_code != 404

Coverage gaps, deliberate:

The export happy path isn't tested because create_threat_export still raises NotImplementedError pending the XSD. Everything up to that line is covered — mission lookup, selection validation, schema rejection. test_listed_entities_are_accepted_by_the_export_endpoint asserts != 404 rather than == 201 for the same reason; tighten it to 201 and add file/expiry assertions once generation lands.

Not yet testable, worth tracking:

The four generated artifacts and their file_type values
expires_at being in the future and download_url being well-formed
Nested children pulled through for radar (EmMode → WaveForm) and laser (OptronicMode)
Whether two exports on one mission produce two threat_export row sets or supersede
Behaviour when the selection exceeds whatever timeout budget you settle on

seeded_nrd uses db_session directly since the NRD tables have no write API. That's the one place tests touch the DB rather than HTTP — if nrd_ingestion_service exposes a fixture already, prefer it. And it depends on clean_db truncating the NRD tech tables too; if those are seeded once per session rather than per test, the counts in TestGetFilterOptions will drift.