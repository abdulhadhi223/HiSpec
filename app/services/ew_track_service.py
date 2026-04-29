"""
app/services/ew_track_service.py
Business logic for EW Track feature.
All DB operations live here — routers stay thin.

Reference data CRUD (Sensor, Platform, Mission) lives in:
    app/services/reference_service.py
"""
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.ew_track_models import (
    EWTrack,
    EWTrackEmitter,
    EWTrackPoint,
    EWTrackPointSensor,
)
from app.schemas.ew_track import (
    EWTrackCreate,
    EWTrackEmitterCreate,
    EWTrackPointCreate,
    EWTrackPointSensorCreate,
    EWTrackPointSensorResponse,
    EWTrackUpdate,
)


# ── EWTrack ───────────────────────────────────────────────────────────────────

def create_ew_track(db: Session, data: EWTrackCreate) -> EWTrack:
    track = EWTrack(**data.model_dump())
    db.add(track)
    db.commit()
    db.refresh(track)
    return track

def upsert_ew_track(db: Session, data: EWTrackCreate) -> EWTrack:
    """
    Idempotent upsert on (source_system, source_track_id).
    Returns existing record if already present, otherwise inserts.
    """
    existing = db.execute(
        select(EWTrack).where(
            EWTrack.source_system == data.source_system,
            EWTrack.source_track_id == data.source_track_id,
        )
    ).scalar_one_or_none()

    if existing:
        for field in (
            "hostility", "classification", "mission_id",
            "platform_id", "platform_name", "platform_class",
            "platform_country_code", "platform_country_name", "platform_category",
        ):
            val = getattr(data, field, None)
            if val is not None:
                setattr(existing, field, val)
        db.commit()
        db.refresh(existing)
        return existing

    return create_ew_track(db, data)

def get_ew_track(db: Session, id: uuid.UUID) -> Optional[EWTrack]:
    return db.get(EWTrack, id)

def get_ew_track_detail(db: Session, id: uuid.UUID) -> Optional[EWTrack]:
    """Eagerly load points and emitters for detail view."""
    return db.execute(
        select(EWTrack)
        .where(EWTrack.id == id)
        .options(
            selectinload(EWTrack.track_points),
            selectinload(EWTrack.track_emitters),
        )
    ).scalar_one_or_none()

def list_ew_tracks(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    source_system: Optional[str] = None,
    mission_id: Optional[uuid.UUID] = None,
) -> list[EWTrack]:
    stmt = select(EWTrack)
    if source_system:
        stmt = stmt.where(EWTrack.source_system == source_system)
    if mission_id:
        stmt = stmt.where(EWTrack.mission_id == mission_id)
    return db.execute(stmt.offset(skip).limit(limit)).scalars().all()

def update_ew_track(db: Session, id: uuid.UUID, data: EWTrackUpdate) -> Optional[EWTrack]:
    track = db.get(EWTrack, id)
    if not track:
        return None
    for field, val in data.model_dump(exclude_unset=True).items():
        setattr(track, field, val)
    db.commit()
    db.refresh(track)
    return track

def delete_ew_track(db: Session, id: uuid.UUID) -> bool:
    track = db.get(EWTrack, id)
    if not track:
        return False
    db.delete(track)
    db.commit()
    return True


# ── EWTrackPoint ──────────────────────────────────────────────────────────────

def append_track_point(db: Session, data: EWTrackPointCreate) -> EWTrackPoint:
    """
    Append-only insert. Duplicate (track_id, observed_at, lat, lon) raises
    IntegrityError — let the router handle it as a 409.
    """
    point = EWTrackPoint(**data.model_dump())
    db.add(point)
    db.commit()
    db.refresh(point)
    return point

def list_track_points(
    db: Session,
    track_id: uuid.UUID,
    skip: int = 0,
    limit: int = 500,
) -> list[EWTrackPoint]:
    return db.execute(
        select(EWTrackPoint)
        .where(EWTrackPoint.track_id == track_id)
        .order_by(EWTrackPoint.observed_at)
        .offset(skip)
        .limit(limit)
    ).scalars().all()


# ── EWTrackPointSensor ────────────────────────────────────────────────────────

def add_point_sensor(db: Session, data: EWTrackPointSensorCreate) -> EWTrackPointSensor:
    ps = EWTrackPointSensor(
        point_id=data.point_id,
        sensor_catalog_id=data.sensor_catalog_id,
        role=data.role,
    )
    db.add(ps)
    db.commit()
    db.refresh(ps)
    return ps


# ── EWTrackEmitter ────────────────────────────────────────────────────────────

def upsert_track_emitter(db: Session, data: EWTrackEmitterCreate) -> EWTrackEmitter:
    """Upsert on (track_id, emitter_mode). Updates all fields if record exists."""
    existing = db.execute(
        select(EWTrackEmitter).where(
            EWTrackEmitter.track_id     == data.track_id,
            EWTrackEmitter.emitter_mode == data.emitter_mode,
        )
    ).scalar_one_or_none()

    if existing:
        for field, val in data.model_dump(exclude={"track_id", "emitter_mode"}).items():
            setattr(existing, field, val)
        db.commit()
        db.refresh(existing)
        return existing

    record = EWTrackEmitter(**data.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record

def list_track_emitters(db: Session, track_id: uuid.UUID) -> list[EWTrackEmitter]:
    return db.execute(
        select(EWTrackEmitter).where(EWTrackEmitter.track_id == track_id)
    ).scalars().all()

