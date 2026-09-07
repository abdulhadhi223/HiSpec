1. app/schemas/threat_export_schemas.py (changed parts)
python
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
# Step 2 — entities under the selected types, grouped by type
# ---------------------------------------------------------------------------
class ThreatEntityOption(BaseModel):
    """A single selectable threat entity. `object_id` is the value to send back;
    `english_name` is display only and is not guaranteed unique."""

    model_config = ConfigDict(from_attributes=True)

    object_id: str
    english_name: str


class ThreatEntityGroup(BaseModel):
    """Entities for one entity type. `limit` and `offset` apply within a group."""

    entity_type: TechnicalEntityType
    label: str
    total: int
    items: list[ThreatEntityOption]


class ThreatEntityListResponse(BaseModel):
    groups: list[ThreatEntityGroup]
    limit: int
    offset: int

ThreatEntitySelection, ThreatExportRequest and the export responses are unchanged from before.

2. app/api/routers/threat_library_router.py (new)
python
"""Threat library reference-data endpoints. Not mission-scoped: the available
entity types and entities are identical for every mission."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.schemas.threat_export_schemas import (
    FilterOptionsResponse,
    TechnicalEntityType,
    ThreatEntityListResponse,
)

router = APIRouter(prefix="/threat-library", tags=["Threat Library"])


@router.get(
    "/filter-options",
    response_model=FilterOptionsResponse,
    status_code=status.HTTP_200_OK,
)
def get_filter_options(
    db: Annotated[Session, Depends(get_db)],
) -> FilterOptionsResponse:
    from app.services import threat_export_service

    return threat_export_service.get_filter_options(db=db)


@router.get(
    "/entities",
    response_model=ThreatEntityListResponse,
    status_code=status.HTTP_200_OK,
)
def list_threat_entities(
    entity_types: Annotated[list[TechnicalEntityType], Query(min_length=1)],
    db: Annotated[Session, Depends(get_db)],
    search: Annotated[str | None, Query(min_length=2, max_length=255)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ThreatEntityListResponse:
    from app.services import threat_export_service

    return threat_export_service.list_threat_entities(
        db=db,
        entity_types=entity_types,
        search=search,
        limit=limit,
        offset=offset,
    )

threat_export_router.py keeps only the POST, unchanged.

3. app/services/threat_export_service.py
python
"""Threat library export service."""

import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import BusinessValidationError, DatabaseError, NotFoundError
from app.models import enums
from app.models import nrd_tech_models as tech
from app.models.mission_models import Mission, ThreatExport
from app.schemas.threat_export_schemas import (
    FilterOptionDescriptor,
    FilterOptionsResponse,
    TechnicalEntityType,
    ThreatEntityGroup,
    ThreatEntityListResponse,
    ThreatEntityOption,
    ThreatExportFileResponse,
    ThreatExportRequest,
    ThreatExportResponse,
)

_EXPORT_TTL = timedelta(hours=24)


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


def _active_only(model: type) -> ColumnElement[bool]:
    """Restricts a statement to entities not flagged for removal in the NRD."""
    return model.to_be_removed == enums.BooleanEnum.FALSE


def _resolve_binding(entity_type: TechnicalEntityType) -> _EntityBinding:
    binding = _ENTITY_QUERY_MAP.get(entity_type)
    if binding is None:
        raise BusinessValidationError(f"Unsupported entity type: {entity_type.value}")
    return binding


def _base_statement(binding: _EntityBinding, search: str | None) -> Select:
    model = binding.model
    stmt = select(model).where(_active_only(model))
    if search is not None:
        stmt = stmt.where(model.english_name.ilike(f"%{search}%"))
    return stmt


def _get_mission_or_raise(db: Session, mission_id: uuid.UUID) -> Mission:
    stmt = select(Mission).where(Mission.id == mission_id, Mission.deleted_at.is_(None))
    mission = db.execute(stmt).scalar_one_or_none()
    if mission is None:
        raise NotFoundError(f"Mission {mission_id} not found")
    return mission


# ---------------------------------------------------------------------------
# Filter options
# ---------------------------------------------------------------------------
def get_filter_options(db: Session) -> FilterOptionsResponse:
    options: list[FilterOptionDescriptor] = []
    for entity_type, binding in _ENTITY_QUERY_MAP.items():
        count_stmt = (
            select(func.count())
            .select_from(binding.model)
            .where(_active_only(binding.model))
        )
        options.append(
            FilterOptionDescriptor(
                entity_type=entity_type,
                label=binding.label,
                entity_count=db.execute(count_stmt).scalar_one(),
            )
        )
    return FilterOptionsResponse(options=options)


# ---------------------------------------------------------------------------
# Entity listing
# ---------------------------------------------------------------------------
def list_threat_entities(
    db: Session,
    entity_types: list[TechnicalEntityType],
    search: str | None,
    limit: int,
    offset: int,
) -> ThreatEntityListResponse:
    groups: list[ThreatEntityGroup] = []

    for entity_type in dict.fromkeys(entity_types):
        binding = _resolve_binding(entity_type)
        model = binding.model

        count_stmt = select(func.count()).select_from(
            _base_statement(binding, search).subquery()
        )
        stmt = (
            _base_statement(binding, search)
            .order_by(model.english_name, model.object_id)
            .offset(offset)
            .limit(limit)
        )

        groups.append(
            ThreatEntityGroup(
                entity_type=entity_type,
                label=binding.label,
                total=db.execute(count_stmt).scalar_one(),
                items=[
                    ThreatEntityOption(
                        object_id=row.object_id, english_name=row.english_name
                    )
                    for row in db.execute(stmt).scalars()
                ],
            )
        )

    return ThreatEntityListResponse(groups=groups, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def _load_selected(
    db: Session, entity_type: TechnicalEntityType, object_ids: list[str]
) -> list[object]:
    """Loads the selected entities, raising if any id is unknown or removed."""
    binding = _resolve_binding(entity_type)
    model = binding.model

    stmt = select(model).where(
        model.object_id.in_(object_ids), _active_only(model)
    )
    rows = list(db.execute(stmt).scalars())

    missing = sorted(set(object_ids) - {row.object_id for row in rows})
    if missing:
        preview = ", ".join(missing[:5])
        suffix = f" (and {len(missing) - 5} more)" if len(missing) > 5 else ""
        raise NotFoundError(
            f"Unknown or removed {entity_type.value} object_ids: {preview}{suffix}"
        )
    return rows


def _build_demo_document(
    mission: Mission, selected: dict[TechnicalEntityType, list[object]]
) -> ET.ElementTree:
    """Builds the placeholder threat document pending the export XSD."""
    root = ET.Element("ThreatLibraryExport")
    root.set("missionId", str(mission.id))
    root.set("missionName", mission.name)
    root.set(
        "generatedAt", datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    root.set("schemaStatus", "PLACEHOLDER")

    technical = ET.SubElement(root, "Technical")
    for entity_type, rows in selected.items():
        group = ET.SubElement(technical, entity_type.value)
        group.set("count", str(len(rows)))
        for row in rows:
            entity = ET.SubElement(group, "Entity")
            entity.set("ObjectId", row.object_id)
            ET.SubElement(entity, "Name").text = row.name
            ET.SubElement(entity, "EnglishName").text = row.english_name
            ET.SubElement(entity, "EntityType").text = entity_type.value

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    return tree


def _write_export_file(
    export_id: uuid.UUID, mission_id: uuid.UUID, tree: ET.ElementTree
) -> Path:
    directory = Path(settings.EXPORT_STORAGE_ROOT) / str(mission_id)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"threat-{export_id}.xml"
        tree.write(path, encoding="utf-8", xml_declaration=True)
    except OSError as exc:
        raise DatabaseError(f"Failed to write export artifact: {exc}") from exc
    return path


def create_threat_export(
    db: Session, mission_id: uuid.UUID, request: ThreatExportRequest
) -> ThreatExportResponse:
    mission = _get_mission_or_raise(db, mission_id)

    selected: dict[TechnicalEntityType, list[object]] = {
        selection.entity_type: _load_selected(
            db, selection.entity_type, selection.object_ids
        )
        for selection in request.selections
    }

    export_id = uuid.uuid4()
    tree = _build_demo_document(mission, selected)
    path = _write_export_file(export_id, mission_id, tree)
    expires_at = datetime.now(timezone.utc) + _EXPORT_TTL

    record = ThreatExport(
        id=export_id,
        mission_id=mission_id,
        file_type=enums.FileType.TECH_XML,
        file_path=str(path),
        download_url=f"{settings.EXPORT_DOWNLOAD_BASE_URL}/{export_id}",
        expires_at=expires_at,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return ThreatExportResponse(
        mission_id=mission_id,
        exported_entity_count=sum(len(rows) for rows in selected.values()),
        files=[ThreatExportFileResponse.model_validate(record)],
    )