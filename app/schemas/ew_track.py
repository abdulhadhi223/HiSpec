"""
app/schemas/ew_track.py
Pydantic request/response schemas for EW Track endpoints.

Mission and Emitter schemas live in app/schemas/common.py.
Import them from there — do NOT redefine them here.
"""
import uuid
import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.core.enum import (
    ClassificationType,
    HostilityType,
    PlatformCategoryType,
    SensorRoleType,
    SignalType,
)

# Re-export so callers can still do a single import from this module if preferred
from app.schemas.common import EmitterCreate, EmitterResponse, MissionCreate, MissionResponse  # noqa: F401


# ---------------------------------------------------------------------------
# Sensor
# ---------------------------------------------------------------------------
class SensorBase(BaseModel):
    name:           str
    type:           str
    classification: ClassificationType

class SensorCreate(SensorBase):
    pass

class SensorUpdate(BaseModel):
    name:           Optional[str]               = None
    type:           Optional[str]               = None
    classification: Optional[ClassificationType] = None

class SensorResponse(SensorBase):
    key:        uuid.UUID           # public UUID identifier
    created_at: datetime.datetime
    updated_at: datetime.datetime
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Platform
# ---------------------------------------------------------------------------
class PlatformBase(BaseModel):
    name:                  Optional[str]                  = None
    category:              Optional[PlatformCategoryType] = None
    platform_country_code: Optional[str]                  = Field(None, max_length=3)
    platform_country_name: Optional[str]                  = None
    classification:        ClassificationType

class PlatformCreate(PlatformBase):
    pass

class PlatformUpdate(BaseModel):
    name:                  Optional[str]                  = None
    category:              Optional[PlatformCategoryType] = None
    platform_country_code: Optional[str]                  = Field(None, max_length=3)
    platform_country_name: Optional[str]                  = None
    classification:        Optional[ClassificationType]   = None

class PlatformResponse(PlatformBase):
    id:         int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# EWTrack
# ---------------------------------------------------------------------------
class EWTrackBase(BaseModel):
    source_system:   str
    source_track_id: Optional[str] = None
    hostility:       HostilityType
    classification:  ClassificationType
    platform_id:     Optional[int] = None        # Integer FK → tech_platform_instance.id
    mission_id:      Optional[uuid.UUID] = None

class EWTrackCreate(EWTrackBase):
    pass

class EWTrackUpdate(BaseModel):
    """Partial update — all fields optional."""
    hostility:      Optional[HostilityType]      = None
    classification: Optional[ClassificationType] = None
    platform_id:    Optional[int]                = None  # Integer FK → tech_platform_instance.id
    mission_id:     Optional[uuid.UUID]          = None

class EWTrackResponse(EWTrackBase):
    id:         uuid.UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime
    model_config = {"from_attributes": True}

class EWTrackDetailResponse(EWTrackResponse):
    """Full track with nested points and emitters."""
    track_points:   list["EWTrackPointResponse"]   = []
    track_emitters: list["EWTrackEmitterResponse"] = []


# ---------------------------------------------------------------------------
# EWTrackPoint
# ---------------------------------------------------------------------------
class EWTrackPointBase(BaseModel):
    observed_at:    datetime.datetime
    lat:            float = Field(..., ge=-90,  le=90)
    lon:            float = Field(..., ge=-180, le=180)
    error_m:        Optional[float] = Field(None, ge=0)
    classification: ClassificationType

class EWTrackPointCreate(EWTrackPointBase):
    track_id: uuid.UUID

class EWTrackPointResponse(EWTrackPointBase):
    id:       uuid.UUID
    track_id: uuid.UUID
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# EWTrackPointSensor
# ---------------------------------------------------------------------------
class EWTrackPointSensorCreate(BaseModel):
    point_id:  uuid.UUID
    sensor_id: int                          # Integer FK → tech_sensor.id
    role:      Optional[SensorRoleType] = None

class EWTrackPointSensorResponse(EWTrackPointSensorCreate):
    id: uuid.UUID
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# EWTrackEmitter
# ---------------------------------------------------------------------------
class EWTrackEmitterBase(BaseModel):
    first_seen_at:      datetime.datetime
    last_seen_at:       datetime.datetime
    emitter_confidence: Optional[float] = Field(None, ge=0, le=1)
    signal_type:        SignalType
    emitter_mode:       str

    # Frequency (MHz)
    freq_low_mhz:    Optional[float] = None
    freq_high_mhz:   Optional[float] = None
    freq_center_mhz: Optional[float] = None

    # Pulse Width (µs)
    pulse_width_low_us:    Optional[float] = None
    pulse_width_high_us:   Optional[float] = None
    pulse_width_center_us: Optional[float] = None

    # PRI (µs)
    pri_low_us:    Optional[float] = None
    pri_high_us:   Optional[float] = None
    pri_center_us: Optional[float] = None

class EWTrackEmitterCreate(EWTrackEmitterBase):
    track_id:    uuid.UUID
    emitter_key: uuid.UUID

class EWTrackEmitterResponse(EWTrackEmitterBase):
    id:          uuid.UUID
    track_id:    uuid.UUID
    emitter_key: uuid.UUID
    created_at:  datetime.datetime
    updated_at:  datetime.datetime
    model_config = {"from_attributes": True}


# ── Forward-reference resolution ─────────────────────────────────────────────
EWTrackDetailResponse.model_rebuild()
