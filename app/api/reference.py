"""
app/api/reference.py
Reference data endpoints — Sensors / Platforms / Missions / Emitters.

ACTION REQUIRED in app/main.py — register this router:
    from app.api.reference import router as reference_router
    app.include_router(reference_router)
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.common import (
    EmitterCreate, EmitterResponse, EmitterUpdate,
    MissionCreate, MissionResponse, MissionUpdate,
)
from app.schemas.ew_track import (
    PlatformCreate, PlatformResponse, PlatformUpdate,
    SensorCreate, SensorResponse, SensorUpdate,
)
from app.services import reference_service as svc

router = APIRouter(tags=["Reference Data"])


# ── Sensors ───────────────────────────────────────────────────────────────────

@router.post("/sensors", response_model=SensorResponse, status_code=status.HTTP_201_CREATED)
def create_sensor(data: SensorCreate, db: Session = Depends(get_db)):
    return svc.create_sensor(db, data)

@router.get("/sensors", response_model=list[SensorResponse])
def list_sensors(
    skip:  int = Query(0, ge=0),
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

@router.patch("/sensors/{key}", response_model=SensorResponse)
def update_sensor(key: uuid.UUID, data: SensorUpdate, db: Session = Depends(get_db)):
    sensor = svc.update_sensor(db, key, data)
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")
    return sensor


# ── Platforms ─────────────────────────────────────────────────────────────────

@router.post("/platforms", response_model=PlatformResponse, status_code=status.HTTP_201_CREATED)
def create_platform(data: PlatformCreate, db: Session = Depends(get_db)):
    return svc.create_platform(db, data)

@router.get("/platforms", response_model=list[PlatformResponse])
def list_platforms(
    skip:  int = Query(0, ge=0),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
):
    return svc.list_platforms(db, skip, limit)

@router.get("/platforms/{id}", response_model=PlatformResponse)
def get_platform(id: int, db: Session = Depends(get_db)):
    platform = svc.get_platform(db, id)
    if not platform:
        raise HTTPException(status_code=404, detail="Platform not found")
    return platform

@router.patch("/platforms/{id}", response_model=PlatformResponse)
def update_platform(id: int, data: PlatformUpdate, db: Session = Depends(get_db)):
    platform = svc.update_platform(db, id, data)
    if not platform:
        raise HTTPException(status_code=404, detail="Platform not found")
    return platform


# ── Missions ──────────────────────────────────────────────────────────────────

@router.post("/missions", response_model=MissionResponse, status_code=status.HTTP_201_CREATED)
def create_mission(data: MissionCreate, db: Session = Depends(get_db)):
    return svc.create_mission(db, data)

@router.get("/missions", response_model=list[MissionResponse])
def list_missions(
    skip:  int = Query(0, ge=0),
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

@router.patch("/missions/{id}", response_model=MissionResponse)
def update_mission(id: uuid.UUID, data: MissionUpdate, db: Session = Depends(get_db)):
    mission = svc.update_mission(db, id, data)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission


# ── Emitters ──────────────────────────────────────────────────────────────────

@router.post("/emitters", response_model=EmitterResponse, status_code=status.HTTP_201_CREATED)
def create_emitter(data: EmitterCreate, db: Session = Depends(get_db)):
    return svc.create_emitter(db, data)

@router.get("/emitters", response_model=list[EmitterResponse])
def list_emitters(
    skip:  int = Query(0, ge=0),
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

@router.patch("/emitters/{key}", response_model=EmitterResponse)
def update_emitter(key: uuid.UUID, data: EmitterUpdate, db: Session = Depends(get_db)):
    emitter = svc.update_emitter(db, key, data)
    if not emitter:
        raise HTTPException(status_code=404, detail="Emitter not found")
    return emitter
