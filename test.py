from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from typing import Any


FEATURES = frozenset({
    "nrd",
    "update_nominations",
    "sensor_status",
    "mission_management",
    "intercept_correlation",
    "ew_tracks",
    "activity_reports",
    "nec",
})


class SeedError(RuntimeError):
    def __init__(self, feature: str, cause: Exception, report: dict):
        super().__init__(f"{feature}: {cause}")
        self.report = {
            **report,
            "failed": feature,
            "error": str(cause),
        }


def _execution_order(features: dict, selected: list[str]) -> list[str]:
    order: list[str] = []
    active: list[str] = []

    def visit(name: str) -> None:
        if name in order:
            return

        if name in active:
            raise ValueError(
                "Dependency cycle: " + " -> ".join([*active, name])
            )

        if name not in features:
            raise ValueError(
                f"Missing feature configuration for {name!r}"
            )

        settings = features[name]

        if (
            not isinstance(settings, dict)
            or settings.keys() - {"depends_on", "options"}
        ):
            raise ValueError(
                f"{name}: expected a feature object with depends_on/options"
            )

        deps = settings.get("depends_on", [])
        if not isinstance(deps, list) or not all(
            isinstance(key, str) for key in deps
        ):
            raise ValueError(
                f"{name}.depends_on must be a list of feature names"
            )

        if not isinstance(settings.get("options", {}), dict):
            raise ValueError(f"{name}.options must be an object")

        active.append(name)
        for dep in deps:
            visit(dep)
        active.pop()

        order.append(name)

    for name in selected:
        visit(name)

    return order


def run(
    config: dict,
    handlers: dict[str, Callable],
    sessions: dict[str, Callable],
    only: list[str] | None = None,
) -> dict:
    if not isinstance(config, dict):
        raise ValueError("Expected a configuration object")

    dataset = config.get("dataset")
    if not isinstance(dataset, str) or not dataset.strip():
        raise ValueError("A nonempty dataset name is required")

    features = config.get("features")
    if not isinstance(features, dict) or not features:
        raise ValueError("Configure at least one feature")

    unknown = set(features) - FEATURES
    if unknown:
        raise ValueError(f"Unknown feature names: {sorted(unknown)}")

    if only is not None and (
        not isinstance(only, list)
        or not only
        or not all(isinstance(key, str) for key in only)
    ):
        raise ValueError("Feature selection must be a nonempty list of names")

    selected = list(features) if only is None else only
    order = _execution_order(features, selected)
    targets = {
        name: "nec" if name == "nec" else "nmdb"
        for name in order
    }

    missing = [name for name in order if not callable(handlers.get(name))]
    if missing:
        raise ValueError(f"Missing feature handlers: {', '.join(missing)}")

    for target in dict.fromkeys(targets.values()):
        if not callable(sessions.get(target)):
            raise ValueError(f"Missing session factory for {target!r}")

    completed: dict[str, Any] = {}
    report = {"dataset": dataset, "completed": completed}

    for name in order:
        try:
            with sessions[targets[name]]() as db:
                try:
                    result = handlers[name](
                        db,
                        dataset,
                        features[name].get("options", {}),
                        deepcopy(completed),
                    )

                    if not isinstance(result, dict):
                        raise TypeError(
                            "A feature must return a JSON-compatible dictionary"
                        )

                    snapshot = json.loads(
                        json.dumps(result, allow_nan=False)
                    )
                    db.commit()
                    completed[name] = snapshot

                except Exception:
                    db.rollback()
                    raise

        except Exception as exc:
            raise SeedError(name, exc, report) from exc

    return report


import argparse
import importlib
import json
import sys
from pathlib import Path

