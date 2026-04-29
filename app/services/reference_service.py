"""
app/services/reference_service.py
Business logic for Mission reference data.
"""
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.common_models import Mission
from app.schemas.common import MissionCreate, MissionUpdate


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
