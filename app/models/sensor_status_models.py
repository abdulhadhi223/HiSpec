from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, String, Boolean, Enum as SAEnum, TIMESTAMP, Double
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from app.core.database import Base
from app.core.enum import (
    SensorType,
    SensorStatusType,
    SensorSourceType,
)

_senty   = SAEnum(SensorType,       name="sensor_type_enum",          create_type=False, validate_strings=True)
_senstat = SAEnum(SensorStatusType, name="sensor_status_enum",        create_type=False, validate_strings=True)
_sensou  = SAEnum(SensorSourceType, name="sensor_status_source_enum", create_type=False, validate_strings=True)


class SensorCatalog(Base):
    __tablename__ = "sensor_catalog"

    id:                 Mapped[uuid.UUID]   = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name:               Mapped[str]         = mapped_column(String(255))
    platform_entity_id: Mapped[str | None]  = mapped_column(
        String(50),
        ForeignKey("tech_platform_instance.entity_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    sensor_type:   Mapped[SensorType]  = mapped_column(_senty,  nullable=False)
    manufacturer:  Mapped[str]         = mapped_column(String(255))
    model:         Mapped[str]         = mapped_column(String(255))
    active:        Mapped[bool]        = mapped_column(Boolean, default=True)
    external_ref:  Mapped[str | None]  = mapped_column(String(255))
    nrd_entity_id: Mapped[str | None]  = mapped_column(String(50))
    metadata_dict: Mapped[str | None]  = mapped_column(String(255))
    created_at:    Mapped[str]         = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at:    Mapped[str]         = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    deleted_at:    Mapped[str | None]  = mapped_column(TIMESTAMP(timezone=True))

    nrd_platform: Mapped["TechPlatformInstance | None"] = relationship(
        "TechPlatformInstance",
        primaryjoin="SensorCatalog.platform_entity_id == TechPlatformInstance.entity_id",
        foreign_keys="[SensorCatalog.platform_entity_id]",
        backref="sensors",
        uselist=False,
        viewonly=True,
    )

    statuses: Mapped[list["SensorStatusRecord"]] = relationship(
        back_populates="sensor", cascade="all, delete-orphan"
    )


class SensorStatusRecord(Base):
    __tablename__ = "sensor_status"

    id:         Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sensor_id:  Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("sensor_catalog.id", ondelete="SET NULL"))
    status:     Mapped[SensorStatusType] = mapped_column(_senstat, nullable=False)
    source:     Mapped[SensorSourceType] = mapped_column(_sensou,  nullable=False)
    latitude:   Mapped[float | None]   = mapped_column(Double, nullable=True)
    longitude:  Mapped[float | None]   = mapped_column(Double, nullable=True)
    note:       Mapped[str | None]     = mapped_column(String(1000))
    created_by: Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[str]            = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    sensor: Mapped["SensorCatalog"] = relationship(back_populates="statuses")


class MissionPlatform(Base):
    __tablename__ = "mission_platform"

    id:                 Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mission_id:         Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("mission.id", ondelete="SET NULL"))
    platform_entity_id: Mapped[str]       = mapped_column(String(50), ForeignKey("tech_platform_instance.entity_id"))
    created_at:         Mapped[str]       = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    mission: Mapped["Mission"] = relationship("Mission", back_populates="mission_platform")

    nrd_platform: Mapped["TechPlatformInstance"] = relationship(
        "TechPlatformInstance",
        primaryjoin="MissionPlatform.platform_entity_id == TechPlatformInstance.entity_id",
        foreign_keys="[MissionPlatform.platform_entity_id]",
        uselist=False,
    )
