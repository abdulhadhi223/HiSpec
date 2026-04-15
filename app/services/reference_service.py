"""
app/services/reference_service.py
Business logic for all reference data entities:
  TechSensor, TechPlatformInstance, Mission, Emitter
"""
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.common_models import Emitter, Mission
from app.models.orm_models import TechPlatformInstance as Platform, TechSensor as Sensor
from app.schemas.common import (
    EmitterCreate, EmitterUpdate,
    MissionCreate, MissionUpdate,
)
from app.schemas.ew_track import (
    PlatformCreate, PlatformUpdate,
    SensorCreate, SensorUpdate,
)


# ── Sensor ────────────────────────────────────────────────────────────────────

def create_sensor(db: Session, data: SensorCreate) -> Sensor:
    sensor = Sensor(**data.model_dump())
    db.add(sensor)
    db.commit()
    db.refresh(sensor)
    return sensor

def get_sensor(db: Session, key: uuid.UUID) -> Optional[Sensor]:
    # key is a unique UUID column, not the Integer PK — use WHERE
    return db.execute(
        select(Sensor).where(Sensor.key == key)
    ).scalar_one_or_none()

def list_sensors(db: Session, skip: int = 0, limit: int = 100) -> list[Sensor]:
    return db.execute(select(Sensor).offset(skip).limit(limit)).scalars().all()

def update_sensor(db: Session, key: uuid.UUID, data: SensorUpdate) -> Optional[Sensor]:
    sensor = get_sensor(db, key)
    if not sensor:
        return None
    for field, val in data.model_dump(exclude_unset=True).items():
        setattr(sensor, field, val)
    db.commit()
    db.refresh(sensor)
    return sensor


# ── Platform ──────────────────────────────────────────────────────────────────

def create_platform(db: Session, data: PlatformCreate) -> Platform:
    platform = Platform(**data.model_dump())
    db.add(platform)
    db.commit()
    db.refresh(platform)
    return platform

def get_platform(db: Session, id: int) -> Optional[Platform]:
    return db.get(Platform, id)

def list_platforms(db: Session, skip: int = 0, limit: int = 100) -> list[Platform]:
    return db.execute(select(Platform).offset(skip).limit(limit)).scalars().all()

def update_platform(db: Session, id: int, data: PlatformUpdate) -> Optional[Platform]:
    platform = db.get(Platform, id)
    if not platform:
        return None
    for field, val in data.model_dump(exclude_unset=True).items():
        setattr(platform, field, val)
    db.commit()
    db.refresh(platform)
    return platform


# ── Mission ───────────────────────────────────────────────────────────────────

def create_mission(db: Session, data: MissionCreate) -> Mission:
    mission = Mission(**data.model_dump())
    db.add(mission)
    db.commit()
    db.refresh(mission)
    return mission

def get_mission(db: Session, id: uuid.UUID) -> Optional[Mission]:
    return db.get(Mission, id)

def list_missions(db: Session, skip: int = 0, limit: int = 100) -> list[Mission]:
    return db.execute(select(Mission).offset(skip).limit(limit)).scalars().all()

def update_mission(db: Session, id: uuid.UUID, data: MissionUpdate) -> Optional[Mission]:
    mission = db.get(Mission, id)
    if not mission:
        return None
    for field, val in data.model_dump(exclude_unset=True).items():
        setattr(mission, field, val)
    db.commit()
    db.refresh(mission)
    return mission


# ── Emitter ───────────────────────────────────────────────────────────────────

def create_emitter(db: Session, data: EmitterCreate) -> Emitter:
    emitter = Emitter(**data.model_dump())
    db.add(emitter)
    db.commit()
    db.refresh(emitter)
    return emitter

def get_emitter(db: Session, key: uuid.UUID) -> Optional[Emitter]:
    return db.get(Emitter, key)  # key is the PK on Emitter

def list_emitters(db: Session, skip: int = 0, limit: int = 100) -> list[Emitter]:
    return db.execute(select(Emitter).offset(skip).limit(limit)).scalars().all()

def update_emitter(db: Session, key: uuid.UUID, data: EmitterUpdate) -> Optional[Emitter]:
    emitter = db.get(Emitter, key)
    if not emitter:
        return None
    for field, val in data.model_dump(exclude_unset=True).items():
        setattr(emitter, field, val)
    db.commit()
    db.refresh(emitter)
    return emitter
