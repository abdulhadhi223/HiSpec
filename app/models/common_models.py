"""
app/models/common_models.py

Shared domain entities used across multiple features.
Import from here — never define Mission elsewhere.

Current entities:
  - Mission  : time-bounded mission context (EW Tracks + Activity Reports)

Relationship back-refs (ew_tracks, activity_report_missions)
are wired via string references so this file has zero imports from
ew_track_models.py — no circular dependency.
"""

import uuid
import datetime

from sqlalchemy import (
    CheckConstraint,
    Enum as SAEnum,
    String,
    TIMESTAMP,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

# Use your project's shared Base
from app.core.database import Base

# Enums live in app/core/enum.py
from app.core.enum import Classification

TZ   = TIMESTAMP(timezone=True)
_cls = SAEnum(Classification, name="classification_type", create_type=False)


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
    classification: Mapped[Classification]       = mapped_column(_cls, nullable=False)
    created_at = mapped_column(TZ, nullable=False, server_default=text("now()"))
    updated_at = mapped_column(TZ, nullable=False, server_default=text("now()"))

    # Back-refs — populated by relationships defined in ew_track_models.py
    ew_tracks: Mapped[list["EWTrack"]] = relationship(
        "EWTrack", back_populates="mission"
    )
    activity_report_missions: Mapped[list["ActivityReportMission"]] = relationship(
        "ActivityReportMission", back_populates="mission"
    )
