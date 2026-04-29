"""
app/schemas/common.py

Shared Pydantic schemas for domain entities defined in common_models.py.
Import Mission schemas from here — never define them elsewhere.
"""
import uuid
import datetime
from typing import Optional
from pydantic import BaseModel, field_validator

from app.core.enum import Classification


# ---------------------------------------------------------------------------
# Mission
# ---------------------------------------------------------------------------
class MissionBase(BaseModel):
    name:           str
    start_at:       Optional[datetime.datetime] = None
    end_at:         Optional[datetime.datetime] = None
    classification: Classification

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
    classification: Optional[Classification] = None

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
