"""
app/models/ew_track_models.py

All ORM models for EW Track & Activity Report (schema v5.0).
Follows the single-file-per-feature convention of your existing orm_models.py.

ACTION REQUIRED in your app/models/__init__.py — add:
    from app.models.ew_track_models import (
        Sensor, Platform, Mission, Emitter,
        EWTrack, EWTrackPoint, EWTrackPointSensor, EWTrackEmitter,
        ActivityReport, ActivityReportInstance, ActivityReportMission,
    )
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

# ── Adjust this import to match how your project exposes Base ─────────────────
# Common patterns:
#   from app.core.database import Base
#   from app.database import Base
from app.core.database import Base

from app.core.enum import (
    ClassificationType,
    HostilityType,
    PlatformCategoryType,
    SensorRoleType,
    SignalType,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
TZ = TIMESTAMP(timezone=True)  # timezone-aware timestamp

# SA Enum columns — create_type=False: migration owns PG type lifecycle
_cls  = SAEnum(ClassificationType,    name="classification_type",    create_type=False)
_sig  = SAEnum(SignalType,            name="signal_type",            create_type=False)
_hos  = SAEnum(HostilityType,         name="hostility_type",         create_type=False)
_pcat = SAEnum(PlatformCategoryType,  name="platform_category_type", create_type=False)
_role = SAEnum(SensorRoleType,        name="sensor_role_type",       create_type=False)


# ---------------------------------------------------------------------------
# 1. Sensor
# ---------------------------------------------------------------------------
class Sensor(Base):
    """Registry of physical sensors (ESM, ELINT, …)."""
    __tablename__ = "sensor"

    key: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name:           Mapped[str]                  = mapped_column(String(255), nullable=False)
    type:           Mapped[str]                  = mapped_column(String(128), nullable=False)
    classification: Mapped[ClassificationType]   = mapped_column(_cls, nullable=False)
    created_at = mapped_column(TZ, nullable=False, server_default=text("now()"))
    updated_at = mapped_column(TZ, nullable=False, server_default=text("now()"))

    track_point_sensors: Mapped[list["EWTrackPointSensor"]] = relationship(
        back_populates="sensor"
    )


# ---------------------------------------------------------------------------
# 2. Platform
# ---------------------------------------------------------------------------
class Platform(Base):
    """Registry of ships, aircraft, and other platforms."""
    __tablename__ = "platform"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name:                  Mapped[str | None]                  = mapped_column(String(255), nullable=True)
    category:              Mapped[PlatformCategoryType | None] = mapped_column(_pcat, nullable=True)
    platform_country_code: Mapped[str | None]                  = mapped_column(String(3),   nullable=True)
    platform_country_name: Mapped[str | None]                  = mapped_column(String(128), nullable=True)
    classification:        Mapped[ClassificationType]          = mapped_column(_cls,  nullable=False)
    created_at = mapped_column(TZ, nullable=False, server_default=text("now()"))
    updated_at = mapped_column(TZ, nullable=False, server_default=text("now()"))

    ew_tracks: Mapped[list["EWTrack"]] = relationship(back_populates="platform")


# ---------------------------------------------------------------------------
# 3. Mission
# ---------------------------------------------------------------------------
class Mission(Base):
    """Mission context — optional link on EW tracks and activity reports."""
    __tablename__ = "mission"
    __table_args__ = (
        CheckConstraint(
            "start_at IS NULL OR end_at IS NULL OR end_at >= start_at",
            name="mission_end_after_start",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name:           Mapped[str]                          = mapped_column(String(255), nullable=False)
    start_at:       Mapped[datetime.datetime | None]     = mapped_column(TZ, nullable=True)
    end_at:         Mapped[datetime.datetime | None]     = mapped_column(TZ, nullable=True)
    classification: Mapped[ClassificationType]           = mapped_column(_cls, nullable=False)
    created_at = mapped_column(TZ, nullable=False, server_default=text("now()"))
    updated_at = mapped_column(TZ, nullable=False, server_default=text("now()"))

    ew_tracks:                Mapped[list["EWTrack"]]                  = relationship(back_populates="mission")
    activity_report_missions: Mapped[list["ActivityReportMission"]]    = relationship(back_populates="mission")


# ---------------------------------------------------------------------------
# 4. Emitter
# ---------------------------------------------------------------------------
class Emitter(Base):
    """Global emitter catalog."""
    __tablename__ = "emitter"

    key: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    emitter_id_sensor:    Mapped[int | None] = mapped_column(Integer,     nullable=True)
    emitter_name:         Mapped[str | None] = mapped_column(String(255), nullable=True)
    emitter_country_code: Mapped[str | None] = mapped_column(String(3),   nullable=True)
    emitter_country_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at = mapped_column(TZ, nullable=False, server_default=text("now()"))
    updated_at = mapped_column(TZ, nullable=False, server_default=text("now()"))

    ew_track_emitters: Mapped[list["EWTrackEmitter"]] = relationship(back_populates="emitter")


# ---------------------------------------------------------------------------
# 5. EWTrack
# ---------------------------------------------------------------------------
class EWTrack(Base):
    """
    Master track record per emitter observation.
    UNIQUE (source_system, source_track_id) → idempotent ingestion.
    """
    __tablename__ = "ew_track"
    __table_args__ = (
        UniqueConstraint("source_system", "source_track_id", name="ew_track_idempotency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    source_system:   Mapped[str]                  = mapped_column(String(64),  nullable=False)
    source_track_id: Mapped[str | None]           = mapped_column(String(128), nullable=True)
    hostility:       Mapped[HostilityType]        = mapped_column(_hos, nullable=False)
    classification:  Mapped[ClassificationType]   = mapped_column(_cls, nullable=False)
    platform_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform.id"), nullable=True
    )
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mission.id"), nullable=True
    )
    created_at = mapped_column(TZ, nullable=False, server_default=text("now()"))
    updated_at = mapped_column(TZ, nullable=False, server_default=text("now()"))

    platform: Mapped["Platform | None"]                       = relationship(back_populates="ew_tracks")
    mission:  Mapped["Mission | None"]                        = relationship(back_populates="ew_tracks")
    track_points:               Mapped[list["EWTrackPoint"]]           = relationship(back_populates="track", cascade="all, delete-orphan")
    track_emitters:             Mapped[list["EWTrackEmitter"]]         = relationship(back_populates="track", cascade="all, delete-orphan")
    activity_report_instances:  Mapped[list["ActivityReportInstance"]] = relationship(back_populates="track")


# ---------------------------------------------------------------------------
# 6. EWTrackPoint  (append-only)
# ---------------------------------------------------------------------------
class EWTrackPoint(Base):
    """
    Append-only position samples. NEVER update or delete except by admin.
    DB indexes managed by migration:
      BTREE (track_id, observed_at)  — time-ordered fetch
      GIST  ll_to_earth(lat, lon)    — AOI spatial queries
    """
    __tablename__ = "ew_track_point"
    __table_args__ = (
        CheckConstraint("lat BETWEEN -90 AND 90",          name="ew_track_point_lat_range"),
        CheckConstraint("lon BETWEEN -180 AND 180",         name="ew_track_point_lon_range"),
        CheckConstraint("error_m IS NULL OR error_m >= 0", name="ew_track_point_error_positive"),
        UniqueConstraint("track_id", "observed_at", "lat", "lon", name="ew_track_point_unique"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    track_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ew_track.id"), nullable=False
    )
    observed_at:    Mapped[datetime.datetime]    = mapped_column(TZ,     nullable=False)
    lat:            Mapped[float]                = mapped_column(Double, nullable=False)
    lon:            Mapped[float]                = mapped_column(Double, nullable=False)
    error_m:        Mapped[float | None]         = mapped_column(Double, nullable=True)
    classification: Mapped[ClassificationType]   = mapped_column(_cls,   nullable=False)

    track:         Mapped["EWTrack"]                   = relationship(back_populates="track_points")
    point_sensors: Mapped[list["EWTrackPointSensor"]]  = relationship(back_populates="point", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# 7. EWTrackPointSensor
# ---------------------------------------------------------------------------
class EWTrackPointSensor(Base):
    """Junction: which sensor produced which track point, with optional role."""
    __tablename__ = "ew_track_point_sensor"
    __table_args__ = (
        UniqueConstraint("point_id", "sensor_key", name="ew_track_point_sensor_unique"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    point_id:   Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ew_track_point.id"), nullable=False)
    sensor_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sensor.key"),        nullable=False)
    role:       Mapped[SensorRoleType | None]  = mapped_column(_role, nullable=True)

    point:  Mapped["EWTrackPoint"] = relationship(back_populates="point_sensors")
    sensor: Mapped["Sensor"]       = relationship(back_populates="track_point_sensors")


# ---------------------------------------------------------------------------
# 8. EWTrackEmitter
# ---------------------------------------------------------------------------
class EWTrackEmitter(Base):
    """
    Emitter identity + full RF fingerprint per track per emitter mode.
    One row per unique (track_id, emitter_key, emitter_mode).
    """
    __tablename__ = "ew_track_emitter"
    __table_args__ = (
        CheckConstraint(
            "emitter_confidence IS NULL OR emitter_confidence BETWEEN 0 AND 1",
            name="ew_track_emitter_confidence_range",
        ),
        UniqueConstraint("track_id", "emitter_key", "emitter_mode", name="ew_track_emitter_unique"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    track_id:    Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ew_track.id"),  nullable=False)
    emitter_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("emitter.key"), nullable=False)

    first_seen_at:      Mapped[datetime.datetime] = mapped_column(TZ,     nullable=False)
    last_seen_at:       Mapped[datetime.datetime] = mapped_column(TZ,     nullable=False)
    emitter_confidence: Mapped[float | None]      = mapped_column(Double, nullable=True)
    signal_type:        Mapped[SignalType]         = mapped_column(_sig,   nullable=False)
    emitter_mode:       Mapped[str]               = mapped_column(String(128), nullable=False)

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

    track:   Mapped["EWTrack"]   = relationship(back_populates="track_emitters")
    emitter: Mapped["Emitter"]   = relationship(back_populates="ew_track_emitters")


# ---------------------------------------------------------------------------
# 9. ActivityReport
# ---------------------------------------------------------------------------
class ActivityReport(Base):
    """Parent submission wrapper for an activity report."""
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

    instances:       Mapped[list["ActivityReportInstance"]] = relationship(back_populates="activity_report", cascade="all, delete-orphan")
    report_missions: Mapped[list["ActivityReportMission"]]  = relationship(back_populates="activity_report", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# 10. ActivityReportInstance
# ---------------------------------------------------------------------------
class ActivityReportInstance(Base):
    """
    One entry per EW Track in a report.
    Denormalises emitter, platform, and last-known position at snapshot time.
    DB index (migration): BTREE (first_seen_dtg, last_seen_dtg)
    """
    __tablename__ = "activity_report_instance"
    __table_args__ = (
        CheckConstraint("first_seen_dtg <= last_seen_dtg",                           name="ar_instance_time_range"),
        CheckConstraint("last_position_latitude_dd BETWEEN -90 AND 90",             name="ar_instance_lat_range"),
        CheckConstraint("last_position_longitude_dd BETWEEN -180 AND 180",          name="ar_instance_lon_range"),
        CheckConstraint("last_position_error_m IS NULL OR last_position_error_m >= 0", name="ar_instance_error_positive"),
        UniqueConstraint("activity_report_id", "track_id",                           name="ar_instance_unique"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    activity_report_id: Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("activity_report.id"), nullable=False)
    track_id:           Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ew_track.id"),       nullable=True)

    # Emitter identity (snapshot at report time)
    emitter_id:           Mapped[int | None]   = mapped_column(Integer,     nullable=True)
    emitter_name:         Mapped[str | None]   = mapped_column(String(255), nullable=True)
    emitter_confidence:   Mapped[float | None] = mapped_column(Double,      nullable=True)
    emitter_country_code: Mapped[str | None]   = mapped_column(String(3),   nullable=True)
    emitter_country_name: Mapped[str | None]   = mapped_column(String(128), nullable=True)

    # Tactical
    signal_type: Mapped[SignalType]   = mapped_column(_sig, nullable=False)
    hostility:   Mapped[HostilityType] = mapped_column(_hos, nullable=False)

    # Time window
    first_seen_dtg: Mapped[datetime.datetime] = mapped_column(TZ, nullable=False)
    last_seen_dtg:  Mapped[datetime.datetime] = mapped_column(TZ, nullable=False)

    # Last known position
    last_position_longitude_dd: Mapped[float]      = mapped_column(Double,   nullable=False)
    last_position_latitude_dd:  Mapped[float]      = mapped_column(Double,   nullable=False)
    last_position_error_m:      Mapped[int | None] = mapped_column(Integer,  nullable=True)

    # Platform (snapshot at report time)
    platform_category: Mapped[PlatformCategoryType | None] = mapped_column(_pcat,       nullable=True)
    platform_name:     Mapped[str | None]                  = mapped_column(String(255), nullable=True)
    platform_id:       Mapped[str | None]                  = mapped_column(String(64),  nullable=True)
    platform_class:    Mapped[str | None]                  = mapped_column(String(128), nullable=True)

    # Metadata
    classification: Mapped[ClassificationType] = mapped_column(_cls,       nullable=False)
    source_system:  Mapped[str]                = mapped_column(String(64), nullable=False)
    created_at = mapped_column(TZ, nullable=False, server_default=text("now()"))
    updated_at = mapped_column(TZ, nullable=False, server_default=text("now()"))

    activity_report: Mapped["ActivityReport"]    = relationship(back_populates="instances")
    track:           Mapped["EWTrack | None"]    = relationship(back_populates="activity_report_instances")


# ---------------------------------------------------------------------------
# 11. ActivityReportMission
# ---------------------------------------------------------------------------
class ActivityReportMission(Base):
    """Junction: links an activity report to one or more missions."""
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
    mission:         Mapped["Mission"]         = relationship(back_populates="activity_report_missions")