from .runner import FEATURES, SeedError, run


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed a configured sample dataset"
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--bindings",
        required=True,
        help="Python module exporting HANDLERS and SESSIONS",
    )
    parser.add_argument(
        "--feature",
        choices=sorted(FEATURES),
        action="append",
        help="Select a feature and its prerequisites. Repeat for several.",
    )
    args = parser.parse_args()

    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        bindings = importlib.import_module(args.bindings)

        report = run(
            config,
            bindings.HANDLERS,
            bindings.SESSIONS,
            args.feature,
        )

    except SeedError as exc:
        print(json.dumps(exc.report, indent=2), file=sys.stderr)
        return 1

    except (AttributeError, ImportError, OSError, ValueError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


from datetime import date, datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import select

from .ew_qa import ew_tracks
from .generation import payload

__all__ = ["mission_management", "ew_tracks"]


def _plain(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (UUID, datetime, date)):
        return str(value)
    return value


def _active(query, model):
    deleted_at = getattr(model, "deleted_at", None)
    if deleted_at is not None:
        return query.where(deleted_at.is_(None))
    return query


def _platform_keys(items):
    return {
        (_plain(item.platform_type), str(item.platform_instance_id))
        for item in items
    }


def _test_platforms(db, raw_items, platform_schema, catalog):
    if not isinstance(raw_items, list):
        raise ValueError("platforms must be a list of test platform references")

    items = [platform_schema.model_validate(raw) for raw in raw_items]

    if len(items) != len(_platform_keys(items)):
        raise ValueError("platforms contains duplicate test platform references")

    sensor_ids = set()

    for item in items:
        query = select(catalog.id).where(
            catalog.platform_type == item.platform_type,
            catalog.platform_instance_id == item.platform_instance_id,
        )
        ids = list(db.scalars(_active(query, catalog)))

        if not ids:
            raise ValueError(
                f"No test catalog entries for {item.platform_instance_id!r}"
            )

        sensor_ids.update(map(str, ids))

    return items, sensor_ids


def _check_assignments(
    db,
    mission_id,
    platform_model,
    sensor_model,
    platforms,
    sensors,
):
    platform_query = select(platform_model).where(
        platform_model.mission_id == mission_id
    )
    rows = list(db.scalars(_active(platform_query, platform_model)))

    sensor_query = select(sensor_model.sensor_id).where(
        sensor_model.mission_id == mission_id
    )
    observed = list(
        map(str, db.scalars(_active(sensor_query, sensor_model)))
    )

    if (
        len(rows) != len(platforms)
        or _platform_keys(rows) != _platform_keys(platforms)
        or len(observed) != len(sensors)
        or set(observed) != sensors
    ):
        raise ValueError(
            f"Mission {mission_id} differs from the requested "
            "platform/sensor fixture"
        )


def mission_management(db, dataset, options, prior_results):
    from app.core.enum import ClassificationEnum
    from app.models.mission_models import Mission, MissionPlatform, MissionSensor
    from app.models.sensor_status_models import SensorCatalog
    from app.schemas.mission.mission_schema import (
        MissionCreate,
        PlatformAssignItem,
    )
    from app.services.mission.mission_service import (
        assign_platform_to_mission,
        create_mission,
    )

    supported = {"count", "created_by", "platforms", "mission_fields"}
    unknown = options.keys() - supported
    if unknown:
        raise ValueError(f"Unknown mission options: {sorted(unknown)}")

    count = options.get("count", 1)
    if type(count) is not int or count < 1:
        raise ValueError("count must be a positive integer")

    if not options.get("created_by"):
        raise ValueError("Specify the UUID of the test actor in created_by")

    actor = str(UUID(str(options["created_by"])))
    fields = options.get("mission_fields", {})
    allowed = set(MissionCreate.model_fields) - {"id", "name", "created_by"}

    if not isinstance(fields, dict) or set(fields) - allowed:
        raise ValueError(
            f"mission_fields must contain fields from {sorted(allowed)}"
        )

    base = {
        "mission_type": "Training",
        "status": "Draft",
        "classification": ClassificationEnum.NOT_RESTRICTED,
        **fields,
        "created_by": actor,
    }

    for field, value in (
        ("start_date", "2026-01-01T08:00:00"),
        ("end_date", "2026-01-02T08:00:00"),
    ):
        definition = MissionCreate.model_fields.get(field)
        if definition is not None and definition.is_required():
            base.setdefault(field, value)

    unmapped = set(base) - set(Mission.__mapper__.column_attrs.keys())
    if unmapped:
        raise ValueError(
            f"Configure a mission adapter for unmapped payload fields "
            f"{sorted(unmapped)}"
        )

    platforms, sensor_ids = _test_platforms(
        db,
        options.get("platforms", []),
        PlatformAssignItem,
        SensorCatalog,
    )

    ids = []
    created = 0

    for ordinal in range(1, count + 1):
        name = f"QA-{dataset}-mission-{ordinal:04d}"
        data = payload(MissionCreate, **base, name=name)

        query = select(Mission).where(Mission.name == name)
        mission = db.scalars(query).one_or_none()

        if mission is None:
            mission = create_mission(db, data)
            db.flush()

            if platforms:
                assign_platform_to_mission(
                    db=db,
                    mission_id=mission.id,
                    platforms=platforms,
                )
            db.flush()
            created += 1

        elif mission.deleted_at is not None or any(
            _plain(getattr(mission, attr)) != _plain(getattr(data, attr))
            for attr in base
        ):
            raise ValueError(
                f"Existing mission {name!r} differs from the requested fixture"
            )

        _check_assignments(
            db,
            mission.id,
            MissionPlatform,
            MissionSensor,
            platforms,
            sensor_ids,
        )
        ids.append(str(mission.id))

    return {
        "ids": ids,
        "sensor_ids": sorted(sensor_ids),
        "created": created,
        "reused": count - created,
    }


from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select

from .generation import row


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
            raise ValueError(
                f"Missing active {model.__name__} test fixture {key}"
            )


def _comparable(value):
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _persist_level(db, model, wanted, query, expected_existing):
    existing = {item.id: item for item in db.scalars(query)}

    if set(existing) != expected_existing:
        raise ValueError(
            f"{model.__name__} fixture membership differs; use a fresh dataset"
        )

    for fields in wanted:
        record = existing.get(fields["id"])

        if record is None:
            db.add(row(model, **fields))
        elif any(
            _comparable(getattr(record, key)) != value
            for key, value in fields.items()
        ):
            raise ValueError(
                f"Existing {model.__name__} {record.id} differs from its fixture"
            )

    db.flush()
    return len(wanted) - len(existing), len(existing)


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

    supported = {
        "track_count",
        "points_per_track",
        "emitters_per_track",
        "sensor_links_per_point",
        "mission_ids",
        "sensor_ids",
    }
    unknown = options.keys() - supported
    if unknown:
        raise ValueError(f"Unknown EW options: {sorted(unknown)}")

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
        raise ValueError(
            f"Provide at least {links} distinct test catalog sensor_ids"
        )

    _check_references(db, Mission, mission_ids)
    _check_references(db, SensorCatalog, sensor_ids)

    namespace = uuid5(NAMESPACE_URL, f"nmdb-qa/ew_tracks/{dataset}")
    source = f"QA-{namespace.hex[:16]}"
    classification = ClassificationEnum.NOT_RESTRICTED
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)

    track_values = []
    for i in range(tracks):
        track_id = uuid5(namespace, str(i))
        track_values.append({
            "id": track_id,
            "source_track_id": str(track_id),
            "source_system": source,
            "mission_id": mission_ids[i % len(mission_ids)],
            "classification": classification,
            "platform_instance_id": None,
            "platform_instance_name": None,
            "platform_class_name": None,
            "platform_country_id": None,
            "platform_type": None,
        })

    ids = [item["id"] for item in track_values]

    existing_ids = set(
        db.scalars(
            select(EWTrack.id).where(EWTrack.source_system == source)
        )
    )

    if existing_ids and existing_ids != set(ids):
        raise ValueError(
            "Existing QA dataset has different tracks; use a fresh dataset"
        )

    names = ("tracks", "points", "emitters", "sensor_links")
    created = dict.fromkeys(names, 0)
    reused = dict.fromkeys(names, 0)

    created["tracks"], reused["tracks"] = _persist_level(
        db,
        EWTrack,
        track_values,
        select(EWTrack).where(EWTrack.source_system == source),
        existing_ids,
    )

    for track_id in ids:
        point_values = [
            {
                "id": uuid5(track_id, f"point/{i}"),
                "track_id": track_id,
                "observed_at": start + timedelta(seconds=i),
                "lat": 0.0,
                "lon": 0.0,
                "error_m": 0.0,
                "classification": classification,
            }
            for i in range(points)
        ]

        emitter_values = [
            {
                "id": uuid5(track_id, f"emitter/{i}"),
                "track_id": track_id,
                "emitter_mode": f"QA-{i}",
                "emitter_id_sensor": f"QA-{uuid5(track_id, str(i)).hex[:8]}",
                "emitter_name": f"Fixture {i}",
                "emitter_country_id": "ZZZ",
                "first_seen_at": start,
                "last_seen_at": start + timedelta(seconds=1),
                "emitter_confidence": 0.0,
                "freq_low_mhz": 1.0,
                "freq_mid_mhz": 2.0,
                "freq_high_mhz": 3.0,
                "pulse_width_low_us": 1.0,
                "pulse_width_mid_us": 2.0,
                "pulse_width_high_us": 3.0,
                "pri_low_us": 1.0,
                "pri_mid_us": 2.0,
                "pri_high_us": 3.0,
            }
            for i in range(emitters)
        ]

        link_values = [
            {
                "id": uuid5(point["id"], str(sensor_id)),
                "point_id": point["id"],
                "sensor_catalog_id": sensor_id,
            }
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
                {item["id"] for item in values}
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


from app.core.database import SessionLocal

from nmdb_seed.nmdb_adapters import ew_tracks, mission_management


SESSIONS = {
    "nmdb": SessionLocal,
}

HANDLERS = {
    "mission_management": mission_management,
    "ew_tracks": ew_tracks,
}


from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nmdb_seed.records import store_records


class Main(DeclarativeBase):
    pass


class Cache(DeclarativeBase):
    pass


class Fixture:
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(32))


