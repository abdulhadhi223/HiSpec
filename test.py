"""Validate the sample XML and resolve imported rows for draft text edits."""

from lxml import etree
from sqlalchemy import MetaData, String, Table, select


def nrd(db, dataset, options, prior_results):
    for kind in ("technical", "tactical"):
        paths = options[kind]
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        schema = etree.XMLSchema(etree.parse(paths["xsd"], parser))
        schema.assertValid(etree.parse(paths["xml"], parser))

    cfg = options["nomination_targets"]
    name = cfg["table"]
    if cfg.get("entity_type", name) != name:
        raise ValueError("entity_type must match the NRD table name")
    table = Table(name, MetaData(), schema="public", autoload_with=db.connection(),
                  resolve_fks=False)
    field = table.c[cfg["text_field"]]
    if not isinstance(field.type, String):
        raise ValueError(f"{name}.{field.name} must be a text field for this fixture")
    names = cfg["qa_names"]
    if not isinstance(names, list) or not names or not all(isinstance(n, str) and n.strip() for n in names):
        raise ValueError("qa_names must list existing, nonempty QA display values")
    if len(set(names)) != len(names):
        raise ValueError("Each QA display value must occur once in qa_names")

    query = select(table.c.object_id, field).where(field.in_(names))
    if "to_be_removed" in table.c:
        query = query.where(table.c.to_be_removed.is_not(True))
    if "deleted_at" in table.c:
        query = query.where(table.c.deleted_at.is_(None))

    found = {}
    for object_id, current in db.execute(query):
        if not isinstance(object_id, str) or not object_id.strip() or current in found:
            raise ValueError(f"Expected one row with a nonempty object_id for {current!r}")
        found[current] = object_id
    missing = [value for value in names if value not in found]
    if missing:
        raise ValueError(f"No eligible row in {name}.{field.name} for {missing}")
    if len(set(found.values())) != len(names):
        raise ValueError("Choose distinct NRD objects for the draft proposals")

    return {"validated_documents": ["technical", "tactical"], "qa_edit_targets": [
        {"entity_type": name, "entity_id": found[value],
         "field_name": field.name, "current_text": value}
        for value in names
    ]}

"""Submit one draft EDIT proposal per imported QA target."""
import os
from uuid import NAMESPACE_URL, uuid5

import httpx
from sqlalchemy import select

from .enum_values import resolve_enum


def update_nominations(db, dataset, options, prior_results):
    from app.models.nrd.nrd_update_proposals import ProposedCellEdit as Edit
    from app.models.nrd.nrd_update_proposals import ProposedUpdate as Proposal

    targets = prior_results.get("nrd", {}).get("qa_edit_targets")
    if not targets:
        raise ValueError("The nrd feature must return qa_edit_targets")
    owner = os.environ.get("NMDB_SEED_ACTOR_ID")
    base = os.environ.get("NMDB_API_BASE_URL")
    if not owner or not base:
        raise ValueError("Set NMDB_SEED_ACTOR_ID and NMDB_API_BASE_URL for the QA instance")

    headers = {}
    if username := os.environ.get("NMDB_QA_USERNAME"):
        headers["x-username"] = username
    ids = []
    created = 0
    with httpx.Client(base_url=base.rstrip("/") + "/", headers=headers, timeout=30) as api:
        for target in targets:
            kind, obj, field = (target[k] for k in ("entity_type", "entity_id", "field_name"))
            suffix = uuid5(NAMESPACE_URL, f"{dataset}/{kind}/{obj}/{field}").hex[:12]
            new_value = f"QA-{suffix}"
            if new_value == target["current_text"]:
                raise ValueError(f"Proposed value already equals {kind}.{field} for {obj}")

            edit = {"entity_type": kind, "entity_id": obj, "field_name": field,
                    "delta_type": "EDIT", "proposed_value": new_value,
                    "value_type": "string", "field_label": field}
            query = select(Proposal.id, Proposal.status).join(
                Edit, Edit.proposed_update_id == Proposal.id
            ).where(
                Proposal.original_owner_id == owner, Proposal.is_deleted.is_(False),
                Edit.is_deleted.is_(False), Edit.entity_type == kind, Edit.entity_id == obj,
                Edit.field_name == field, Edit.delta_type == resolve_enum(Edit.delta_type, "EDIT"),
                Edit.proposed_value == new_value,
            )
            saved = db.execute(query).one_or_none()
            if saved is None:
                response = api.post("nrd-updates/proposals", json={
                    "original_owner_id": owner, "initial_edits": [edit],
                })
                if response.status_code not in (201, 409):
                    raise ValueError(f"Proposal for {obj}: HTTP {response.status_code} {response.text}")
                saved = db.execute(query).one_or_none()
                if saved is None:
                    if response.status_code == 409:
                        raise ValueError(f"Proposal conflict for {obj}: {response.text}")
                    raise ValueError(f"API returned 201 but the draft for {obj} is absent in the seeder DB")
                created += int(response.status_code == 201)
            if saved.status != resolve_enum(Proposal.status, "DRAFT"):
                raise ValueError(f"QA proposal {saved.id} has already left DRAFT")
            ids.append(str(saved.id))
    return {"ids": ids, "created": created, "reused": len(ids) - created}
