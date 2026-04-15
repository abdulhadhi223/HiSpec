"""
app/schemas/common.py

Shared Pydantic schemas for domain entities defined in common_models.py.
Import Mission and Emitter schemas from here — never define them elsewhere.
"""
import uuid
import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.enum import ClassificationType


# ---------------------------------------------------------------------------
# Mission
# ---------------------------------------------------------------------------
class MissionBase(BaseModel):
    name:           str
    start_at:       Optional[datetime.datetime] = None
    end_at:         Optional[datetime.datetime] = None
    classification: ClassificationType

    @field_validator("end_at")
    @classmethod
    def end_after_start(cls, v, info):
        start = info.data.get("start_at")
        if v and start and v < start:
            raise ValueError("end_at must be >= start_at")
        return v

class MissionCreate(MissionBase):
    pass

class MissionUpdate(BaseModel):
    name:           Optional[str]               = None
    start_at:       Optional[datetime.datetime] = None
    end_at:         Optional[datetime.datetime] = None
    classification: Optional[ClassificationType] = None

    @field_validator("end_at")
    @classmethod
    def end_after_start(cls, v, info):
        start = info.data.get("start_at")
        if v and start and v < start:
            raise ValueError("end_at must be >= start_at")
        return v

class MissionResponse(MissionBase):
    id:         uuid.UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Emitter
# ---------------------------------------------------------------------------
class EmitterBase(BaseModel):
    emitter_id_sensor:    Optional[int] = None
    emitter_name:         Optional[str] = None
    emitter_country_code: Optional[str] = Field(None, max_length=3)
    emitter_country_name: Optional[str] = None

class EmitterCreate(EmitterBase):
    pass

class EmitterUpdate(BaseModel):
    emitter_id_sensor:    Optional[int] = None
    emitter_name:         Optional[str] = None
    emitter_country_code: Optional[str] = Field(None, max_length=3)
    emitter_country_name: Optional[str] = None

class EmitterResponse(EmitterBase):
    key:        uuid.UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime
    model_config = {"from_attributes": True}
