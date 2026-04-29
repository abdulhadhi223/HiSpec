"""
app/models/orm_models.py

Stub definitions for existing NMDB catalog tables.

These are PLACEHOLDER models for this feature branch only.
When this branch is merged into the main NMDB project, delete this file —
the real TechPlatformInstance and TechSensor definitions in the main
orm_models.py will take over.

Verify that column names and types here match the real tables before merging.
"""

import datetime

from sqlalchemy import Enum as SAEnum, Integer, String, TIMESTAMP, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
import uuid

from app.core.database import Base
from app.core.enum import Classification, PlatformCategoryType

TZ    = TIMESTAMP(timezone=True)
_cls  = SAEnum(Classification,   name="classification_type",    create_type=False)
_pcat = SAEnum(PlatformCategoryType, name="platform_category_type", create_type=False)


class TechPlatformInstance(Base):
    """Stub — real definition lives in the main project's orm_models.py."""
    __tablename__ = "tech_platform_instance"

    id:                    Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:                  Mapped[str | None]       = mapped_column(String(255), nullable=True)
    category:              Mapped[PlatformCategoryType | None] = mapped_column(_pcat, nullable=True)
    platform_country_code: Mapped[str | None]       = mapped_column(String(3),   nullable=True)
    platform_country_name: Mapped[str | None]       = mapped_column(String(128), nullable=True)
    classification:        Mapped[Classification] = mapped_column(_cls, nullable=False)
    created_at = mapped_column(TZ, nullable=False, server_default=text("now()"))
    updated_at = mapped_column(TZ, nullable=False, server_default=text("now()"))


class TechSensor(Base):
    """Stub — real definition lives in the main project's orm_models.py."""
    __tablename__ = "tech_sensor"
    __table_args__ = (
        UniqueConstraint("key", name="tech_sensor_key_unique"),
    )

    id:             Mapped[int]               = mapped_column(Integer, primary_key=True, autoincrement=True)
    key:            Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), nullable=False, server_default=text("gen_random_uuid()"))
    name:           Mapped[str]               = mapped_column(String(255), nullable=False)
    type:           Mapped[str]               = mapped_column(String(128), nullable=False)
    classification: Mapped[Classification] = mapped_column(_cls, nullable=False)
    created_at = mapped_column(TZ, nullable=False, server_default=text("now()"))
    updated_at = mapped_column(TZ, nullable=False, server_default=text("now()"))


class SensorCatalog(Base):
    """Stub — sensor catalog referenced by EWTrackPointSensor."""
    __tablename__ = "sensor_catalog"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    created_at = mapped_column(TZ, nullable=False, server_default=text("now()"))
    updated_at = mapped_column(TZ, nullable=False, server_default=text("now()"))
