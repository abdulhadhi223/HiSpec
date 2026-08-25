class PlatformAssignSchema(BaseModel):
    platform_instance_type: enums.EnvironmentEnum
    platform_instance_object_id: str = Field(max_length=128)


class SensorAssignSchema(BaseModel):
    sensor_ids: list[uuid.UUID] = Field(min_length=1)

@router.post(
    "/missions/{mission_id}/platform-instance",
    response_model=MissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a platform instance to a mission",
    description=(
        "Assigns a platform instance to the mission, identified by platform type "
        "and object id. Returns the updated mission."
    ),
)
def assign_platform(
    mission_id: uuid.UUID,
    data: PlatformAssignSchema,
    db: Session = Depends(get_db),
):
    return assign_platform_to_mission(
        db,
        mission_id,
        data.platform_instance_type,
        data.platform_instance_object_id,
    )


@router.post(
    "/missions/{mission_id}/sensors",
    response_model=MissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign sensors to a mission",
    description=(
        "Assigns one or more sensors to the mission. Sensors must belong to the "
        "mission's assigned platform instance. Returns the updated mission."
    ),
)
def assign_sensors(
    mission_id: uuid.UUID,
    data: SensorAssignSchema,
    db: Session = Depends(get_db),
):
    return assign_sensors_to_mission(db, mission_id, data.sensor_ids)

def assign_platform_to_mission(
    db: Session,
    mission_id: uuid.UUID,
    platform_instance_type: enums.EnvironmentEnum,
    platform_instance_object_id: str,
) -> Mission:
    mission = db.get(Mission, mission_id)
    if not mission or mission.deleted_at is not None:
        raise NotFoundError(f"Mission {mission_id} not found")

    # resolves against the correct one of the six type tables
    validate_platform_exists(db, platform_instance_type, platform_instance_object_id)

    if mission.platform_instance is not None:
        raise ConflictError("Mission already has a platform instance assigned")

    mission.platform_instance = MissionPlatform(
        mission_id=mission.id,
        platform_instance_type=platform_instance_type,
        platform_instance_object_id=platform_instance_object_id,
    )
    db.commit()
    db.refresh(mission)
    return mission


def assign_sensors_to_mission(
    db: Session,
    mission_id: uuid.UUID,
    sensor_ids: list[uuid.UUID],
) -> Mission:
    mission = db.get(Mission, mission_id)
    if not mission or mission.deleted_at is not None:
        raise NotFoundError(f"Mission {mission_id} not found")

    platform = mission.platform_instance
    if platform is None:
        raise BusinessValidationError(
            "Mission has no platform instance assigned; assign one before adding sensors"
        )

    sensors = db.execute(
        select(SensorCatalog).where(SensorCatalog.id.in_(sensor_ids))
    ).scalars().all()

    found_ids = {s.id for s in sensors}
    missing = set(sensor_ids) - found_ids
    if missing:
        raise NotFoundError(f"Sensors not found: {sorted(str(i) for i in missing)}")

    # Spec: "sensors belong to assigned platform instance"
    mismatched = [
        s.id for s in sensors
        if s.platform_instance_type != platform.platform_instance_type
        or s.platform_instance_object_id != platform.platform_instance_object_id
    ]
    if mismatched:
        raise BusinessValidationError(
            f"Sensors do not belong to the mission's platform instance: "
            f"{sorted(str(i) for i in mismatched)}"
        )

    for sensor in sensors:
        mission.sensors.append(MissionSensor(mission_id=mission.id, sensor_id=sensor.id))

    db.commit()
    db.refresh(mission)
    return mission

