"""Select values for synthetic fixtures from a mapped Python enum."""
from itertools import cycle, repeat
from uuid import uuid5


def resolve_enum(column, value):
    members = column.property.columns[0].type.enum_class
    for member in members:
        if value in (member.name, member.value):
            return member
    raise ValueError(f"{column.key}: choose from {[m.value for m in members]}")


def enum_cycle(column, namespace, override=None):
    """Visit every member in a repeatable, dataset-specific order."""
    if override is not None:
        return repeat(resolve_enum(column, override))
    members = column.property.columns[0].type.enum_class
    return cycle(sorted(members, key=lambda m: uuid5(namespace, f"{column.key}/{m.name}")))


"""QA recipes for independent catalog sensors and their status history."""
from datetime import timedelta, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select

from .enum_values import enum_cycle, resolve_enum
from .records import store_records


class Options(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Platform(Options):
    platform_type: str
    platform_instance_id: str = Field(min_length=1, pattern=r"\S")


class CatalogOptions(Options):
    count: int = Field(default=2, gt=0, strict=True)
    sensor_type: str | None = None
    platform: Platform | None = None


class StatusOptions(Options):
    sensor_ids: list[UUID] = Field(default_factory=list)
    created_by: UUID
    source: str | None = None
    history: list[str] | None = Field(default=None, min_length=1)
    start_at: AwareDatetime


def sensor_catalog(db, dataset, options, prior_results):
    from app.models.sensor_status_models import SensorCatalog

    cfg = CatalogOptions.model_validate(options)
    ns = uuid5(NAMESPACE_URL, f"nmdb-qa/catalog/{dataset}")
    kinds = enum_cycle(SensorCatalog.sensor_type, ns, cfg.sensor_type)
    ids = [uuid5(ns, str(i)) for i in range(cfg.count)]
    recipes = [
        dict(id=key, name=f"QA-{ns.hex[:16]}-{i}", model="QA fixture", sensor_type=next(kinds),
             manufacturer="QA", active=True, deleted_at=None, metadata_dict=None,
             external_ref=None, nrd_entity_id=None)
        for i, key in enumerate(ids)
    ]
    result = store_records(db, SensorCatalog, recipes,
                           create_only={"platform_type": None, "platform_instance_id": None})
    if cfg.platform:
        target = (resolve_enum(SensorCatalog.platform_type, cfg.platform.platform_type),
                  cfg.platform.platform_instance_id)
        sensors = select(SensorCatalog).where(SensorCatalog.id.in_(ids)).order_by(SensorCatalog.id)
        for sensor in db.scalars(sensors.with_for_update().execution_options(populate_existing=True)):
            current = (sensor.platform_type, sensor.platform_instance_id)
            if current == (None, None):
                sensor.platform_type, sensor.platform_instance_id = target
            elif current != target:
                raise ValueError(f"Catalog fixture {sensor.id} already belongs to a different platform")
        db.flush()
    return result


def sensor_status(db, dataset, options, prior_results):
    from app.models.sensor_status_models import SensorCatalog, SensorStatus

    defaults = {"sensor_ids": prior_results.get("sensor_catalog", {}).get("ids", [])}
    cfg = StatusOptions.model_validate({**defaults, **options})
    ids = cfg.sensor_ids
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("Supply distinct test sensor_ids or depend on sensor_catalog")
    available = select(SensorCatalog.id).where(SensorCatalog.id.in_(ids), SensorCatalog.deleted_at.is_(None))
    missing = set(ids) - set(db.scalars(available))
    if missing:
        raise ValueError(f"Missing catalog sensors: {sorted(map(str, missing))}")

    ns = uuid5(NAMESPACE_URL, f"nmdb-qa/status/{dataset}")
    start = cfg.start_at.astimezone(timezone.utc)
    sources = enum_cycle(SensorStatus.source, ns, cfg.source)
    if cfg.history is None:
        states = sorted(SensorStatus.status.property.columns[0].type.enum_class, key=lambda state: state.name)
    else:
        states = [resolve_enum(SensorStatus.status, state) for state in cfg.history]
    recipes = (
        dict(id=uuid5(ns, f"{sensor_id}/{i}"), sensor_id=sensor_id, status=states[(i + ordinal) % len(states)] if cfg.history is None else states[i], source=next(sources),
             created_by=cfg.created_by, created_at=start + timedelta(seconds=i),
             note="QA fixture", latitude=None, longitude=None)
        for ordinal, sensor_id in enumerate(ids)
        for i in range(len(states))
    )
    return store_records(db, SensorStatus, recipes)


{
  "dataset": "qa-newsc-557-02",
  "platform": {
    "platform_type": "REPLACE_WITH_ENUM_VALUE",
    "platform_instance_id": "REPLACE_WITH_TEST_INSTANCE_ID"
  },
  "features": {
    "sensor_catalog": {
      "options": {
        "count": 4
      }
    },
    "sensor_status": {
      "options": {
        "start_at": "2026-01-01T08:00:00+00:00"
      }
    },
    "mission_management": {
      "options": {
        "count": 5,
        "mission_fields": {
          "status": "Draft",
          "mission_type": "Training"
        }
      }
    },
    "ew_tracks": {
      "options": {
        "track_count": 10,
        "points_per_track": 10,
        "emitters_per_track": 2,
        "sensor_links_per_point": 2,
        "start_at": "2026-01-01T08:00:00+00:00",
        "vary_sensor_links": true
      }
    },
    "activity_reports": {
      "options": {
        "report_key": "baseline",
        "submitted_by": "qa-seeding",
        "count": 10,
        "tracks_per_report": 3,
        "mission_linked_reports": 8
      }
    }
  }
}


{
  "dataset": "qa-linked-02",
  "platform": {
    "platform_type": "REPLACE_WITH_ENUM_VALUE",
    "platform_instance_id": "REPLACE_WITH_TEST_INSTANCE_ID"
  },
  "features": {
    "sensor_catalog": {
      "options": {
        "count": 2
      }
    },
    "sensor_status": {
      "options": {
        "start_at": "2026-01-01T08:00:00+00:00"
      }
    },
    "mission_management": {
      "options": {
        "count": 5,
        "mission_fields": {
          "status": "Draft",
          "mission_type": "Training"
        }
      }
    },
    "ew_tracks": {
      "options": {
        "track_count": 20,
        "points_per_track": 5,
        "emitters_per_track": 5,
        "sensor_links_per_point": 2,
        "start_at": "2026-01-01T08:00:00+00:00"
      }
    },
    "activity_reports": {
      "options": {
        "report_key": "baseline",
        "submitted_by": "qa-seeding"
      }
    }
  }
}


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
        "vary_sensor_links",
        "start_at",
        "mission_ids",
        "sensor_ids",
    }
    if options.keys() - keys:
        raise ValueError(f"Unknown EW options: {sorted(options.keys() - keys)}")
    mission_data = prior_results.get("mission_management", {})
    mission_ids = _uuids(
        options.get("mission_ids", mission_data.get("ids", [])), "mission_ids"
    )
    if not mission_ids:
        raise ValueError(
            "Supply mission_ids for QA missions or depend on mission_management"
        )
    sensor_ids = _uuids(
        options.get("sensor_ids", mission_data.get("sensor_ids", [])), "sensor_ids"
    )
    tracks = _number(options, "track_count", 20, 1)
    points = _number(options, "points_per_track", 5, 1)
    emitters = _number(options, "emitters_per_track", 5, 0)
    links = _number(options, "sensor_links_per_point", 2, 0)
    vary_links = options.get("vary_sensor_links", False)
    if type(vary_links) is not bool:
        raise ValueError("vary_sensor_links must be true or false")
    if vary_links:
        sensor_ids.sort()
    if len(sensor_ids) < links:
        raise ValueError(f"Provide at least {links} distinct test catalog sensor_ids")
    _check_references(db, Mission, mission_ids)
    _check_references(db, SensorCatalog, sensor_ids)

    namespace = uuid5(NAMESPACE_URL, f"nmdb-qa/ew_tracks/{dataset}")
    source = f"QA-{namespace.hex[:16]}"
    classification = ClassificationEnum.NOT_RESTRICTED
    start = datetime.fromisoformat(options.get("start_at", "2024-01-01T00:00:00+00:00"))
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
        def sensors_for_point(index):
            if vary_links:
                return [sensor_ids[(index + slot) % len(sensor_ids)] for slot in range(links)]
            return sensor_ids[:links]

        link_values = [
            dict(
                id=uuid5(point["id"], str(sensor_id)),
                point_id=point["id"],
                sensor_catalog_id=sensor_id,
            )
            for index, point in enumerate(point_values)
            for sensor_id in sensors_for_point(index)
        ]
        point_ids = [point["id"] for point in point_values]
        levels = (
            ("points", EWTrackPoint, point_values, EWTrackPoint.track_id == track_id),
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
            expected = {v["id"] for v in values} if track_id in existing_ids else set()
            added, found = _persist_level(
                db, model, values, select(model).where(predicate), expected
            )
            created[name] += added
            reused[name] += found
    return {"ids": [str(key) for key in ids], "created": created, "reused": 



    """Freeze samples from this dataset's EW QA fixtures into a report."""

from collections import defaultdict
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select


def activity_reports(db, dataset, options, prior_results):
    if options.keys() - {"submitted_by", "report_key", "count", "tracks_per_report", "mission_linked_reports"}:
        raise ValueError("Unknown activity_reports options")
    author = options.get("submitted_by")
    if not isinstance(author, str) or not author.strip() or len(author) > 255:
        raise ValueError("submitted_by must contain 1 to 255 characters")
    name = options.get("report_key", "baseline")
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise ValueError("report_key must contain 1 to 100 characters")
    ids = [UUID(key) for key in prior_results.get("ew_tracks", {}).get("ids", [])]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("activity_reports requires distinct IDs from ew_tracks")
    ns = uuid5(NAMESPACE_URL, f"nmdb-qa/ew_tracks/{dataset}")
    count = options.get("count", 1)
    width = options.get("tracks_per_report", len(ids))
    linked = options.get("mission_linked_reports", count)
    if type(count) is not int or count < 1:
        raise ValueError("count must be a positive integer")
    if type(width) is not int or not 1 <= width <= len(ids):
        raise ValueError("tracks_per_report must be between 1 and the available track count")
    if type(linked) is not int or not 0 <= linked <= count:
        raise ValueError("mission_linked_reports must be between zero and count")

    report_ids = []
    created = instances = mission_links = 0
    for index in range(count):
        selected = [ids[(index + offset) % len(ids)] for offset in range(width)]
        # Preserve the existing single-report identifier for legacy configurations.
        if count == 1:
            key = uuid5(ns, f"report/{name}")
            label = name
        else:
            key = uuid5(ns, f"report-set/{name}/{index}")
            label = f"{name}-{index + 1:02d}"
        added, links = _store_snapshot(db, key, label, author, selected, ns, index < linked)
        report_ids.append(str(key))
        created += added
        instances += len(selected)
        mission_links += links
    return {"ids": report_ids, "created": created, "reused": count - created,
            "instances": instances, "mission_links": mission_links}


def _store_snapshot(db, key, name, author, ids, ns, link_missions):
    from app.core.enum import ClassificationEnum
    from app.models.ew_track_models import (
        ActivityReport, ActivityReportInstance, ActivityReportMission, EWTrack, EWTrackPoint,
    )

    tracks = list(db.scalars(select(EWTrack).where(
        EWTrack.id.in_(ids), EWTrack.source_system == f"QA-{ns.hex[:16]}",
    )))
    if len(tracks) != len(ids) or any(t.mission_id is None for t in tracks):
        raise ValueError("Expected a mission for each track in this QA dataset")
    missions = {t.mission_id for t in tracks} if link_missions else set()
    report = db.get(ActivityReport, key)
    if report is not None:
        stored_tracks = set(db.scalars(select(ActivityReportInstance.track_id).where(
            ActivityReportInstance.activity_report_id == key)))
        stored_missions = set(db.scalars(select(ActivityReportMission.mission_id).where(
            ActivityReportMission.activity_report_id == key)))
        if stored_tracks != set(ids) or stored_missions != missions or report.submitted_by != author:
            raise ValueError("Saved report membership or author differs. Use a fresh report_key.")
        return 0, len(missions)

    by_track = defaultdict(list)
    points = db.scalars(select(EWTrackPoint).where(EWTrackPoint.track_id.in_(ids)).order_by(
        EWTrackPoint.track_id, EWTrackPoint.observed_at, EWTrackPoint.id))
    for point in points:
        by_track[point.track_id].append(point)
    if set(by_track) != set(ids):
        raise ValueError("Every included QA track needs at least one sample")
    db.add(ActivityReport(id=key, name=f"QA-{name}", submitted_by=author,
                          classification=ClassificationEnum.NOT_RESTRICTED,
                          start_at=min(p[0].observed_at for p in by_track.values()),
                          end_at=max(p[-1].observed_at for p in by_track.values())))
    db.flush()
    for t in tracks:
        samples = by_track[t.id]
        first, last = samples[0], samples[-1]
        db.add(ActivityReportInstance(
            id=uuid5(key, str(t.id)), activity_report_id=key, track_id=t.id,
            first_seen_dtg=first.observed_at, last_seen_dtg=last.observed_at,
            last_position_longitude_dd=last.lon, last_position_latitude_dd=last.lat,
            last_position_error_m=None if last.error_m is None else round(last.error_m),
            classification=t.classification, source_system=t.source_system,
            platform_type=t.platform_type, platform_class_name=t.platform_class_name,
            platform_instance_name=t.platform_instance_name, platform_instance_id=t.platform_instance_id,
        ))
    for mission_id in missions:
        db.add(ActivityReportMission(id=uuid5(key, f"mission/{mission_id}"),
                                     activity_report_id=key, mission_id=mission_id))
    db.flush()
    return 1, len(missions)
