"""
app/services/activity_report_service.py
Business logic for Activity Report feature.
"""
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.ew_track_models import (
    ActivityReport,
    ActivityReportInstance,
    ActivityReportMission,
)
from app.schemas.activity_report import (
    ActivityReportCreate,
    ActivityReportInstanceCreate,
    ActivityReportUpdate,
)


# ── ActivityReport ────────────────────────────────────────────────────────────

def create_activity_report(db: Session, data: ActivityReportCreate) -> ActivityReport:
    """
    Creates a report and immediately links any supplied mission_ids.
    """
    payload = data.model_dump(exclude={"mission_ids"})
    report = ActivityReport(**payload)
    db.add(report)
    db.flush()  # get report.id before inserting junctions

    for mission_id in (data.mission_ids or []):
        db.add(ActivityReportMission(
            activity_report_id=report.id,
            mission_id=mission_id,
        ))

    db.commit()
    db.refresh(report)
    return report

def get_activity_report(db: Session, id: uuid.UUID) -> Optional[ActivityReport]:
    return db.get(ActivityReport, id)

def get_activity_report_detail(db: Session, id: uuid.UUID) -> Optional[ActivityReport]:
    """Eagerly load instances and linked missions."""
    return db.execute(
        select(ActivityReport)
        .where(ActivityReport.id == id)
        .options(
            selectinload(ActivityReport.instances),
            selectinload(ActivityReport.report_missions),
        )
    ).scalar_one_or_none()

def list_activity_reports(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    submitted_by: Optional[str] = None,
) -> list[ActivityReport]:
    stmt = select(ActivityReport)
    if submitted_by:
        stmt = stmt.where(ActivityReport.submitted_by == submitted_by)
    return db.execute(stmt.offset(skip).limit(limit)).scalars().all()

def update_activity_report(
    db: Session, id: uuid.UUID, data: ActivityReportUpdate
) -> Optional[ActivityReport]:
    report = db.get(ActivityReport, id)
    if not report:
        return None
    for field, val in data.model_dump(exclude_unset=True).items():
        setattr(report, field, val)
    db.commit()
    db.refresh(report)
    return report

def delete_activity_report(db: Session, id: uuid.UUID) -> bool:
    report = db.get(ActivityReport, id)
    if not report:
        return False
    db.delete(report)
    db.commit()
    return True


# ── ActivityReportInstance ────────────────────────────────────────────────────

def add_instance(
    db: Session, data: ActivityReportInstanceCreate
) -> ActivityReportInstance:
    """
    Add one EW Track entry to a report.
    Duplicate (activity_report_id, track_id) raises IntegrityError → 409.
    """
    instance = ActivityReportInstance(**data.model_dump())
    db.add(instance)
    db.commit()
    db.refresh(instance)
    return instance

def get_instance(db: Session, id: uuid.UUID) -> Optional[ActivityReportInstance]:
    return db.get(ActivityReportInstance, id)

def list_instances(
    db: Session, activity_report_id: uuid.UUID
) -> list[ActivityReportInstance]:
    return db.execute(
        select(ActivityReportInstance)
        .where(ActivityReportInstance.activity_report_id == activity_report_id)
        .order_by(ActivityReportInstance.first_seen_dtg)
    ).scalars().all()

def delete_instance(db: Session, id: uuid.UUID) -> bool:
    instance = db.get(ActivityReportInstance, id)
    if not instance:
        return False
    db.delete(instance)
    db.commit()
    return True


# ── ActivityReportMission ─────────────────────────────────────────────────────

def link_mission(
    db: Session, activity_report_id: uuid.UUID, mission_id: uuid.UUID
) -> ActivityReportMission:
    """Link a mission to a report. Duplicate raises IntegrityError → 409."""
    arm = ActivityReportMission(
        activity_report_id=activity_report_id,
        mission_id=mission_id,
    )
    db.add(arm)
    db.commit()
    db.refresh(arm)
    return arm

def unlink_mission(
    db: Session, activity_report_id: uuid.UUID, mission_id: uuid.UUID
) -> bool:
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

def list_missions_for_report(
    db: Session, activity_report_id: uuid.UUID
) -> list[ActivityReportMission]:
    return db.execute(
        select(ActivityReportMission)
        .where(ActivityReportMission.activity_report_id == activity_report_id)
    ).scalars().all()
