
def test_assign_platform_mission_not_found(
    self, client, seeded_air_platform
):
    """Return 404 when the mission does not exist."""

    resp = client.post(
        f"/missions/{uuid.uuid4()}/platform-instances",
        json={
            "platforms": [
                {
                    "platform_type": enums.EnvironmentEnum.AIR.value,
                    "platform_instance_id": seeded_air_platform,
                }
            ]
        },
    )

    assert resp.status_code == 404, resp.json()


def test_assign_platform_unknown_object_id_returns_404(
    self, client, valid_mission_payload
):
    """Return 404 when platform ID does not exist in NRD."""

    mission_resp = client.post(
        "/missions", json=valid_mission_payload
    )
    assert mission_resp.status_code == 201
    mission_id = mission_resp.json()["id"]

    resp = client.post(
        f"/missions/{mission_id}/platform-instances",
        json={
            "platforms": [
                {
                    "platform_type": enums.EnvironmentEnum.AIR.value,
                    "platform_instance_id": "NOPE-X",
                }
            ]
        },
    )

    assert resp.status_code == 404, resp.json()


def test_assign_platform_wrong_type_for_object_id_returns_404(
    self, client, valid_mission_payload, seeded_air_platform
):
    """An AIR platform ID must not validate as SPACE."""

    mission_resp = client.post(
        "/missions", json=valid_mission_payload
    )
    assert mission_resp.status_code == 201
    mission_id = mission_resp.json()["id"]

    resp = client.post(
        f"/missions/{mission_id}/platform-instances",
        json={
            "platforms": [
                {
                    "platform_type": enums.EnvironmentEnum.SPACE.value,
                    "platform_instance_id": seeded_air_platform,
                }
            ]
        },
    )

    assert resp.status_code == 404, resp.json()


def test_assign_platform_twice_returns_409(
    self, client, valid_mission_payload, seeded_air_platform
):
    """Assigning the same platform twice must return 409."""

    mission_resp = client.post(
        "/missions", json=valid_mission_payload
    )
    assert mission_resp.status_code == 201
    mission_id = mission_resp.json()["id"]

    payload = {
        "platforms": [
            {
                "platform_type": enums.EnvironmentEnum.AIR.value,
                "platform_instance_id": seeded_air_platform,
            }
        ]
    }

    first_resp = client.post(
        f"/missions/{mission_id}/platform-instances",
        json=payload,
    )
    assert first_resp.status_code == 201, first_resp.json()

    second_resp = client.post(
        f"/missions/{mission_id}/platform-instances",
        json=payload,
    )
    assert second_resp.status_code == 409, second_resp.json()


def test_assign_platform_invalid_type_returns_422(
    self, client, valid_mission_payload
):
    """Invalid platform type must fail Pydantic validation."""

    mission_resp = client.post(
        "/missions", json=valid_mission_payload
    )
    assert mission_resp.status_code == 201
    mission_id = mission_resp.json()["id"]

    resp = client.post(
        f"/missions/{mission_id}/platform-instances",
        json={
            "platforms": [
                {
                    "platform_type": "NOT_A_TYPE",
                    "platform_instance_id": "X",
                }
            ]
        },
    )

    assert resp.status_code == 422, resp.json()


def test_assign_multiple_platforms(
    self,
    client,
    valid_mission_payload,
    seeded_air_platform,
    seeded_air_platform_2,
):
    """Assign two valid NRD platforms in one request."""

    mission_resp = client.post(
        "/missions",
        json=valid_mission_payload,
    )

    assert mission_resp.status_code == 201, mission_resp.json()
    mission_id = mission_resp.json()["id"]

    platform_1 = seeded_air_platform
    platform_2 = seeded_air_platform_2

    assert platform_1 != platform_2

    payload = {
        "platforms": [
            {
                "platform_type": enums.EnvironmentEnum.AIR.value,
                "platform_instance_id": platform_1,
            },
            {
                "platform_type": enums.EnvironmentEnum.AIR.value,
                "platform_instance_id": platform_2,
            },
        ]
    }

    resp = client.post(
        f"/missions/{mission_id}/platform-instances",
        json=payload,
    )

    assert resp.status_code == 201, resp.json()

    body = resp.json()

    assigned_ids = {
        item["platform_instance_id"]
        for item in body["platform_instances"]
    }

    assert platform_1 in assigned_ids
    assert platform_2 in assigned_ids
    assert len(assigned_ids) == 2