class Platform(Fixture, Main):
    __tablename__ = "qa_platform"


class Sensor(Fixture, Main):
    __tablename__ = "qa_sensor"

    platform_id: Mapped[str] = mapped_column(
        ForeignKey("qa_platform.id")
    )


class Nomination(Fixture, Main):
    __tablename__ = "qa_nomination"

    reference_id: Mapped[str] = mapped_column(
        ForeignKey("qa_platform.id")
    )
    state: Mapped[str] = mapped_column(String(16))

    __table_args__ = (
        CheckConstraint("state IN ('draft', 'submitted')"),
    )


class Status(Fixture, Main):
    __tablename__ = "qa_sensor_status"

    sensor_id: Mapped[str] = mapped_column(ForeignKey("qa_sensor.id"))
    status: Mapped[str] = mapped_column(String(16))

    __table_args__ = (
        CheckConstraint("status IN ('available', 'offline')"),
    )


class Mission(Fixture, Main):
    __tablename__ = "qa_mission"

    platform_id: Mapped[str] = mapped_column(
        ForeignKey("qa_platform.id")
    )


class Setting(Fixture, Main):
    __tablename__ = "qa_correlation_config"

    enabled: Mapped[bool]


class Track(Fixture, Main):
    __tablename__ = "qa_track"

    mission_id: Mapped[str] = mapped_column(ForeignKey("qa_mission.id"))


