"""
app/models/ew_track_models.py

EW Track & Activity Report ORM models — schema v5.0.

Mission and Emitter have been moved to app/models/common_models.py.
This file imports them from there — do NOT redefine them here.

External entity references (no ORM class defined here):
  - TechPlatformInstance → tech_platform_instance.id (Integer, orm_models.py)
  - TechSensor           → tech_sensor.id            (Integer, orm_models.py)

ACTION REQUIRED in app/models/__init__.py — ensure all three model files
are imported so SQLAlchemy registers every table with Base.metadata:

    from app.models import orm_models       # existing
    from app.models import common_models    # new
    from app.models import ew_track_models  # new
"""

import uuid
import datetime

from sqlalchemy import (
    CheckConstraint,
    Double,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    TIMESTAMP,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enum import (
    ClassificationType,
    HostilityType,
    PlatformCategoryType,
    SensorRoleType,
    SignalType,
)

# ── Import shared entities from common_models ─────────────────────────────────
# Re-export them so callers can do:
#   from app.models.ew_track_models import Mission, Emitter
# if they prefer a single import point.
from app.models.common_models import Emitter, Mission  # noqa: F401

# ---------------------------------------------------------------------------
# SA Enum column types  (create_type=False — migration owns PG type lifecycle)
# ---------------------------------------------------------------------------
TZ    = TIMESTAMP(timezone=True)
_cls  = SAEnum(ClassificationType,   name="classification_type",    create_type=False)
_sig  = SAEnum(SignalType,           name="signal_type",            create_type=False)
_hos  = SAEnum(HostilityType,        name="hostility_type",         create_type=False)
_pcat = SAEnum(PlatformCategoryType, name="platform_category_type", create_type=False)
_role = SAEnum(SensorRoleType,       name="sensor_role_type",       create_type=False)


# ---------------------------------------------------------------------------
# EWTrack
# ---------------------------------------------------------------------------
class EWTrack(Base):
    """
    Master track record per emitter observation.
    UNIQUE (source_system, source_track_id) → idempotent ingestion.

    platform_id → tech_platform_instance.id  (Integer FK, existing table)
    mission_id  → mission.id                 (UUID FK, common_models.py)
    """
    __tablename__ = "ew_track"
    __table_args__ = (
        UniqueConstraint(
            "source_system", "source_track_id", name="ew_track_idempotency"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    source_system:   Mapped[str]                = mapped_column(String(64),  nullable=False)
    source_track_id: Mapped[str | None]         = mapped_column(String(128), nullable=True)
    hostility:       Mapped[HostilityType]      = mapped_column(_hos, nullable=False)
    classification:  Mapped[ClassificationType] = mapped_column(_cls, nullable=False)

    # Integer FK → existing tech_platform_instance table (orm_models.py)
    platform_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("tech_platform_instance.id", ondelete="SET NULL"),
        nullable=True,
    )
    # UUID FK → mission (common_models.py)
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mission.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = mapped_column(TZ, nullable=False, server_default=text("now()"))
    updated_at = mapped_column(TZ, nullable=False, server_default=text("now()"))

    # Relationships
    platform: Mapped["TechPlatformInstance | None"] = relationship(
        "TechPlatformInstance", foreign_keys=[platform_id]
    )
    mission: Mapped["Mission | None"] = relationship(
        "Mission", back_populates="ew_tracks"
    )
    track_points: Mapped[list["EWTrackPoint"]] = relationship(
        back_populates="track", cascade="all, delete-orphan"
    )
    track_emitters: Mapped[list["EWTrackEmitter"]] = relationship(
        back_populates="track", cascade="all, delete-orphan"
    )
    activity_report_instances: Mapped[list["ActivityReportInstance"]] = relationship(
        back_populates="track"
    )


# ---------------------------------------------------------------------------
# EWTrackPoint  (append-only)
# ---------------------------------------------------------------------------
class EWTrackPoint(Base):
    """
    Append-only position samples. NEVER update or delete except by admin.

    DB indexes (managed by migration):
      BTREE (track_id, observed_at)  — time-ordered fetch
      GIST  ll_to_earth(lat, lon)    — AOI spatial queries
    """
    __tablename__ = "ew_track_point"
    __table_args__ = (
        CheckConstraint("lat BETWEEN -90 AND 90",          name="ew_track_point_lat_range"),
        CheckConstraint("lon BETWEEN -180 AND 180",         name="ew_track_point_lon_range"),
        CheckConstraint("error_m IS NULL OR error_m >= 0", name="ew_track_point_error_positive"),
        UniqueConstraint(
            "track_id", "observed_at", "lat", "lon",
            name="ew_track_point_unique",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    track_id:       Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("ew_track.id"), nullable=False)
    observed_at:    Mapped[datetime.datetime]  = mapped_column(TZ,     nullable=False)
    lat:            Mapped[float]              = mapped_column(Double, nullable=False)
    lon:            Mapped[float]              = mapped_column(Double, nullable=False)
    error_m:        Mapped[float | None]       = mapped_column(Double, nullable=True)
    classification: Mapped[ClassificationType] = mapped_column(_cls,   nullable=False)

    track:         Mapped["EWTrack"]                  = relationship(back_populates="track_points")
    point_sensors: Mapped[list["EWTrackPointSensor"]] = relationship(
        back_populates="point", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# EWTrackPointSensor
# ---------------------------------------------------------------------------
class EWTrackPointSensor(Base):
    """
    Junction: which sensor produced which track point.
    sensor_id → tech_sensor.id  (Integer FK, existing table in orm_models.py)
    UNIQUE (point_id, sensor_id)
    """
    __tablename__ = "ew_track_point_sensor"
    __table_args__ = (
        UniqueConstraint("point_id", "sensor_id", name="ew_track_point_sensor_unique"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    point_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ew_track_point.id"), nullable=False
    )
    # Integer FK → existing tech_sensor table (orm_models.py)
    sensor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tech_sensor.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[SensorRoleType | None] = mapped_column(_role, nullable=True)

    point:  Mapped["EWTrackPoint"] = relationship(back_populates="point_sensors")
    sensor: Mapped["TechSensor"]   = relationship("TechSensor", foreign_keys=[sensor_id])


# ---------------------------------------------------------------------------
# EWTrackEmitter
# ---------------------------------------------------------------------------
class EWTrackEmitter(Base):
    """
    Emitter identity + full RF fingerprint per track per emitter mode.
    One row per unique (track_id, emitter_key, emitter_mode).

    emitter_key → emitter.key  (UUID FK, common_models.py)
    """
    __tablename__ = "ew_track_emitter"
    __table_args__ = (
        CheckConstraint(
            "emitter_confidence IS NULL OR emitter_confidence BETWEEN 0 AND 1",
            name="ew_track_emitter_confidence_range",
        ),
        UniqueConstraint(
            "track_id", "emitter_key", "emitter_mode",
            name="ew_track_emitter_unique",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    track_id:    Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ew_track.id"),  nullable=False)
    emitter_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("emitter.key"), nullable=False)

    first_seen_at:      Mapped[datetime.datetime] = mapped_column(TZ,           nullable=False)
    last_seen_at:       Mapped[datetime.datetime] = mapped_column(TZ,           nullable=False)
    emitter_confidence: Mapped[float | None]      = mapped_column(Double,       nullable=True)
    signal_type:        Mapped[SignalType]         = mapped_column(_sig,         nullable=False)
    emitter_mode:       Mapped[str]               = mapped_column(String(128),  nullable=False)

    # Frequency (MHz)
    freq_low_mhz:    Mapped[float | None] = mapped_column(Double, nullable=True)
    freq_high_mhz:   Mapped[float | None] = mapped_column(Double, nullable=True)
    freq_center_mhz: Mapped[float | None] = mapped_column(Double, nullable=True)

    # Pulse Width (µs)
    pulse_width_low_us:    Mapped[float | None] = mapped_column(Double, nullable=True)
    pulse_width_high_us:   Mapped[float | None] = mapped_column(Double, nullable=True)
    pulse_width_center_us: Mapped[float | None] = mapped_column(Double, nullable=True)

    # PRI (µs)
    pri_low_us:    Mapped[float | None] = mapped_column(Double, nullable=True)
    pri_high_us:   Mapped[float | None] = mapped_column(Double, nullable=True)
    pri_center_us: Mapped[float | None] = mapped_column(Double, nullable=True)

    created_at = mapped_column(TZ, nullable=False, server_default=text("now()"))
    updated_at = mapped_column(TZ, nullable=False, server_default=text("now()"))

    track:   Mapped["EWTrack"]  = relationship(back_populates="track_emitters")
    emitter: Mapped["Emitter"]  = relationship("Emitter", back_populates="ew_track_emitters")


# ---------------------------------------------------------------------------
# ActivityReport
# ---------------------------------------------------------------------------
class ActivityReport(Base):
    """Parent submission wrapper — stored as-is from Trident/Thor."""
    __tablename__ = "activity_report"
    __table_args__ = (
        CheckConstraint(
            "start_at IS NULL OR end_at IS NULL OR end_at >= start_at",
            name="activity_report_end_after_start",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name:           Mapped[str | None]               = mapped_column(String(255), nullable=True)
    submitted_by:   Mapped[str]                      = mapped_column(String(255), nullable=False)
    start_at:       Mapped[datetime.datetime | None] = mapped_column(TZ, nullable=True)
    end_at:         Mapped[datetime.datetime | None] = mapped_column(TZ, nullable=True)
    classification: Mapped[ClassificationType]       = mapped_column(_cls, nullable=False)
    created_at = mapped_column(TZ, nullable=False, server_default=text("now()"))
    updated_at = mapped_column(TZ, nullable=False, server_default=text("now()"))

    instances:       Mapped[list["ActivityReportInstance"]] = relationship(
        back_populates="activity_report", cascade="all, delete-orphan"
    )
    report_missions: Mapped[list["ActivityReportMission"]]  = relationship(
        back_populates="activity_report", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# ActivityReportInstance
# ---------------------------------------------------------------------------
class ActivityReportInstance(Base):
    """
    One entry per EW Track in a report.
    Denormalises emitter, platform and position at snapshot time.

    DB index (migration): BTREE (first_seen_dtg, last_seen_dtg)
    """
    __tablename__ = "activity_report_instance"
    __table_args__ = (
        CheckConstraint("first_seen_dtg <= last_seen_dtg",                              name="ar_instance_time_range"),
        CheckConstraint("last_position_latitude_dd BETWEEN -90 AND 90",                name="ar_instance_lat_range"),
        CheckConstraint("last_position_longitude_dd BETWEEN -180 AND 180",             name="ar_instance_lon_range"),
        CheckConstraint("last_position_error_m IS NULL OR last_position_error_m >= 0", name="ar_instance_error_positive"),
        UniqueConstraint("activity_report_id", "track_id",                             name="ar_instance_unique"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    activity_report_id: Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), ForeignKey("activity_report.id"), nullable=False)
    track_id:           Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ew_track.id"),        nullable=True)

    # Emitter identity (snapshot at report time)
    emitter_id:           Mapped[int | None]   = mapped_column(Integer,     nullable=True)
    emitter_name:         Mapped[str | None]   = mapped_column(String(255), nullable=True)
    emitter_confidence:   Mapped[float | None] = mapped_column(Double,      nullable=True)
    emitter_country_code: Mapped[str | None]   = mapped_column(String(3),   nullable=True)
    emitter_country_name: Mapped[str | None]   = mapped_column(String(128), nullable=True)

    # Tactical
    signal_type: Mapped[SignalType]    = mapped_column(_sig, nullable=False)
    hostility:   Mapped[HostilityType] = mapped_column(_hos, nullable=False)

    # Time window
    first_seen_dtg: Mapped[datetime.datetime] = mapped_column(TZ, nullable=False)
    last_seen_dtg:  Mapped[datetime.datetime] = mapped_column(TZ, nullable=False)

    # Last known position
    last_position_longitude_dd: Mapped[float]      = mapped_column(Double,  nullable=False)
    last_position_latitude_dd:  Mapped[float]      = mapped_column(Double,  nullable=False)
    last_position_error_m:      Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Platform (snapshot — string fields, no live FK)
    platform_category: Mapped[PlatformCategoryType | None] = mapped_column(_pcat,       nullable=True)
    platform_name:     Mapped[str | None]                  = mapped_column(String(255), nullable=True)
    platform_id:       Mapped[str | None]                  = mapped_column(String(64),  nullable=True)
    platform_class:    Mapped[str | None]                  = mapped_column(String(128), nullable=True)

    # Metadata
    classification: Mapped[ClassificationType] = mapped_column(_cls,       nullable=False)
    source_system:  Mapped[str]                = mapped_column(String(64), nullable=False)
    created_at = mapped_column(TZ, nullable=False, server_default=text("now()"))
    updated_at = mapped_column(TZ, nullable=False, server_default=text("now()"))

    activity_report: Mapped["ActivityReport"]  = relationship(back_populates="instances")
    track:           Mapped["EWTrack | None"]  = relationship(back_populates="activity_report_instances")


# ---------------------------------------------------------------------------
# ActivityReportMission
# ---------------------------------------------------------------------------
class ActivityReportMission(Base):
    """
    Junction: links an activity report to one or more missions.
    mission_id → mission.id  (UUID FK, common_models.py)
    """
    __tablename__ = "activity_report_mission"
    __table_args__ = (
        UniqueConstraint("activity_report_id", "mission_id", name="ar_mission_unique"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    activity_report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("activity_report.id"), nullable=False)
    mission_id:         Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("mission.id"),         nullable=False)
    created_at = mapped_column(TZ, nullable=False, server_default=text("now()"))

    activity_report: Mapped["ActivityReport"] = relationship(back_populates="report_missions")
    mission:         Mapped["Mission"]         = relationship("Mission", back_populates="activity_report_missions")