# #################################
class TestAssignPlatform:
    def test_assign_platform_success(self, client, valid_mission_payload, seeded_air_platform):
        mission_id = client.post("/missions", json=valid_mission_payload).json()["id"]

        resp = client.post(
            f"/missions/{mission_id}/platform-instance",
            json={
                "platform_instance_type": "AIR",
                "platform_instance_object_id": seeded_air_platform,
            },
        )
        assert resp.status_code == 201, resp.json()
        body = resp.json()
        assert body["platform_instance"]["platform_instance_object_id"] == seeded_air_platform

    def test_assign_platform_mission_not_found(self, client, seeded_air_platform):
        resp = client.post(
            f"/missions/{uuid.uuid4()}/platform-instance",
            json={
                "platform_instance_type": "AIR",
                "platform_instance_object_id": seeded_air_platform,
            },
        )
        assert resp.status_code == 404

    def test_assign_platform_unknown_object_id_returns_404(self, client, valid_mission_payload):
        mission_id = client.post("/missions", json=valid_mission_payload).json()["id"]

        resp = client.post(
            f"/missions/{mission_id}/platform-instance",
            json={"platform_instance_type": "AIR", "platform_instance_object_id": "NOPE-X"},
        )
        assert resp.status_code == 404

    def test_assign_platform_wrong_type_for_object_id_returns_404(
        self, client, valid_mission_payload, seeded_air_platform
    ):
        """object_id exists under AIR, so looking it up as SPACE must miss."""
        mission_id = client.post("/missions", json=valid_mission_payload).json()["id"]

        resp = client.post(
            f"/missions/{mission_id}/platform-instance",
            json={
                "platform_instance_type": "SPACE",
                "platform_instance_object_id": seeded_air_platform,
            },
        )
        assert resp.status_code == 404

    def test_assign_platform_twice_returns_409(
        self, client, valid_mission_payload, seeded_air_platform
    ):
        mission_id = client.post("/missions", json=valid_mission_payload).json()["id"]
        payload = {
            "platform_instance_type": "AIR",
            "platform_instance_object_id": seeded_air_platform,
        }

        assert client.post(f"/missions/{mission_id}/platform-instance", json=payload).status_code == 201
        assert client.post(f"/missions/{mission_id}/platform-instance", json=payload).status_code == 409

    def test_assign_platform_invalid_type_returns_422(self, client, valid_mission_payload):
        mission_id = client.post("/missions", json=valid_mission_payload).json()["id"]

        resp = client.post(
            f"/missions/{mission_id}/platform-instance",
            json={"platform_instance_type": "NOT_A_TYPE", "platform_instance_object_id": "X"},
        )
        assert resp.status_code == 422


class TestAssignSensors:
    def test_assign_sensors_success(self, client, mission_with_platform, sensor_on_platform):
        resp = client.post(
            f"/missions/{mission_with_platform}/sensors",
            json={"sensor_ids": [sensor_on_platform]},
        )
        assert resp.status_code == 201, resp.json()
        assert len(resp.json()["sensors"]) == 1

    def test_assign_sensors_no_platform_assigned_returns_400(
        self, client, valid_mission_payload, sensor_on_platform
    ):
        mission_id = client.post("/missions", json=valid_mission_payload).json()["id"]

        resp = client.post(
            f"/missions/{mission_id}/sensors",
            json={"sensor_ids": [sensor_on_platform]},
        )
        assert resp.status_code == 400

    def test_assign_sensors_unknown_sensor_returns_404(self, client, mission_with_platform):
        resp = client.post(
            f"/missions/{mission_with_platform}/sensors",
            json={"sensor_ids": [str(uuid.uuid4())]},
        )
        assert resp.status_code == 404

    def test_assign_sensors_from_other_platform_returns_400(
        self, client, mission_with_platform, sensor_on_other_platform
    ):
        """The core spec rule: sensors must belong to the assigned platform instance."""
        resp = client.post(
            f"/missions/{mission_with_platform}/sensors",
            json={"sensor_ids": [sensor_on_other_platform]},
        )
        assert resp.status_code == 400

    def test_assign_sensors_partial_mismatch_rejects_all(
        self, client, mission_with_platform, sensor_on_platform, sensor_on_other_platform
    ):
        resp = client.post(
            f"/missions/{mission_with_platform}/sensors",
            json={"sensor_ids": [sensor_on_platform, sensor_on_other_platform]},
        )
        assert resp.status_code == 400

        # nothing should have been assigned
        mission = client.get(f"/missions/{mission_with_platform}").json()
        assert mission["sensors"] == []

    def test_assign_sensors_empty_list_returns_422(self, client, mission_with_platform):
        resp = client.post(f"/missions/{mission_with_platform}/sensors", json={"sensor_ids": []})
        assert resp.status_code == 422