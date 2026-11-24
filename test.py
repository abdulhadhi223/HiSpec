"""QA recipes for independent catalog sensors and their status history."""
from datetime import timedelta, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select

from .records import store_records


class Options(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Platform(Options):
    platform_type: str
    platform_instance_id: str = Field(min_length=1, pattern=r"\S")


class CatalogOptions(Options):
    count: int = Field(default=2, gt=0, strict=True)
    sensor_type: str
    platform: Platform | None = None


class StatusOptions(Options):
    sensor_ids: list[UUID] = Field(default_factory=list)
    created_by: UUID
    source: str
    history: list[str] = Field(min_length=1)
    start_at: AwareDatetime


def _enum(column, value):
    members = column.property.columns[0].type.enum_class

    for member in members:
        if value in (member.name, member.value):
            return member

    raise ValueError(f"{column.key}: choose from {[m.value for m in members]}")


def sensor_catalog(db, dataset, options, prior_results):
    from app.models.sensor_status_models import SensorCatalog

    cfg = CatalogOptions.model_validate(options)
    ns = uuid5(NAMESPACE_URL, f"nmdb-qa/catalog/{dataset}")
    kind = _enum(SensorCatalog.sensor_type, cfg.sensor_type)
    ids = [uuid5(ns, str(i)) for i in range(cfg.count)]

    recipes = [
        dict(
            id=key,
            name=f"QA-{ns.hex[:16]}-{i}",
            model="QA fixture",
            sensor_type=kind,
            manufacturer="QA",
            active=True,
            deleted_at=None,
            metadata_dict=None,
            external_ref=None,
            nrd_entity_id=None,
        )
        for i, key in enumerate(ids)
    ]

    result = store_records(
        db,
        SensorCatalog,
        recipes,
        create_only={
            "platform_type": None,
            "platform_instance_id": None,
        },
    )

    if cfg.platform:
        target = (
            _enum(SensorCatalog.platform_type, cfg.platform.platform_type),
            cfg.platform.platform_instance_id,
        )
        sensors = (
            select(SensorCatalog)
            .where(SensorCatalog.id.in_(ids))
            .order_by(SensorCatalog.id)
        )

        for sensor in db.scalars(
            sensors.with_for_update().execution_options(populate_existing=True)
        ):
            current = (sensor.platform_type, sensor.platform_instance_id)

            if current == (None, None):
                sensor.platform_type, sensor.platform_instance_id = target
            elif current != target:
                raise ValueError(
                    f"Catalog fixture {sensor.id} already belongs to a different platform"
                )

        db.flush()

    return result


def sensor_status(db, dataset, options, prior_results):
    from app.models.sensor_status_models import SensorCatalog, SensorStatus

    defaults = {
        "sensor_ids": prior_results.get("sensor_catalog", {}).get("ids", [])
    }
    cfg = StatusOptions.model_validate({**defaults, **options})
    ids = cfg.sensor_ids

    if not ids or len(set(ids)) != len(ids):
        raise ValueError(
            "Supply distinct test sensor_ids or depend on sensor_catalog"
        )

    available = select(SensorCatalog.id).where(
        SensorCatalog.id.in_(ids),
        SensorCatalog.deleted_at.is_(None),
    )
    missing = set(ids) - set(db.scalars(available))

    if missing:
        raise ValueError(f"Missing catalog sensors: {sorted(map(str, missing))}")

    ns = uuid5(NAMESPACE_URL, f"nmdb-qa/status/{dataset}")
    start = cfg.start_at.astimezone(timezone.utc)
    source = _enum(SensorStatus.source, cfg.source)
    states = [_enum(SensorStatus.status, state) for state in cfg.history]

    recipes = (
        dict(
            id=uuid5(ns, f"{sensor_id}/{i}"),
            sensor_id=sensor_id,
            status=state,
            source=source,
            created_by=cfg.created_by,
            created_at=start + timedelta(seconds=i),
            note="QA fixture",
            latitude=None,
            longitude=None,
        )
        for sensor_id in ids
        for i, state in enumerate(states)
    )

    return store_records(db, SensorStatus, recipes)


"""Insert repeatable synthetic rows for EW Tracks in a QA database."""

from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select

from .records import store_records


def _uuids(value, name):
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON list of UUIDs")

    try:
        ids = [UUID(str(item)) for item in value]
    except ValueError as exc:
        raise ValueError(f"{name} contains an invalid UUID") from exc

    if len(ids) != len(set(ids)):
        raise ValueError(f"{name} contains duplicate IDs")

    return ids


def _number(options, key, default, minimum):
    value = options.get(key, default)

    if type(value) is not int or value < minimum:
        raise ValueError(f"{key} must be an integer >= {minimum}")

    return value


def _check_references(db, model, ids):
    for key in ids:
        record = db.get(model, key)

        if record is None or getattr(record, "deleted_at", None) is not None:
            raise ValueError(f"Missing active {model.__name__} test fixture {key}")


def _persist_level(db, model, wanted, query, expected_existing):
    """Check the whole persisted shape before reusing the fixture's children."""
    existing = {item.id: item for item in db.scalars(query)}

    if set(existing) != expected_existing:
        raise ValueError(
            f"{model.__name__} fixture membership differs; use a fresh dataset"
        )

    result = store_records(db, model, wanted)
    return result["created"], result["reused"]


def ew_tracks(db, dataset, options, prior_results):
    from app.core.enum import ClassificationEnum
    from app.models.ew_track_models import (
        EWTrack,
        EWTrackEmitter,
        EWTrackPoint,
        EWTrackPointSensor,
    )
    from app.models.mission_models import Mission
    from app.models.sensor_status_models import SensorCatalog

    keys = {
        "track_count",
        "points_per_track",
        "emitters_per_track",
        "sensor_links_per_point",
        "start_at",
        "mission_ids",
        "sensor_ids",
    }

    if options.keys() - keys:
        raise ValueError(f"Unknown EW options: {sorted(options.keys() - keys)}")

    mission_data = prior_results.get("mission_management", {})
    mission_ids = _uuids(
        options.get("mission_ids", mission_data.get("ids", [])),
        "mission_ids",
    )

    if not mission_ids:
        raise ValueError(
            "Supply mission_ids for QA missions or depend on mission_management"
        )

    sensor_ids = _uuids(
        options.get("sensor_ids", mission_data.get("sensor_ids", [])),
        "sensor_ids",
    )

    tracks = _number(options, "track_count", 20, 1)
    points = _number(options, "points_per_track", 5, 1)
    emitters = _number(options, "emitters_per_track", 5, 0)
    links = _number(options, "sensor_links_per_point", 2, 0)

    if len(sensor_ids) < links:
        raise ValueError(f"Provide at least {links} distinct test catalog sensor_ids")

    _check_references(db, Mission, mission_ids)
    _check_references(db, SensorCatalog, sensor_ids)

    namespace = uuid5(NAMESPACE_URL, f"nmdb-qa/ew_tracks/{dataset}")
    source = f"QA-{namespace.hex[:16]}"
    classification = ClassificationEnum.NOT_RESTRICTED

    start = datetime.fromisoformat(
        options.get("start_at", "2024-01-01T00:00:00+00:00")
    )
    if start.utcoffset() is None:
        raise ValueError("EW fixture start_at needs a timezone")
    start = start.astimezone(timezone.utc)

    track_values = [
        dict(
            id=uuid5(namespace, str(i)),
            source_track_id=str(uuid5(namespace, str(i))),
            source_system=source,
            mission_id=mission_ids[i % len(mission_ids)],
            classification=classification,
            platform_instance_id=None,
            platform_instance_name=None,
            platform_class_name=None,
            platform_country_id=None,
            platform_type=None,
        )
        for i in range(tracks)
    ]

    ids = [item["id"] for item in track_values]
    existing_ids = set(
        db.scalars(select(EWTrack.id).where(EWTrack.source_system == source))
    )

    if existing_ids and existing_ids != set(ids):
        raise ValueError(
            "Existing QA dataset has different tracks; use a fresh dataset"
        )

    names = ("tracks", "points", "emitters", "sensor_links")
    created, reused = dict.fromkeys(names, 0), dict.fromkeys(names, 0)

    created["tracks"], reused["tracks"] = _persist_level(
        db,
        EWTrack,
        track_values,
        select(EWTrack).where(EWTrack.source_system == source),
        existing_ids,
    )

    for track_id in ids:
        point_values = [
            dict(
                id=uuid5(track_id, f"point/{i}"),
                track_id=track_id,
                observed_at=start + timedelta(seconds=i),
                lat=0.0,
                lon=0.0,
                error_m=0.0,
                classification=classification,
            )
            for i in range(points)
        ]

        emitter_values = [
            dict(
                id=uuid5(track_id, f"emitter/{i}"),
                track_id=track_id,
                emitter_mode=f"QA-{i}",
                emitter_id_sensor=f"QA-{uuid5(track_id, str(i)).hex[:8]}",
                emitter_name=f"Fixture {i}",
                emitter_country_id="ZZZ",
                first_seen_at=start,
                last_seen_at=start + timedelta(seconds=1),
                emitter_confidence=0.0,
                freq_low_mhz=1.0,
                freq_mid_mhz=2.0,
                freq_high_mhz=3.0,
                pulse_width_low_us=1.0,
                pulse_width_mid_us=2.0,
                pulse_width_high_us=3.0,
                pri_low_us=1.0,
                pri_mid_us=2.0,
                pri_high_us=3.0,
            )
            for i in range(emitters)
        ]

        link_values = [
            dict(
                id=uuid5(point["id"], str(sensor_id)),
                point_id=point["id"],
                sensor_catalog_id=sensor_id,
            )
            for point in point_values
            for sensor_id in sensor_ids[:links]
        ]

        point_ids = [point["id"] for point in point_values]

        levels = (
            (
                "points",
                EWTrackPoint,
                point_values,
                EWTrackPoint.track_id == track_id,
            ),
            (
                "emitters",
                EWTrackEmitter,
                emitter_values,
                EWTrackEmitter.track_id == track_id,
            ),
            (
                "sensor_links",
                EWTrackPointSensor,
                link_values,
                EWTrackPointSensor.point_id.in_(point_ids),
            ),
        )

        for name, model, values, predicate in levels:
            expected = (
                {v["id"] for v in values}
                if track_id in existing_ids
                else set()
            )

            added, found = _persist_level(
                db,
                model,
                values,
                select(model).where(predicate),
                expected,
            )

            created[name] += added
            reused[name] += found

    return {
        "ids": [str(key) for key in ids],
        "created": created,
        "reused": reused,
    }
