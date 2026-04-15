"""
app/models/common_models.py

Shared domain entities used across multiple features.
Import from here — never define Mission or Emitter elsewhere.

Current entities:
  - Mission  : time-bounded mission context (EW Tracks + Activity Reports)
  - Emitter  : global ELINT emitter catalog (EW Tracks)

Relationship back-refs (ew_tracks, activity_report_missions, ew_track_emitters)
are wired via string references so this file has zero imports from
ew_track_models.py — no circular dependency.
"""

import uuid
import datetime

from sqlalchemy import (
    CheckConstraint,
    Enum as SAEnum,
    Integer,
    String,
    TIMESTAMP,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

# Use your project's shared Base
from app.core.database import Base

# Enums live in app/core/enum.py
from app.core.enum import ClassificationType

TZ   = TIMESTAMP(timezone=True)
_cls = SAEnum(ClassificationType, name="classification_type", create_type=False)


# ---------------------------------------------------------------------------
# Mission
# ---------------------------------------------------------------------------
class Mission(Base):
    """
    Time-bounded mission context.

    Shared by:
      - EWTrack          (ew_track.mission_id → mission.id)
      - ActivityReport   (activity_report_mission.mission_id → mission.id)

    Lives here in common_models.py so both feature modules can import it
    without creating a circular dependency.
    """
    __tablename__ = "mission"
    __table_args__ = (
        CheckConstraint(
            "start_at IS NULL OR end_at IS NULL OR end_at >= start_at",
            name="mission_end_after_start",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name:           Mapped[str]                      = mapped_column(String(255), nullable=False)
    start_at:       Mapped[datetime.datetime | None] = mapped_column(TZ, nullable=True)
    end_at:         Mapped[datetime.datetime | None] = mapped_column(TZ, nullable=True)
    classification: Mapped[ClassificationType]       = mapped_column(_cls, nullable=False)
    created_at = mapped_column(TZ, nullable=False, server_default=text("now()"))
    updated_at = mapped_column(TZ, nullable=False, server_default=text("now()"))

    # Back-refs — populated by relationships defined in ew_track_models.py
    ew_tracks: Mapped[list["EWTrack"]] = relationship(
        "EWTrack", back_populates="mission"
    )
    activity_report_missions: Mapped[list["ActivityReportMission"]] = relationship(
        "ActivityReportMission", back_populates="mission"
    )


# ---------------------------------------------------------------------------
# Emitter
# ---------------------------------------------------------------------------
class Emitter(Base):
    """
    Global ELINT emitter catalog.
    One row per known emitter type (make / model / mode-family).

    Referenced by:
      - EWTrackEmitter  (ew_track_emitter.emitter_key → emitter.key)

    PK is named `key` (UUID) — consistent with the schema v5.0 convention
    of using `key` for catalog/reference tables and `id` for transactional ones.
    """
    __tablename__ = "emitter"

    key: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    emitter_id_sensor:    Mapped[int | None] = mapped_column(Integer,     nullable=True)
    emitter_name:         Mapped[str | None] = mapped_column(String(255), nullable=True)
    emitter_country_code: Mapped[str | None] = mapped_column(String(3),   nullable=True)
    emitter_country_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at = mapped_column(TZ, nullable=False, server_default=text("now()"))
    updated_at = mapped_column(TZ, nullable=False, server_default=text("now()"))

    # Back-ref — populated by EWTrackEmitter relationship in ew_track_models.py
    ew_track_emitters: Mapped[list["EWTrackEmitter"]] = relationship(
        "EWTrackEmitter", back_populates="emitter"
    )
