"""
app/api/activity_reports.py
FastAPI router for Activity Report endpoints.

ACTION REQUIRED in app/main.py — register this router:
    from app.api.activity_reports import router as activity_reports_router
    app.include_router(activity_reports_router)
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db   # adjust if your dep function differs
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

router = APIRouter(prefix="/activity-reports", tags=["Activity Reports"])


# ── Activity Reports ──────────────────────────────────────────────────────────

@router.post("", response_model=ActivityReportResponse, status_code=status.HTTP_201_CREATED)
def create_report(data: ActivityReportCreate, db: Session = Depends(get_db)):
    return svc.create_activity_report(db, data)

@router.get("", response_model=list[ActivityReportResponse])
def list_reports(
    skip:         int           = Query(0, ge=0),
    limit:        int           = Query(100, le=500),
    submitted_by: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    return svc.list_activity_reports(db, skip, limit, submitted_by)

@router.get("/{id}", response_model=ActivityReportDetailResponse)
def get_report(id: uuid.UUID, db: Session = Depends(get_db)):
    report = svc.get_activity_report_detail(db, id)
    if not report:
        raise HTTPException(status_code=404, detail="Activity report not found")
    return report

@router.patch("/{id}", response_model=ActivityReportResponse)
def update_report(id: uuid.UUID, data: ActivityReportUpdate, db: Session = Depends(get_db)):
    report = svc.update_activity_report(db, id, data)
    if not report:
        raise HTTPException(status_code=404, detail="Activity report not found")
    return report

@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(id: uuid.UUID, db: Session = Depends(get_db)):
    if not svc.delete_activity_report(db, id):
        raise HTTPException(status_code=404, detail="Activity report not found")


# ── Instances ─────────────────────────────────────────────────────────────────

@router.post("/{report_id}/instances", response_model=ActivityReportInstanceResponse, status_code=status.HTTP_201_CREATED)
def add_instance(
    report_id: uuid.UUID,
    data: ActivityReportInstanceCreate,
    db: Session = Depends(get_db),
):
    data.activity_report_id = report_id  # enforce from path
    try:
        return svc.add_instance(db, data)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Instance already exists for this report + track combination",
        )

@router.get("/{report_id}/instances", response_model=list[ActivityReportInstanceResponse])
def list_instances(report_id: uuid.UUID, db: Session = Depends(get_db)):
    return svc.list_instances(db, report_id)

@router.get("/{report_id}/instances/{instance_id}", response_model=ActivityReportInstanceResponse)
def get_instance(report_id: uuid.UUID, instance_id: uuid.UUID, db: Session = Depends(get_db)):
    instance = svc.get_instance(db, instance_id)
    if not instance or instance.activity_report_id != report_id:
        raise HTTPException(status_code=404, detail="Instance not found")
    return instance

@router.delete("/{report_id}/instances/{instance_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_instance(report_id: uuid.UUID, instance_id: uuid.UUID, db: Session = Depends(get_db)):
    instance = svc.get_instance(db, instance_id)
    if not instance or instance.activity_report_id != report_id:
        raise HTTPException(status_code=404, detail="Instance not found")
    svc.delete_instance(db, instance_id)


# ── Mission links ─────────────────────────────────────────────────────────────

@router.post("/{report_id}/missions/{mission_id}", response_model=ActivityReportMissionResponse, status_code=status.HTTP_201_CREATED)
def link_mission(report_id: uuid.UUID, mission_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        return svc.link_mission(db, report_id, mission_id)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Mission already linked to this report")

@router.delete("/{report_id}/missions/{mission_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_mission(report_id: uuid.UUID, mission_id: uuid.UUID, db: Session = Depends(get_db)):
    if not svc.unlink_mission(db, report_id, mission_id):
        raise HTTPException(status_code=404, detail="Link not found")

@router.get("/{report_id}/missions", response_model=list[ActivityReportMissionResponse])
def list_missions(report_id: uuid.UUID, db: Session = Depends(get_db)):
    return svc.list_missions_for_report(db, report_id)