class Point(Fixture, Main):
    __tablename__ = "qa_point"

    track_id: Mapped[str] = mapped_column(ForeignKey("qa_track.id"))
    position_index: Mapped[int]

    __table_args__ = (
        UniqueConstraint("track_id", "position_index"),
    )


class Report(Fixture, Main):
    __tablename__ = "qa_report"

    track_id: Mapped[str] = mapped_column(ForeignKey("qa_track.id"))
    mission_id: Mapped[str] = mapped_column(ForeignKey("qa_mission.id"))


class CachedMission(Fixture, Cache):
    __tablename__ = "qa_cache_entry"

    source_mission_id: Mapped[str] = mapped_column(String(36))


def _enforce_foreign_keys(connection, _record):
    connection.execute("PRAGMA foreign_keys=ON")


def init_demo(main_engine, nec_engine):
    for engine, base in ((main_engine, Main), (nec_engine, Cache)):
        if engine.dialect.name != "sqlite":
            raise ValueError("Demo bindings require SQLite")

        if not event.contains(engine, "connect", _enforce_foreign_keys):
            event.listen(engine, "connect", _enforce_foreign_keys)

        with engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            base.metadata.create_all(conn)


def _count(options, name="count"):
    value = options.get(name, 2)
    if type(value) is not int or not 1 <= value <= 1000:
        raise ValueError(f"{name} must be between 1 and 1000")
    return value


