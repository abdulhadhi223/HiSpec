"""Pydantic v2 schemas for reading mission platform and sensor assignments."""

import uuid

from pydantic import BaseModel, ConfigDict, Field


class MissionPlatformInstanceResponse(BaseModel):
    """Platform instance currently assigned to a mission."""

    model_config = ConfigDict(from_attributes=True)

    mission_id: uuid.UUID
    platform_instance_type: str
    platform_instance_object_id: str
    platform_instance_name: str | None = None


class MissionSensorResponse(BaseModel):
    """Single sensor assigned to a mission."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sensor_id: str
    sensor_name: str | None = None


class MissionSensorListResponse(BaseModel):
    """Sensors assigned to a mission."""

    total: int = Field(ge=0)
    items: list[MissionSensorResponse]

Service — add to the existing mission service module

python
def get_mission_platform_instance(
    db: Session, mission_id: uuid.UUID
) -> MissionPlatformInstanceResponse:
    """Returns the platform instance assigned to a mission."""
    _get_mission(db, mission_id)
    try:
        record = db.execute(
            select(MissionPlatform).where(MissionPlatform.mission_id == mission_id)
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise DatabaseError(ErrorCode.MISSION_LOOKUP_FAILED) from exc

    if record is None:
        raise NotFoundError(ErrorCode.MISSION_HAS_NO_PLATFORM)

    model = _PLATFORM_TYPE_MODEL_MAP.get(record.platform_instance_type)
    name = None
    if model is not None:
        instance = db.get(model, record.platform_instance_object_id)
        name = getattr(instance, "name", None) if instance else None

    return MissionPlatformInstanceResponse(
        mission_id=record.mission_id,
        platform_instance_type=record.platform_instance_type.value,
        platform_instance_object_id=record.platform_instance_object_id,
        platform_instance_name=name,
    )


def get_mission_sensors(
    db: Session, mission_id: uuid.UUID
) -> MissionSensorListResponse:
    """Returns every sensor assigned to a mission."""
    _get_mission(db, mission_id)
    try:
        records = (
            db.execute(
                select(MissionSensor)
                .where(MissionSensor.mission_id == mission_id)
                .order_by(MissionSensor.sensor_id)
            )
            .scalars()
            .all()
        )
    except SQLAlchemyError as exc:
        raise DatabaseError(ErrorCode.MISSION_LOOKUP_FAILED) from exc

    items = [
        MissionSensorResponse(
            id=r.id,
            sensor_id=r.sensor_id,
            sensor_name=getattr(r.sensor, "name", None),
        )
        for r in records
    ]
    return MissionSensorListResponse(total=len(items), items=items)

Router

python
@router.get(
    "/{mission_id}/platform-instance",
    response_model=MissionPlatformInstanceResponse,
)
def get_mission_platform_instance(
    mission_id: uuid.UUID, db: Session = Depends(get_db)
) -> MissionPlatformInstanceResponse:
    """Returns the platform instance assigned to a mission."""
    return mission_service.get_mission_platform_instance(db, mission_id)


@router.get("/{mission_id}/sensors", response_model=MissionSensorListResponse)
def get_mission_sensors(
    mission_id: uuid.UUID, db: Session = Depends(get_db)
) -> MissionSensorListResponse:
    """Returns the sensors assigned to a mission."""
    return mission_service.get_mission_sensors(db, mission_id)

Tests

python
def test_returns_assigned_platform_instance(client, mission_with_platform) -> None:
    """Returns the platform instance assigned to the mission."""
    response = client.get(
        f"/missions/{mission_with_platform.id}/platform-instance"
    )

    assert response.status_code == 200
    assert response.json()["platform_instance_object_id"]


def test_returns_400_when_no_platform_assigned(client, seeded_mission) -> None:
    """Returns 400 when the mission has no platform instance assigned."""
    response = client.get(f"/missions/{seeded_mission.id}/platform-instance")

    assert response.status_code == 400


def test_returns_404_for_unknown_mission_platform(client) -> None:
    """Returns 404 for a well-formed but unmapped mission id."""
    response = client.get(f"/missions/{uuid.uuid4()}/platform-instance")

    assert response.status_code == 404


def test_lists_assigned_sensors(client, mission_with_sensors) -> None:
    """Returns every sensor assigned to the mission."""
    body = client.get(f"/missions/{mission_with_sensors.id}/sensors").json()

    assert body["total"] == len(body["items"])
    assert body["total"] > 0


def test_returns_empty_sensor_list_when_none_assigned(client, seeded_mission) -> None:
    """Returns an empty collection when no sensors are assigned."""
    body = client.get(f"/missions/{seeded_mission.id}/sensors").json()

    assert body == {"total": 0, "items": []}