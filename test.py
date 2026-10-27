def test_assign_multiple_platforms(
    self,
    client,
    valid_mission_payload,
    seeded_air_platforms,
):
    mission_resp = client.post(
        "/missions",
        json=valid_mission_payload,
    )

    assert mission_resp.status_code == 201, mission_resp.json()
    mission_id = mission_resp.json()["id"]

    # Fixture must return two existing NRD platform IDs
    platform_1, platform_2 = seeded_air_platforms

    resp = client.post(
        f"/missions/{mission_id}/platform-instances",
        json={
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
        },
    )

    assert resp.status_code == 201, resp.json()

    body = resp.json()

    assigned_ids = {
        item["platform_instance_id"]
        for item in body["platform_instances"]
    }

    assert platform_1 in assigned_ids
    assert platform_2 in assigned_ids