def _refs(previous, feature, field="ids"):
    try:
        ids = previous[feature][field]
    except KeyError as exc:
        raise ValueError(f"Declare {feature} as a dependency") from exc

    if not ids:
        raise ValueError(f"{feature} returned no {field}")
    return ids


def _populate(db, dataset, model, recipes):
    def indexed():
        for key, fields in recipes:
            identity = json.dumps(
                [dataset, model.__tablename__, key],
                separators=(",", ":"),
            )
            yield {
                **fields,
                "id": str(uuid5(NAMESPACE_URL, identity)),
                "dataset": dataset,
            }

    return store_records(db, model, indexed(), key="id")


def nrd(db, dataset, options, previous):
    platforms = _populate(
        db,
        dataset,
        Platform,
        ((i, {}) for i in range(_count(options))),
    )

    sensors = _populate(
        db,
        dataset,
        Sensor,
        (
            (platform_id, {"platform_id": platform_id})
            for platform_id in platforms["ids"]
        ),
    )

    return {
        **platforms,
        "sensor_ids": sensors["ids"],
        "sensors_created": sensors["created"],
        "sensors_reused": sensors["reused"],
    }


def _linked_rows(
    model,
    parent,
    field,
    *,
    ids_field="ids",
    variations=None,
):
    def seed(db, dataset, options, previous):
        parents = _refs(previous, parent, ids_field)

        def recipes():
            for i in range(_count(options)):
                values = {field: parents[i % len(parents)]}

                for name, choices in (variations or {}).items():
                    values[name] = choices[i % len(choices)]

                yield i, values

        return _populate(db, dataset, model, recipes())

    return seed


def intercept_correlation(db, dataset, options, previous):
    return _populate(
        db,
        dataset,
        Setting,
        ((i, {"enabled": False}) for i in range(_count(options))),
    )


def ew_tracks(db, dataset, options, previous):
    mission_ids = _refs(previous, "mission_management")

    tracks = _populate(
        db,
        dataset,
        Track,
        (
            (i, {"mission_id": mission_ids[i % len(mission_ids)]})
            for i in range(_count(options))
        ),
    )

    depth = _count(options, "points_per_track")
    points = _populate(
        db,
        dataset,
        Point,
        (
            (
                [track_id, i],
                {"track_id": track_id, "position_index": i},
            )
            for track_id in tracks["ids"]
            for i in range(depth)
        ),
    )

    return {
        **tracks,
        "points_created": points["created"],
        "points_reused": points["reused"],
    }


def activity_reports(db, dataset, options, previous):
    tracks = _refs(previous, "ew_tracks")
    missions = set(_refs(previous, "mission_management"))

    def recipes():
        for i in range(_count(options)):
            track = db.get(Track, tracks[i % len(tracks)])

            if (
                track is None
                or track.dataset != dataset
                or track.mission_id not in missions
            ):
                raise ValueError(
                    "Report references a track outside the selected missions"
                )

            yield i, {
                "track_id": track.id,
                "mission_id": track.mission_id,
            }

    return _populate(db, dataset, Report, recipes())


EXTRA_HANDLERS = {
    "nrd": nrd,
    "update_nominations": _linked_rows(
        Nomination,
        "nrd",
        "reference_id",
        variations={"state": ("draft", "submitted")},
    ),
    "sensor_status": _linked_rows(
        Status,
        "nrd",
        "sensor_id",
        ids_field="sensor_ids",
        variations={"status": ("available", "offline")},
    ),
    "intercept_correlation": intercept_correlation,
    "activity_reports": activity_reports,
    "nec": _linked_rows(
        CachedMission,
        "mission_management",
        "source_mission_id",
    ),
}

HANDLERS = {
    **EXTRA_HANDLERS,
    "mission_management": _linked_rows(
        Mission,
        "nrd",
        "platform_id",
    ),
    "ew_tracks": ew_tracks,
}
