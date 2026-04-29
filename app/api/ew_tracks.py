"""
app/api/ew_tracks.py
FastAPI router for EW Track endpoints.

ACTION REQUIRED in app/main.py — register this router:
    from app.api.ew_tracks import router as ew_tracks_router
    app.include_router(ew_tracks_router)

Reference data (sensors / platforms / missions) lives in:
    app/api/reference.py
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.ew_track import (
    EWTrackCreate, EWTrackDetailResponse, EWTrackResponse, EWTrackUpdate,
    EWTrackEmitterCreate, EWTrackEmitterResponse,
    EWTrackPointCreate, EWTrackPointResponse,
    EWTrackPointSensorCreate, EWTrackPointSensorResponse,
)
from app.services import ew_track_service as svc

router = APIRouter(prefix="/ew", tags=["EW Tracks"])


# ── EW Tracks ─────────────────────────────────────────────────────────────────

@router.post("/tracks", response_model=EWTrackResponse, status_code=status.HTTP_201_CREATED)
def create_track(data: EWTrackCreate, db: Session = Depends(get_db)):
    try:
        return svc.create_ew_track(db, data)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Track already exists (duplicate source_system + source_track_id)")

@router.post("/tracks/upsert", response_model=EWTrackResponse)
def upsert_track(data: EWTrackCreate, db: Session = Depends(get_db)):
    """Idempotent — inserts or updates based on (source_system, source_track_id)."""
    return svc.upsert_ew_track(db, data)

@router.get("/tracks", response_model=list[EWTrackResponse])
def list_tracks(
    skip:          int                 = Query(0, ge=0),
    limit:         int                 = Query(100, le=500),
    source_system: Optional[str]       = Query(None),
    mission_id:    Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db),
):
    return svc.list_ew_tracks(db, skip, limit, source_system, mission_id)

@router.get("/tracks/{id}", response_model=EWTrackDetailResponse)
def get_track(id: uuid.UUID, db: Session = Depends(get_db)):
    track = svc.get_ew_track_detail(db, id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")
    return track

@router.patch("/tracks/{id}", response_model=EWTrackResponse)
def update_track(id: uuid.UUID, data: EWTrackUpdate, db: Session = Depends(get_db)):
    track = svc.update_ew_track(db, id, data)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")
    return track

@router.delete("/tracks/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_track(id: uuid.UUID, db: Session = Depends(get_db)):
    if not svc.delete_ew_track(db, id):
        raise HTTPException(status_code=404, detail="Track not found")


# ── Track Points ──────────────────────────────────────────────────────────────

@router.post("/tracks/{track_id}/points", response_model=EWTrackPointResponse, status_code=status.HTTP_201_CREATED)
def append_point(track_id: uuid.UUID, data: EWTrackPointCreate, db: Session = Depends(get_db)):
    data.track_id = track_id
    try:
        return svc.append_track_point(db, data)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Duplicate point (track_id, observed_at, lat, lon)")

@router.get("/tracks/{track_id}/points", response_model=list[EWTrackPointResponse])
def list_points(
    track_id: uuid.UUID,
    skip:  int = Query(0, ge=0),
    limit: int = Query(500, le=2000),
    db: Session = Depends(get_db),
):
    return svc.list_track_points(db, track_id, skip, limit)


# ── Track Point Sensors ───────────────────────────────────────────────────────

@router.post("/points/{point_id}/sensors", response_model=EWTrackPointSensorResponse, status_code=status.HTTP_201_CREATED)
def add_point_sensor(point_id: uuid.UUID, data: EWTrackPointSensorCreate, db: Session = Depends(get_db)):
    data.point_id = point_id
    try:
        return svc.add_point_sensor(db, data)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Sensor already linked to this point")


# ── Track Emitters ────────────────────────────────────────────────────────────

@router.post("/tracks/{track_id}/emitters", response_model=EWTrackEmitterResponse, status_code=status.HTTP_201_CREATED)
def upsert_emitter(track_id: uuid.UUID, data: EWTrackEmitterCreate, db: Session = Depends(get_db)):
    data.track_id = track_id
    try:
        return svc.upsert_track_emitter(db, data)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflict upserting track emitter")

@router.get("/tracks/{track_id}/emitters", response_model=list[EWTrackEmitterResponse])
def list_emitters_for_track(track_id: uuid.UUID, db: Session = Depends(get_db)):
    return svc.list_track_emitters(db, track_id)
