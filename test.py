"""Validate NRD QA documents and resolve existing imported nomination targets."""

from collections import Counter
from pathlib import Path

from lxml import etree
from sqlalchemy import MetaData, Table, select


def validate_document(xml_path, xsd_path):
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    schema = etree.XMLSchema(etree.parse(str(Path(xsd_path)), parser))
    document = etree.parse(str(Path(xml_path)), parser)
    schema.assertValid(document)


def nrd(db, dataset, options, prior_results):
    for kind in ("technical", "tactical"):
        document = options[kind]
        try:
            validate_document(document["xml"], document["xsd"])
        except (OSError, etree.LxmlError) as exc:
            raise ValueError(f"{kind} XML/XSD validation failed: {exc}") from exc

    target = options["nomination_targets"]
    names = target["qa_names"]
    if (
        not isinstance(names, list)
        or len(names) != 3
        or not all(isinstance(name, str) and name.strip() for name in names)
        or len(set(names)) != 3
    ):
        raise ValueError("Provide three distinct QA display names")

    table = Table(
        target["table"],
        MetaData(),
        schema=target.get("schema"),
        autoload_with=db.connection(),
    )
    primary_key = list(table.primary_key.columns)
    if len(primary_key) != 1:
        raise ValueError(f"{table.fullname}: expected a single-column primary key")

    field_name = target["text_field"]
    if field_name not in table.c:
        raise ValueError(f"{table.fullname}: unknown text field {field_name!r}")

    text_column = table.c[field_name]
    query = select(primary_key[0], text_column).where(text_column.in_(names))
    if "deleted_at" in table.c:
        query = query.where(table.c.deleted_at.is_(None))

    rows = db.execute(query).all()
    counts = Counter(value for _, value in rows)
    ambiguous = [name for name in names if counts[name] != 1]
    if ambiguous:
        raise ValueError(
            f"Expected exactly one imported QA row per name in "
            f"{table.fullname}.{field_name}. Check {ambiguous}"
        )

    return {
        "validated_documents": ["technical", "tactical"],
        "qa_edit_targets": [
            {
                "entity_type": target["entity_type"],
                "entity_id": str(row_id),
                "field_name": field_name,
                "current_text": value,
            }
            for row_id, value in rows
        ],
    }


"""Seed administrative proposal examples against imported QA text fields."""

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from .enum_values import resolve_enum


def _ensure(db, model, row_id, **values):
    existing = db.get(model, row_id)
    if existing is None:
        db.add(model(id=row_id, **values))
        db.flush()
        return 1

    for field, expected in values.items():
        if getattr(existing, field) != expected:
            raise ValueError(f"Saved {model.__name__} {row_id} differs at {field}")
    return 0


def update_nominations(db, dataset, options, prior_results):
    from app.models.nrd.nrd_update_proposals import (
        EntityLock,
        ProposedCellEdit,
        ProposedUpdate,
    )

    if options:
        raise ValueError("Nomination samples use QA edit targets returned by nrd")

    targets = prior_results.get("nrd", {}).get("qa_edit_targets", [])
    required = ("entity_type", "entity_id", "field_name", "current_text")
    if not isinstance(targets, list) or len(targets) < 3:
        raise ValueError(
            "NRD must return three distinct imported QA entities "
            "with editable text fields"
        )

    for item in targets:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(k), str) for k in required
        ):
            raise ValueError(f"Each QA edit target needs string values for {required}")
        if not all(item[k].strip() for k in required[:3]):
            raise ValueError("Empty QA edit target identity")

    ordered = sorted(targets, key=lambda t: tuple(t[k] for k in required[:3]))
    if len({(t["entity_type"], t["entity_id"]) for t in ordered}) != len(ordered):
        raise ValueError("Supply one QA text field per distinct imported entity")

    namespace = uuid5(NAMESPACE_URL, f"nmdb-qa/nominations/{dataset}")
    when = datetime(2026, 1, 1, 8, tzinfo=timezone.utc)
    edit = resolve_enum(ProposedCellEdit.delta_type, "EDIT")
    ids = []
    represented = set()
    created = 0

    scenarios = ("DRAFT", "DRAFT", "REJECTED")
    for index, (target, state) in enumerate(zip(ordered[:3], scenarios, strict=True)):
        kind, entity, field, current = (target[k] for k in required)
        key = uuid5(namespace, str(index))
        owner = f"qa-author-{index % 2 + 1}"
        locked = state == "DRAFT"
        dirty = index == 1
        status = resolve_enum(ProposedUpdate.status, state)

        created += _ensure(
            db, ProposedUpdate, key,
            original_owner_id=owner,
            locked_to=owner if locked else None,
            status=status,
            is_dirty=dirty,
            dirty_since=when if dirty else None,
            is_deleted=False,
            reviewed_by=None if locked else "qa-reviewer",
            submitted_at=None if locked else when,
            rejected_at=None if locked else when,
        )

        original = current + " (previous QA value)" if dirty else current
        _ensure(
            db, ProposedCellEdit, uuid5(key, "edit"),
            proposed_update_id=key,
            entity_type=kind,
            entity_id=entity,
            field_name=field,
            delta_type=edit,
            original_value=original,
            proposed_value=current + " (QA edit)",
            extract_current_value=current if dirty else None,
            relation_data=None,
            is_dirty=dirty,
            dirty_since=when if dirty else None,
            is_deleted=False,
        )

        lock_id = uuid5(key, "lock")
        if locked:
            _ensure(
                db, EntityLock, lock_id,
                entity_type=kind,
                entity_id=entity,
                proposed_update_id=key,
            )

        expected_locks = {lock_id} if locked else set()
        actual_locks = set(
            db.scalars(
                select(EntityLock.id).where(EntityLock.proposed_update_id == key)
            )
        )
        if actual_locks != expected_locks:
            raise ValueError(f"Unexpected locks on sample proposal {key}")

        represented.add(status)
        ids.append(str(key))

    all_states = set(ProposedUpdate.status.property.columns[0].type.enum_class)
    return {
        "ids": ids,
        "created": created,
        "reused": len(ids) - created,
        "missing_states": sorted(s.name for s in all_states - represented),
        "checks": {
            "states": represented == all_states,
            "locks": True,
            "multiple_users": True,
            "dirty_proposal": True,
        },
    }


