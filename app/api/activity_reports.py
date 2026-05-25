"""API router for Activity Report endpoints."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.common_models import Mission
from app.models.ew_track_models import (
    ActivityReport,
    ActivityReportInstance,
    ActivityReportMission,
)
from app.schemas.activity_report import (
    ActivityReportCreate,
    ActivityReportDetailResponse,
    ActivityReportInstanceCreate,
    ActivityReportInstanceResponse,
    ActivityReportMissionResponse,
    ActivityReportResponse,
    ActivityReportUpdate,
)
from app.services import activity_report_service as svc
from app.services.activity_report_service import ActivityReportFilter

router = APIRouter(
    prefix="/activity-reports",
    tags=["Activity Reports"],
)

# ─────────────────────────────────────────────────────────────────────────────
# ActivityReport
# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=ActivityReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Activity Report",
    description=(
        "Creates a new Activity Report.\n\n"
        "Notes:\n"
        "- `mission_ids` may be supplied to automatically create mission links.\n"
        "- `start_at` and `end_at` define the operational window of this report "
        "(optional, do not affect instance creation).\n"
        "- A 409 Conflict is returned if an identical mission link already exists."
    ),
)
def create_report(
    data: ActivityReportCreate,
    db: Session = Depends(get_db),
) -> ActivityReport:  # type: ignore[return-value]
    try:
        return svc.create_activity_report(db, data)
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Duplicate Activity Report or mission link conflict",
        )


@router.get(
    "",
    response_model=list[ActivityReportResponse],
    summary="List Activity Reports",
    description=(
        "Retrieve Activity Reports with optional filters.\n\n"
        "Filtering Rules:\n"
        "- `submitted_by`: exact match\n"
        "- `from_dt` / `to_dt`: filters by the report's `start_at` field\n"
        "- `mission_id`: returns only reports linked to the specified mission\n\n"
        "All filters are optional. Pagination supported via `skip` and `limit`."
    ),
)
def list_reports(
    submitted_by: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    from_dt: datetime | None = Query(None),
    to_dt: datetime | None = Query(None),
    mission_id: uuid.UUID | None = Query(None),
    db: Session = Depends(get_db),
) -> list[ActivityReport]:  # type: ignore[return-value]
    if from_dt and to_dt and from_dt > to_dt:
        raise HTTPException(
            status_code=422,
            detail="from_dt must be earlier than or equal to to_dt",
        )
    filters = ActivityReportFilter(
        submitted_by=submitted_by,
        from_dt=from_dt,
        to_dt=to_dt,
        mission_id=mission_id,
    )
    return svc.list_activity_reports(db, filters, skip, limit)


@router.get(
    "/{report_id}",
    response_model=ActivityReportDetailResponse,
    summary="Get Activity Report (Detailed)",
    description=(
        "Returns a single Activity Report with all associated instances "
        "and mission links.\n"
        "Includes report metadata, snapshot instances, and linked missions.\n"
        "Returns 404 if the report does not exist."
    ),
)
def get_report(
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ActivityReport:  # type: ignore[return-value]
    report = svc.get_activity_report_detail(db, report_id)
    if not report:
        raise HTTPException(
            status_code=404, detail="Activity Report not found"
        )
    return report


@router.patch(
    "/{report_id}",
    response_model=ActivityReportResponse,
    summary="Update Activity Report",
    description=(
        "Updates one or more metadata fields of an existing Activity Report.\n\n"
        "Editable fields: `name`, `start_at`, `end_at`, `classification`.\n"
        "Returns 404 if the report does not exist."
    ),
)
def update_report(
    report_id: uuid.UUID,
    data: ActivityReportUpdate,
    db: Session = Depends(get_db),
) -> ActivityReport:  # type: ignore[return-value]
    report = svc.update_activity_report(db, report_id, data)
    if not report:
        raise HTTPException(
            status_code=404, detail="Activity Report not found"
        )
    return report


@router.delete(
    "/{report_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Activity Report",
    description=(
        "Deletes the specified Activity Report and all related instances "
        "and mission links.\n"
        "Returns 404 if the report does not exist."
    ),
)
def delete_report(
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> None:
    ok = svc.delete_activity_report(db, report_id)
    if not ok:
        raise HTTPException(
            status_code=404, detail="Activity Report not found"
        )


# ─────────────────────────────────────────────────────────────────────────────
# ActivityReportInstance
# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/{report_id}/instances",
    response_model=ActivityReportInstanceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add Instance to Activity Report",
    description=(
        "Adds an Activity Report Instance.\n\n"
        "Two creation modes are supported:\n\n"
        "**1) Auto Mode (recommended)**\n"
        "- Provide only `track_id`.\n"
        "- The system automatically extracts earliest/latest EWTrackPoint, "
        "last known position, EWTrackEmitter, platform metadata, "
        "hostility, classification, and source system.\n\n"
        "**2) Manual Mode**\n"
        "- Omit `track_id` and provide ALL snapshot fields manually.\n"
        "- Required: `signal_type`, `hostility`, `first_seen_dtg`, "
        "`last_seen_dtg`, `last_position_latitude_dd`, "
        "`last_position_longitude_dd`, `classification`, `source_system`.\n\n"
        "**Error Codes:**\n"
        "- 409: instance with same `(report_id, track_id)` already exists\n"
        "- 422: missing required fields in manual mode"
    ),
)
def add_instance(
    report_id: uuid.UUID,
    data: ActivityReportInstanceCreate,
    db: Session = Depends(get_db),
) -> ActivityReportInstance:  # type: ignore[return-value]
    try:
        data.activity_report_id = report_id
        return svc.add_instance(db, data)
    except ValueError as e:
        msg = str(e)
        if "already added" in msg or "already exists" in msg:
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=422, detail=msg)
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Instance already exists for this (report_id, track_id) pair",
        )


@router.get(
    "/{report_id}/instances",
    response_model=list[ActivityReportInstanceResponse],
    summary="List Instances in Activity Report",
    description=(
        "Returns all Activity Report Instances for the given report.\n"
        "Instances are sorted by `first_seen_dtg`."
    ),
)
def list_instances(
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> list[ActivityReportInstance]:  # type: ignore[return-value]
    return svc.list_instances(db, report_id)


@router.get(
    "/{report_id}/instances/{instance_id}",
    response_model=ActivityReportInstanceResponse,
    summary="Get Activity Report Instance",
    description=(
        "Returns a single Activity Report Instance.\n"
        "Ensures that the instance belongs to the specified activity report.\n"
        "Returns 404 if not found or mismatched."
    ),
)
def get_instance(
    report_id: uuid.UUID,
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ActivityReportInstance:  # type: ignore[return-value]
    inst = svc.get_instance(db, instance_id)
    if not inst or inst.activity_report_id != report_id:
        raise HTTPException(status_code=404, detail="Instance not found")
    return inst


@router.delete(
    "/{report_id}/instances/{instance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Activity Report Instance",
    description=(
        "Deletes a single Activity Report Instance.\n"
        "Deleting an instance does not delete the parent report.\n"
        "Returns 404 if the instance does not belong to the report."
    ),
)
def delete_instance(
    report_id: uuid.UUID,
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> None:
    inst = svc.get_instance(db, instance_id)
    if not inst or inst.activity_report_id != report_id:
        raise HTTPException(status_code=404, detail="Instance not found")
    svc.delete_instance(db, instance_id)


# ─────────────────────────────────────────────────────────────────────────────
# ActivityReportMission
# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/{report_id}/missions/{mission_id}",
    response_model=ActivityReportMissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Link Mission to Activity Report",
    description=(
        "Creates a link between the Activity Report and the specified Mission.\n"
        "A 409 Conflict is returned if that mission is already linked."
    ),
)
def link_mission(
    report_id: uuid.UUID,
    mission_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ActivityReportMission:  # type: ignore[return-value]
    if not db.get(Mission, mission_id):
        raise HTTPException(status_code=404, detail="Mission not found")
    try:
        return svc.link_mission(db, report_id, mission_id)
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Mission already linked to this report",
        )


@router.delete(
    "/{report_id}/missions/{mission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unlink Mission from Activity Report",
    description=(
        "Removes a mission link from the Activity Report.\n"
        "If the link does not exist, a 404 is returned."
    ),
)
def unlink_mission(
    report_id: uuid.UUID,
    mission_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> None:
    ok = svc.unlink_mission(db, report_id, mission_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Mission link not found")


@router.get(
    "/{report_id}/missions",
    response_model=list[ActivityReportMissionResponse],
    summary="List Linked Missions",
    description=(
        "Returns all missions linked to the specified Activity Report.\n"
        "Links are stored in the `activity_report_mission` table."
    ),
)
def list_missions(
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> list[ActivityReportMission]:  # type: ignore[return-value]
    return svc.list_missions_for_report(db, report_id)
