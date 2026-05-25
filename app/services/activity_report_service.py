"""Service layer for Activity Report operations."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.models.ew_track_models import (
    ActivityReport,
    ActivityReportInstance,
    ActivityReportMission,
    EWTrack,
    EWTrackEmitter,
    EWTrackPoint,
)
from app.schemas.activity_report import (
    ActivityReportCreate,
    ActivityReportInstanceCreate,
    ActivityReportUpdate,
)

# ─────────────────────────────────────────────────────────────────────────────
# Filter dataclass
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ActivityReportFilter:
    submitted_by: str | None = None
    from_dt: datetime | None = None
    to_dt: datetime | None = None
    mission_id: uuid.UUID | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Utility helpers
# ─────────────────────────────────────────────────────────────────────────────


def _get_track_points(
    db: Session,
    track_id: uuid.UUID,
) -> tuple[EWTrackPoint | None, EWTrackPoint | None]:
    """Return earliest and latest EWTrackPoint for snapshot."""
    try:
        earliest = (
            db.execute(
                select(EWTrackPoint)
                .where(EWTrackPoint.track_id == track_id)
                .order_by(EWTrackPoint.observed_at.asc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        latest = (
            db.execute(
                select(EWTrackPoint)
                .where(EWTrackPoint.track_id == track_id)
                .order_by(EWTrackPoint.observed_at.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        return earliest, latest
    except SQLAlchemyError as e:
        raise e


def _get_latest_emitter(
    db: Session,
    track_id: uuid.UUID,
) -> EWTrackEmitter | None:
    """Return EWTrackEmitter with the most recent last_seen_at."""
    try:
        return (
            db.execute(
                select(EWTrackEmitter)
                .where(EWTrackEmitter.track_id == track_id)
                .order_by(EWTrackEmitter.last_seen_at.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
    except SQLAlchemyError as e:
        raise e


def _auto_populate_instance_fields(
    db: Session,
    track: EWTrack,
) -> dict[str, Any]:
    """Produce dict of fields required by ActivityReportInstance."""
    earliest, latest = _get_track_points(db, track.id)
    emitter = _get_latest_emitter(db, track.id)

    snapshot: dict[str, Any] = {}

    # Always set these keys; None when track has no points yet
    snapshot["first_seen_dtg"]           = earliest.observed_at if earliest else None
    snapshot["last_seen_dtg"]            = latest.observed_at   if latest   else None
    snapshot["last_position_latitude_dd"]  = latest.lat          if latest   else None
    snapshot["last_position_longitude_dd"] = latest.lon          if latest   else None
    snapshot["last_position_error_m"]      = int(latest.error_m) if (latest and latest.error_m is not None) else None

    snapshot.update(
        {
            "signal_type": emitter.signal_type if emitter else None,
            "hostility": track.hostility,
            "classification": track.classification,
            "source_system": track.source_system,
        }
    )

    if emitter:
        snapshot.update(
            {
                "emitter_id": emitter.emitter_id_sensor,
                "emitter_name": emitter.emitter_name,
                "emitter_confidence": emitter.emitter_confidence,
                "emitter_country_code": emitter.emitter_country_code,
                "emitter_country_name": emitter.emitter_country_name,
            }
        )

    snapshot.update(
        {
            "platform_category": track.platform_category,
            "platform_name": track.platform_name,
            "platform_id": track.platform_id,
            "platform_class": track.platform_class,
        }
    )

    return snapshot


def _validate_manual_mode(payload: dict[str, Any]) -> None:
    """Raise ValueError if required manual snapshot fields are missing."""
    required = [
        "signal_type",
        "hostility",
        "first_seen_dtg",
        "last_seen_dtg",
        "last_position_latitude_dd",
        "last_position_longitude_dd",
        "classification",
        "source_system",
    ]
    missing = [f for f in required if payload.get(f) is None]
    if missing:
        raise ValueError(
            f"Missing required fields for manual instance: {missing}"
        )


def _resolve_instance_payload(
    db: Session,
    data: ActivityReportInstanceCreate,
) -> dict[str, Any]:
    """Resolve final instance payload.

    Auto-populates from EWTrack if track_id is provided,
    otherwise validates all required manual snapshot fields are present.
    """
    payload = data.model_dump(exclude_unset=True)

    if not data.track_id:
        _validate_manual_mode(payload)
        return payload

    track = db.get(EWTrack, data.track_id)
    if not track:
        raise ValueError("Track not found for provided track_id.")

    auto = _auto_populate_instance_fields(db, track)
    # Position/time fields always come from auto (None if track has no points).
    # All other auto fields only override the payload when they have a value.
    _ALWAYS_FROM_AUTO = {
        "first_seen_dtg", "last_seen_dtg",
        "last_position_latitude_dd", "last_position_longitude_dd",
        "last_position_error_m",
    }
    for key, value in auto.items():
        if key in _ALWAYS_FROM_AUTO or value is not None:
            payload[key] = value
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# ActivityReport CRUD
# ─────────────────────────────────────────────────────────────────────────────


def create_activity_report(
    db: Session,
    data: ActivityReportCreate,
) -> ActivityReport:
    """Create ActivityReport and link missions (if any)."""
    try:
        payload = data.model_dump(exclude={"mission_ids"})
        report = ActivityReport(**payload)
        db.add(report)
        db.flush()

        for mission_id in data.mission_ids or []:
            arm = ActivityReportMission(
                activity_report_id=report.id,
                mission_id=mission_id,
            )
            db.add(arm)

        db.commit()
        db.refresh(report)
        return report
    except (IntegrityError, SQLAlchemyError) as e:
        db.rollback()
        raise e


def get_activity_report(
    db: Session,
    report_id: uuid.UUID,
) -> ActivityReport | None:
    """Return a single ActivityReport by ID."""
    return db.get(ActivityReport, report_id)


def get_activity_report_detail(
    db: Session,
    report_id: uuid.UUID,
) -> ActivityReport | None:
    """Load ActivityReport with instances and missions eagerly."""
    try:
        return (
            db.execute(
                select(ActivityReport)
                .where(ActivityReport.id == report_id)
                .options(
                    selectinload(ActivityReport.instances),
                    selectinload(ActivityReport.report_missions),
                )
            )
            .scalar_one_or_none()
        )
    except SQLAlchemyError as e:
        raise e


def list_activity_reports(
    db: Session,
    filters: ActivityReportFilter,
    skip: int = 0,
    limit: int = 100,
) -> list[ActivityReport]:
    """List ActivityReports with optional filters and pagination."""
    try:
        stmt = select(ActivityReport)

        if filters.submitted_by:
            stmt = stmt.where(
                ActivityReport.submitted_by == filters.submitted_by
            )
        if filters.from_dt:
            stmt = stmt.where(ActivityReport.start_at >= filters.from_dt)
        if filters.to_dt:
            stmt = stmt.where(ActivityReport.start_at <= filters.to_dt)
        if filters.mission_id:
            stmt = stmt.join(ActivityReport.report_missions).where(
                ActivityReportMission.mission_id == filters.mission_id
            )

        results = (
            db.execute(stmt.offset(skip).limit(limit)).scalars().all()
        )
        return list(results)
    except SQLAlchemyError as e:
        raise e


def update_activity_report(
    db: Session,
    report_id: uuid.UUID,
    data: ActivityReportUpdate,
) -> ActivityReport | None:
    """Update metadata fields of an existing ActivityReport."""
    report = db.get(ActivityReport, report_id)
    if not report:
        return None

    try:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(report, field, value)
        db.commit()
        db.refresh(report)
        return report
    except (IntegrityError, SQLAlchemyError) as e:
        db.rollback()
        raise e


def delete_activity_report(
    db: Session,
    report_id: uuid.UUID,
) -> bool:
    """Delete an ActivityReport and all related records."""
    report = db.get(ActivityReport, report_id)
    if not report:
        return False

    try:
        db.delete(report)
        db.commit()
        return True
    except SQLAlchemyError as e:
        db.rollback()
        raise e


# ─────────────────────────────────────────────────────────────────────────────
# ActivityReportInstance
# ─────────────────────────────────────────────────────────────────────────────


def add_instance(
    db: Session,
    data: ActivityReportInstanceCreate,
) -> ActivityReportInstance:
    """Add an instance to an ActivityReport."""
    try:
        payload = _resolve_instance_payload(db, data)
        instance = ActivityReportInstance(**payload)
        db.add(instance)
        db.commit()
        db.refresh(instance)
        return instance
    except (IntegrityError, SQLAlchemyError) as e:
        db.rollback()
        raise e


def get_instance(
    db: Session,
    instance_id: uuid.UUID,
) -> ActivityReportInstance | None:
    """Return a single ActivityReportInstance by ID."""
    return db.get(ActivityReportInstance, instance_id)


def list_instances(
    db: Session,
    activity_report_id: uuid.UUID,
) -> list[ActivityReportInstance]:
    """Return all instances for an ActivityReport ordered by first_seen_dtg."""
    try:
        results = (
            db.execute(
                select(ActivityReportInstance)
                .where(
                    ActivityReportInstance.activity_report_id
                    == activity_report_id
                )
                .order_by(ActivityReportInstance.first_seen_dtg.asc())
            )
            .scalars()
            .all()
        )
        return list(results)
    except SQLAlchemyError as e:
        raise e


def delete_instance(
    db: Session,
    instance_id: uuid.UUID,
) -> bool:
    """Delete a single ActivityReportInstance."""
    instance = db.get(ActivityReportInstance, instance_id)
    if not instance:
        return False

    try:
        db.delete(instance)
        db.commit()
        return True
    except SQLAlchemyError as e:
        db.rollback()
        raise e


# ─────────────────────────────────────────────────────────────────────────────
# ActivityReportMission
# ─────────────────────────────────────────────────────────────────────────────


def link_mission(
    db: Session,
    activity_report_id: uuid.UUID,
    mission_id: uuid.UUID,
) -> ActivityReportMission:
    """Link a Mission to an ActivityReport."""
    try:
        arm = ActivityReportMission(
            activity_report_id=activity_report_id,
            mission_id=mission_id,
        )
        db.add(arm)
        db.commit()
        db.refresh(arm)
        return arm
    except (IntegrityError, SQLAlchemyError) as e:
        db.rollback()
        raise e


def unlink_mission(
    db: Session,
    activity_report_id: uuid.UUID,
    mission_id: uuid.UUID,
) -> bool:
    """Remove a mission link from an ActivityReport."""
    try:
        arm = db.execute(
            select(ActivityReportMission).where(
                ActivityReportMission.activity_report_id == activity_report_id,
                ActivityReportMission.mission_id == mission_id,
            )
        ).scalar_one_or_none()

        if not arm:
            return False

        db.delete(arm)
        db.commit()
        return True
    except SQLAlchemyError as e:
        db.rollback()
        raise e


def list_missions_for_report(
    db: Session,
    activity_report_id: uuid.UUID,
) -> list[ActivityReportMission]:
    """Return all mission links for an ActivityReport."""
    try:
        results = (
            db.execute(
                select(ActivityReportMission).where(
                    ActivityReportMission.activity_report_id
                    == activity_report_id
                )
            )
            .scalars()
            .all()
        )
        return list(results)
    except SQLAlchemyError as e:
        raise e