"""Register inert mission artifact samples for NMDB QA screens."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID, uuid5


def _member(column, label):
    members = column.property.columns[0].type.enum_class
    for member in members:
        if label in (member.name, member.value):
            return member
    raise ValueError(f"{column.key}: choose one of {[m.name for m in members]}")


def _write_sample(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temp = NamedTemporaryFile(dir=path.parent, delete=False)
        temp_path = Path(temp.name)
        try:
            with temp:
                temp.write(content)
            os.link(temp_path, path)
        except FileExistsError:
            pass
        finally:
            temp_path.unlink(missing_ok=True)
    if path.read_bytes() != content:
        raise ValueError(f"Existing QA file has different content: {path}")


def _register(db, model, mission_id, file_type, path, content, now, **extra):
    key = uuid5(mission_id, f"nmdb-qa/artifacts/v1/{model.__tablename__}")
    fields = dict(mission_id=mission_id, file_type=file_type, file_path=str(path), **extra)
    item = db.get(model, key)
    if item is not None:
        if any(getattr(item, field) != value for field, value in fields.items()):
            raise ValueError(f"QA artifact metadata differs for {key}")
        if item.purged_at is not None or item.expires_at <= now:
            raise ValueError(f"QA artifact {key} has been purged or expired")
    _write_sample(path, content)
    if item is None:
        db.add(model(id=key, **fields, generated_at=now,
                     expires_at=now + timedelta(days=30), download_url=None))
    return "created" if item is None else "reused"


def with_qa_artifacts(mission_handler):
    def run(db, dataset, options, prior_results):
        options = dict(options)
        config = options.pop("qa_artifacts", None)
        if config is None:
            return mission_handler(db, dataset, options, prior_results)

        from app.models.mission_models import SensorProgrammingFile, ThreatExport

        root = Path(config["directory"]).resolve()
        export_type = _member(ThreatExport.file_type, config["export_file_type"])
        mdf_type = _member(SensorProgrammingFile.file_type, "MDF")
        result = mission_handler(db, dataset, options, prior_results)
        counts = {key: {"created": 0, "reused": 0} for key in ("export", "mdf_sample")}
        now = datetime.now(timezone.utc)

        for value in result["ids"]:
            mission_id = UUID(str(value))
            folder = root / str(mission_id)
            xml_path = folder / "qa-export-sample.xml"
            xml = f'<qa-sample mission="{mission_id}" purpose="listing-test"/>\n'.encode()
            state = _register(db, ThreatExport, mission_id, export_type, xml_path, xml, now)
            counts["export"][state] += 1

            state = _register(
                db, SensorProgrammingFile, mission_id, mdf_type,
                folder / "qa-placeholder.mdf", b"QA SAMPLE ONLY - no programming data\n",
                now, source_filename=xml_path.name,
            )
            counts["mdf_sample"][state] += 1

        db.flush()
        result["qa_artifact_fixtures"] = counts
        return result

    return run
