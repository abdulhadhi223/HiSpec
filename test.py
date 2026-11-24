"""Independent catalog fixtures and append-only sensor status examples."""

from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select

from .records import store_records


def _enum(model, key, raw):
    members = getattr(model, key).property.columns[0].type.enum_class
    for member in members:
        if raw in (member.name, member.value):
            return member
    raise ValueError(f"{key}: choose a mapped enum value from {[m.value for m in members]}")


def sensor_catalog(db, dataset, options, prior_results):
    from app.models.sensor_status_models import SensorCatalog

    if options.keys() - {"count", "sensor_type", "platform"}:
        raise ValueError("Unknown sensor_catalog options")
    count = options.get("count", 2)
    if type(count) is not int or count < 1:
        raise ValueError("count must be a positive integer")

    kind = _enum(SensorCatalog, "sensor_type", options.get("sensor_type"))
    platform = options.get("platform")
    platform_type = instance = None

    if platform is not None:
        if not isinstance(platform, dict) or set(platform) != {
            "platform_type", "platform_instance_id"
        }:
            raise ValueError("platform needs a platform_type and platform_instance_id")
        platform_type = _enum(SensorCatalog, "platform_type", platform["platform_type"])
        instance = platform["platform_instance_id"]
        if not isinstance(instance, str) or not instance.strip():
            raise ValueError("platform_instance_id must be a nonempty string")

    ns = uuid5(NAMESPACE_URL, f"nmdb-qa/catalog/{dataset}")
    ids = [uuid5(ns, str(i)) for i in range(count)]
    existing = {
        s.id: s
        for s in db.scalars(select(SensorCatalog).where(SensorCatalog.id.in_(ids)))
    }

    recipes = []
    for i, key in enumerate(ids):
        sensor = existing.get(key)
        expected_platform = (platform_type, instance)

        if sensor is not None:
            current = (sensor.platform_type, sensor.platform_instance_id)
            if platform is None:
                expected_platform = current
            elif current == (None, None):
                sensor.platform_type, sensor.platform_instance_id = expected_platform
            elif current != expected_platform:
                raise ValueError(
                    f"Catalog fixture {key} already belongs to a different platform"
                )

        recipes.append(dict(
            id=key,
            name=f"QA-{ns.hex[:16]}-{i}",
            model="QA fixture",
            sensor_type=kind,
            manufacturer="QA",
            active=True,
            deleted_at=None,
            platform_type=expected_platform[0],
            platform_instance_id=expected_platform[1],
            metadata_dict=None,
            external_ref=None,
            nrd_entity_id=None,
        ))

    return store_records(db, SensorCatalog, recipes, key="id")


