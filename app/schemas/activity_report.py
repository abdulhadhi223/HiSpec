"""Pydantic schemas for Activity Report endpoints."""
import datetime
import uuid
from typing import Self

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator, model_validator

from app.core.enum import (
    Classification,
    HostilityType,
    PlatformCategoryType,
    SignalType,
)

# ─────────────────────────────────────────────────────────────────────────────
# Shared mixin
# ─────────────────────────────────────────────────────────────────────────────


class _TimeWindowMixin(BaseModel):
    start_at: datetime.datetime | None = None
    end_at: datetime.datetime | None = None

    @field_validator("end_at")
    @classmethod
    def validate_time_window(
        cls,
        end_at: datetime.datetime | None,
        info: ValidationInfo,
    ) -> datetime.datetime | None:
        start_at = info.data.get("start_at")
        if start_at and end_at and end_at < start_at:
            raise ValueError("end_at must be greater than or equal to start_at")
        return end_at


# ─────────────────────────────────────────────────────────────────────────────
# ActivityReport
# ─────────────────────────────────────────────────────────────────────────────


class ActivityReportBase(_TimeWindowMixin):
    name: str | None = None  # optional user-provided title
    submitted_by: str
    classification: Classification


class ActivityReportCreate(ActivityReportBase):
    mission_ids: list[uuid.UUID] = []


class ActivityReportUpdate(_TimeWindowMixin):
    name: str | None = None
    classification: Classification | None = None


class ActivityReportResponse(ActivityReportBase):
    id: uuid.UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


# ─────────────────────────────────────────────────────────────────────────────
# ActivityReportInstance
# ─────────────────────────────────────────────────────────────────────────────


class ActivityReportInstanceBase(BaseModel):
    activity_report_id: uuid.UUID
    track_id: uuid.UUID | None = None

    signal_type: SignalType | None = None
    hostility: HostilityType | None = None

    first_seen_dtg: datetime.datetime | None = None
    last_seen_dtg: datetime.datetime | None = None

    last_position_longitude_dd: float | None = None
    last_position_latitude_dd: float | None = None
    # Schema v5: integer >= 0, no upper bound
    last_position_error_m: int | None = None

    platform_category: PlatformCategoryType | None = None
    platform_name: str | None = None
    platform_id: str | None = None
    platform_class: str | None = None

    emitter_id: str | None = None  # matches ORM EWTrackEmitter.emitter_id_sensor String(64)
    emitter_name: str | None = None
    # Schema v5: double [0..1] inclusive
    emitter_confidence: float | None = None
    emitter_country_code: str | None = None
    emitter_country_name: str | None = None

    classification: Classification | None = None
    source_system: str | None = None

    @model_validator(mode="after")
    def validate_time_range(self) -> Self:
        if self.first_seen_dtg and self.last_seen_dtg:
            if self.first_seen_dtg > self.last_seen_dtg:
                raise ValueError("last_seen_dtg must be >= first_seen_dtg")
        return self

    @field_validator("last_position_latitude_dd")
    @classmethod
    def validate_lat(cls, v: float | None) -> float | None:
        if v is not None and not (-90 <= v <= 90):
            raise ValueError("Latitude must be between -90 and 90")
        return v

    @field_validator("last_position_longitude_dd")
    @classmethod
    def validate_lon(cls, v: float | None) -> float | None:
        if v is not None and not (-180 <= v <= 180):
            raise ValueError("Longitude must be between -180 and 180")
        return v

    @field_validator("last_position_error_m")
    @classmethod
    def validate_error_m(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("last_position_error_m must be >= 0")
        return v

    @field_validator("emitter_confidence")
    @classmethod
    def validate_emitter_confidence(cls, v: float | None) -> float | None:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError("emitter_confidence must be between 0.0 and 1.0")
        return v


class ActivityReportInstanceCreate(ActivityReportInstanceBase):
    """Schema for creating an ActivityReportInstance."""


class ActivityReportInstanceResponse(ActivityReportInstanceBase):
    id: uuid.UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


# ─────────────────────────────────────────────────────────────────────────────
# ActivityReportMission
# ─────────────────────────────────────────────────────────────────────────────


class ActivityReportMissionResponse(BaseModel):
    id: uuid.UUID
    activity_report_id: uuid.UUID
    mission_id: uuid.UUID
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


# ─────────────────────────────────────────────────────────────────────────────
# ActivityReport Detail
# ─────────────────────────────────────────────────────────────────────────────


class ActivityReportDetailResponse(ActivityReportResponse):
    instances: list["ActivityReportInstanceResponse"] = []
    report_missions: list["ActivityReportMissionResponse"] = []

    model_config = ConfigDict(from_attributes=True)
