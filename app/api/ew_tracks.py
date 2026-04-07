"""
app/api/ew_tracks.py
FastAPI router for EW Track endpoints.

ACTION REQUIRED in app/main.py — register this router:
    from app.api.ew_tracks import router as ew_tracks_router
    app.include_router(ew_tracks_router)
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db   # adjust if your dep function differs
from app.schemas.ew_track import (
    EmitterCreate, EmitterResponse,
    EWTrackCreate, EWTrackDetailResponse, EWTrackResponse, EWTrackUpdate,
    EWTrackEmitterCreate, EWTrackEmitterResponse,
    EWTrackPointCreate, EWTrackPointResponse,
    EWTrackPointSensorCreate, EWTrackPointSensorResponse,
    MissionCreate, MissionResponse,
    PlatformCreate, PlatformResponse,
    SensorCreate, SensorResponse,
)
from app.services import ew_track_service as svc

router = APIRouter(prefix="/ew", tags=["EW Tracks"])


# ── Sensors ───────────────────────────────────────────────────────────────────

@router.post("/sensors", response_model=SensorResponse, status_code=status.HTTP_201_CREATED)
def create_sensor(data: SensorCreate, db: Session = Depends(get_db)):
    return svc.create_sensor(db, data)

@router.get("/sensors", response_model=list[SensorResponse])
def list_sensors(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
):
    return svc.list_sensors(db, skip, limit)

@router.get("/sensors/{key}", response_model=SensorResponse)
def get_sensor(key: uuid.UUID, db: Session = Depends(get_db)):
    sensor = svc.get_sensor(db, key)
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")
    return sensor


# ── Platforms ─────────────────────────────────────────────────────────────────

@router.post("/platforms", response_model=PlatformResponse, status_code=status.HTTP_201_CREATED)
def create_platform(data: PlatformCreate, db: Session = Depends(get_db)):
    return svc.create_platform(db, data)

@router.get("/platforms", response_model=list[PlatformResponse])
def list_platforms(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
):
    return svc.list_platforms(db, skip, limit)

@router.get("/platforms/{id}", response_model=PlatformResponse)
def get_platform(id: uuid.UUID, db: Session = Depends(get_db)):
    platform = svc.get_platform(db, id)
    if not platform:
        raise HTTPException(status_code=404, detail="Platform not found")
    return platform


# ── Missions ──────────────────────────────────────────────────────────────────

@router.post("/missions", response_model=MissionResponse, status_code=status.HTTP_201_CREATED)
def create_mission(data: MissionCreate, db: Session = Depends(get_db)):
    return svc.create_mission(db, data)

@router.get("/missions", response_model=list[MissionResponse])
def list_missions(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
):
    return svc.list_missions(db, skip, limit)

@router.get("/missions/{id}", response_model=MissionResponse)
def get_mission(id: uuid.UUID, db: Session = Depends(get_db)):
    mission = svc.get_mission(db, id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission


# ── Emitters ──────────────────────────────────────────────────────────────────

@router.post("/emitters", response_model=EmitterResponse, status_code=status.HTTP_201_CREATED)
def create_emitter(data: EmitterCreate, db: Session = Depends(get_db)):
    return svc.create_emitter(db, data)

@router.get("/emitters", response_model=list[EmitterResponse])
def list_emitters(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
):
    return svc.list_emitters(db, skip, limit)

@router.get("/emitters/{key}", response_model=EmitterResponse)
def get_emitter(key: uuid.UUID, db: Session = Depends(get_db)):
    emitter = svc.get_emitter(db, key)
    if not emitter:
        raise HTTPException(status_code=404, detail="Emitter not found")
    return emitter


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
    skip:          int            = Query(0, ge=0),
    limit:         int            = Query(100, le=500),
    source_system: Optional[str]  = Query(None),
    mission_id:    Optional[uuid.UUID] = Query(None),
    platform_id:   Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db),
):
    return svc.list_ew_tracks(db, skip, limit, source_system, mission_id, platform_id)

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
    data.track_id = track_id  # enforce from path
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


# ── Track Emitters ────────────────────────────────────────────────────────────

@router.post("/tracks/{track_id}/emitters", response_model=EWTrackEmitterResponse, status_code=status.HTTP_201_CREATED)
def upsert_emitter(track_id: uuid.UUID, data: EWTrackEmitterCreate, db: Session = Depends(get_db)):
    data.track_id = track_id  # enforce from path
    return svc.upsert_track_emitter(db, data)

@router.get("/tracks/{track_id}/emitters", response_model=list[EWTrackEmitterResponse])
def list_emitters_for_track(track_id: uuid.UUID, db: Session = Depends(get_db)):
    return svc.list_track_emitters(db, track_id)


# ── Track Point Sensors ───────────────────────────────────────────────────────

@router.post("/points/{point_id}/sensors", response_model=EWTrackPointSensorResponse, status_code=status.HTTP_201_CREATED)
def add_point_sensor(point_id: uuid.UUID, data: EWTrackPointSensorCreate, db: Session = Depends(get_db)):
    data.point_id = point_id
    try:
        return svc.add_point_sensor(db, data)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Sensor already linked to this point")