def sensor_status(db, dataset, options, prior_results):
    from app.models.sensor_status_models import SensorCatalog, SensorStatus

    if options.keys() - {"sensor_ids", "created_by", "source", "history", "start_at"}:
        raise ValueError("Unknown sensor_status options")

    raw = options.get("sensor_ids", prior_results.get("sensor_catalog", {}).get("ids"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("Provide test sensor_ids or depend on sensor_catalog")

    ids = [UUID(str(key)) for key in raw]
    if len(set(ids)) != len(ids):
        raise ValueError("Repeated sensor_ids")

    actor = UUID(str(options["created_by"]))
    source = _enum(SensorStatus, "source", options.get("source"))
    history = options.get("history")
    if not isinstance(history, list) or not history:
        raise ValueError("history must contain at least one status value")

    states = [_enum(SensorStatus, "status", item) for item in history]
    start = datetime.fromisoformat(options["start_at"])
    if start.utcoffset() is None:
        raise ValueError("start_at must include a timezone")
    start = start.astimezone(timezone.utc)

    ns = uuid5(NAMESPACE_URL, f"nmdb-qa/status/{dataset}")
    event_ids = []
    created = 0

    for sensor_id in ids:
        sensor = db.get(SensorCatalog, sensor_id)
        if sensor is None or sensor.deleted_at is not None:
            raise ValueError(f"Missing catalog sensor {sensor_id}")

        for ordinal, status in enumerate(states):
            key = uuid5(ns, f"{sensor_id}/{ordinal}")
            when = start + timedelta(seconds=ordinal)
            values = dict(
                sensor_id=sensor_id,
                status=status,
                source=source,
                created_by=actor,
                note="QA fixture",
                latitude=None,
                longitude=None,
            )

            event = db.get(SensorStatus, key)
            if event is None:
                db.add(SensorStatus(id=key, created_at=when, **values))
                created += 1
            else:
                stamp = event.created_at
                if stamp.tzinfo is None and db.get_bind().dialect.name == "sqlite":
                    stamp = stamp.replace(tzinfo=timezone.utc)
                if stamp != when or any(
                    getattr(event, k) != v for k, v in values.items()
                ):
                    raise ValueError(
                        f"Stored status fixture {key} differs from the requested history"
                    )

            event_ids.append(str(key))

    db.flush()
    return {
        "ids": event_ids,
        "created": created,
        "reused": len(event_ids) - created,
    }



"""Freeze samples from this dataset's EW QA fixtures into a report."""

from collections import defaultdict
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select


def activity_reports(db, dataset, options, prior_results):
    from app.core.enum import ClassificationEnum
    from app.models.ew_track_models import (
        ActivityReport,
        ActivityReportInstance,
        ActivityReportMission,
        EWTrack,
        EWTrackPoint,
    )

    if options.keys() - {"submitted_by", "report_key"}:
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
    key = uuid5(ns, f"report/{name}")

    tracks = list(db.scalars(select(EWTrack).where(
        EWTrack.id.in_(ids),
        EWTrack.source_system == f"QA-{ns.hex[:16]}",
    )))
    if len(tracks) != len(ids) or any(t.mission_id is None for t in tracks):
        raise ValueError("Expected a mission for each track in this QA dataset")

    missions = {t.mission_id for t in tracks}
    report = db.get(ActivityReport, key)

    if report is not None:
        stored_tracks = set(db.scalars(
            select(ActivityReportInstance.track_id).where(
                ActivityReportInstance.activity_report_id == key
            )
        ))
        stored_missions = set(db.scalars(
            select(ActivityReportMission.mission_id).where(
                ActivityReportMission.activity_report_id == key
            )
        ))
        if (
            stored_tracks != set(ids)
            or stored_missions != missions
            or report.submitted_by != author
        ):
            raise ValueError(
                "Saved report membership or author differs. Use a fresh report_key."
            )
        return {
            "ids": [str(key)],
            "created": 0,
            "reused": 1,
            "instances": len(ids),
            "mission_links": len(missions),
        }

    by_track = defaultdict(list)
    points = db.scalars(
        select(EWTrackPoint)
        .where(EWTrackPoint.track_id.in_(ids))
        .order_by(EWTrackPoint.track_id, EWTrackPoint.observed_at, EWTrackPoint.id)
    )
    for point in points:
        by_track[point.track_id].append(point)

    if set(by_track) != set(ids):
        raise ValueError("Every included QA track needs at least one sample")

    db.add(ActivityReport(
        id=key,
        name=f"QA-{name}",
        submitted_by=author,
        classification=ClassificationEnum.NOT_RESTRICTED,
        start_at=min(p[0].observed_at for p in by_track.values()),
        end_at=max(p[-1].observed_at for p in by_track.values()),
    ))
    db.flush()

    for t in tracks:
        samples = by_track[t.id]
        first, last = samples[0], samples[-1]

        db.add(ActivityReportInstance(
            id=uuid5(key, str(t.id)),
            activity_report_id=key,
            track_id=t.id,
            first_seen_dtg=first.observed_at,
            last_seen_dtg=last.observed_at,
            last_position_longitude_dd=last.lon,
            last_position_latitude_dd=last.lat,
            last_position_error_m=None if last.error_m is None else round(last.error_m),
            classification=t.classification,
            source_system=t.source_system,
            platform_type=t.platform_type,
            platform_class_name=t.platform_class_name,
            platform_instance_name=t.platform_instance_name,
            platform_instance_id=t.platform_instance_id,
        ))

    for mission_id in missions:
        db.add(ActivityReportMission(
            id=uuid5(key, f"mission/{mission_id}"),
            activity_report_id=key,
            mission_id=mission_id,
        ))

    db.flush()
    return {
        "ids": [str(key)],
        "created": 1,
        "reused": 0,
        "instances": len(ids),
        "mission_links": len(missions),
    }



{
  "dataset": "qa-linked-01",
  "features": {
    "sensor_catalog": {
      "options": {
        "count": 2,
        "sensor_type": "REPLACE_WITH_SENSOR_TYPE",
        "platform": {
          "platform_type": "REPLACE_WITH_ENUM_VALUE",
          "platform_instance_id": "REPLACE_WITH_TEST_INSTANCE_ID"
        }
      }
    },
    "sensor_status": {
      "depends_on": ["sensor_catalog"],
      "options": {
        "created_by": "REPLACE_WITH_TEST_ACTOR_UUID",
        "source": "REPLACE_WITH_STATUS_SOURCE",
        "history": [
          "REPLACE_WITH_FIRST_STATUS",
          "REPLACE_WITH_SECOND_STATUS"
        ],
        "start_at": "2026-01-01T08:00:00+00:00"
      }
    },
    "mission_management": {
      "depends_on": ["sensor_catalog"],
      "options": {
        "count": 5,
        "created_by": "REPLACE_WITH_TEST_ACTOR_UUID",
        "platforms": [
          {
            "platform_type": "REPLACE_WITH_ENUM_VALUE",
            "platform_instance_id": "REPLACE_WITH_TEST_INSTANCE_ID"
          }
        ],
        "mission_fields": {
          "status": "Draft",
          "mission_type": "Training"
        }
      }
    },
    "ew_tracks": {
      "depends_on": ["mission_management"],
      "options": {
        "track_count": 20,
        "points_per_track": 5,
        "emitters_per_track": 5,
        "sensor_links_per_point": 2,
        "start_at": "2026-01-01T08:00:00+00:00"
      }
    },
    "activity_reports": {
      "depends_on": ["ew_tracks"],
      "options": {
        "report_key": "baseline",
        "submitted_by": "qa-seeding"
      }
    }
  }
}



"""Write a per-mission QA XML fixture and a JSON receipt from a saved seed summary."""

import argparse
import hashlib
import json
from pathlib import Path
from uuid import UUID
from xml.etree import ElementTree as ET


def write_files(summary, directory):
    mission_ids = summary["completed"]["mission_management"]["ids"]
    if not mission_ids:
        raise ValueError("No completed mission fixtures")

    for value in mission_ids:
        mission_id = str(UUID(value))
        folder = directory / mission_id
        folder.mkdir(parents=True, exist_ok=True)

        xml = ET.Element(
            "qa-export-fixture",
            {"mission": mission_id, "fixture": "sample-01"},
        )
        body = ET.tostring(xml, encoding="utf-8", xml_declaration=True)
        receipt = {
            "kind": "qa-file-handoff",
            "mission_id": mission_id,
            "source": "sample.xml",
            "sha256": hashlib.sha256(body).hexdigest(),
        }
        outputs = {
            "sample.xml": body,
            "receipt.json": (json.dumps(receipt, indent=2) + "\n").encode(),
        }

        for name, data in outputs.items():
            path = folder / name
            try:
                with path.open("xb") as handle:
                    handle.write(data)
            except FileExistsError:
                if path.read_bytes() != data:
                    raise ValueError(f"Existing fixture differs at {path}")

    return len(mission_ids)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()

    # Windows PowerShell 5.1 redirects stdout as UTF-16 by default.
    count = write_files(json.loads(args.summary.read_bytes()), args.directory)
    print(f"Verified fixture files for {count} missions")


