"""
app/schemas/activity_report.py
Pydantic request/response schemas for Activity Report endpoints.
"""
import uuid
import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator

from app.core.enum import (
    Classification,
    HostilityType,
    PlatformCategoryType,
    SignalType,
)


# ---------------------------------------------------------------------------
# ActivityReport
# ---------------------------------------------------------------------------
class ActivityReportBase(BaseModel):
    name:           Optional[str] = None
    submitted_by:   str
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

class ActivityReportCreate(ActivityReportBase):
    mission_ids: list[uuid.UUID] = []   # link missions at creation time

class ActivityReportUpdate(BaseModel):
    name:           Optional[str]               = None
    start_at:       Optional[datetime.datetime] = None
    end_at:         Optional[datetime.datetime] = None
    classification: Optional[Classification] = None

class ActivityReportResponse(ActivityReportBase):
    id:         uuid.UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime
    model_config = {"from_attributes": True}

class ActivityReportDetailResponse(ActivityReportResponse):
    """Full report with nested instances and linked missions."""
    instances:       list["ActivityReportInstanceResponse"] = []
    report_missions: list["ActivityReportMissionResponse"]  = []


# ---------------------------------------------------------------------------
# ActivityReportInstance
# ---------------------------------------------------------------------------
class ActivityReportInstanceBase(BaseModel):
    # Emitter identity (snapshot)
    emitter_id:           Optional[int]   = None
    emitter_name:         Optional[str]   = None
    emitter_confidence:   Optional[float] = Field(None, ge=0, le=1)
    emitter_country_code: Optional[str]   = Field(None, max_length=3)
    emitter_country_name: Optional[str]   = None

    # Tactical
    signal_type: SignalType
    hostility:   HostilityType

    # Time window
    first_seen_dtg: datetime.datetime
    last_seen_dtg:  datetime.datetime

    # Last known position
    last_position_longitude_dd: float = Field(..., ge=-180, le=180)
    last_position_latitude_dd:  float = Field(..., ge=-90,  le=90)
    last_position_error_m:      Optional[int] = Field(None, ge=0)

    # Platform (snapshot)
    platform_category: Optional[PlatformCategoryType] = None
    platform_name:     Optional[str] = None
    platform_id:       Optional[str] = None
    platform_class:    Optional[str] = None

    # Metadata
    classification: Classification
    source_system:  str

    @field_validator("last_seen_dtg")
    @classmethod
    def last_after_first(cls, v, info):
        first = info.data.get("first_seen_dtg")
        if first and v < first:
            raise ValueError("last_seen_dtg must be >= first_seen_dtg")
        return v

class ActivityReportInstanceCreate(ActivityReportInstanceBase):
    activity_report_id: uuid.UUID
    track_id:           Optional[uuid.UUID] = None   # optional link to live EWTrack

class ActivityReportInstanceResponse(ActivityReportInstanceBase):
    id:                 uuid.UUID
    activity_report_id: uuid.UUID
    track_id:           Optional[uuid.UUID] = None
    created_at:         datetime.datetime
    updated_at:         datetime.datetime
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# ActivityReportMission  (lightweight — used inside detail responses)
# ---------------------------------------------------------------------------
class ActivityReportMissionResponse(BaseModel):
    id:                 uuid.UUID
    activity_report_id: uuid.UUID
    mission_id:         uuid.UUID
    created_at:         datetime.datetime
    model_config = {"from_attributes": True}


# ── Forward-reference resolution ─────────────────────────────────────────────
ActivityReportDetailResponse.model_rebuild()
