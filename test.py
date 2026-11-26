    names = cfg.get("qa_names")
    query = select(table.c.object_id, field)

    if names is None:
        # Count mode: discover existing rows belonging to this QA fixture.
        prefix = cfg.get("qa_prefix", "QA-557-")
        if not isinstance(prefix, str) or not prefix.strip():
            raise ValueError("qa_prefix must be a nonempty string")
        query = query.where(field.startswith(prefix, autoescape=True))
    else:
        # Existing configs can still select specific QA names.
        if not isinstance(names, list) or not names:
            raise ValueError("qa_names must be a nonempty list")
        if not all(isinstance(value, str) and value.strip() for value in names):
            raise ValueError("Each qa_names entry must be a nonempty string")
        if len(set(names)) != len(names):
            raise ValueError("qa_names contains duplicates")
        query = query.where(field.in_(names))

    if "to_be_removed" in table.c:
        removed = func.lower(table.c.to_be_removed.cast(String))
        query = query.where(func.coalesce(removed, "false") == "false")
    if "deleted_at" in table.c:
        query = query.where(table.c.deleted_at.is_(None))

    targets = []
    seen_ids = set()
    seen_names = set()
    for object_id, current in db.execute(query.order_by(table.c.object_id)):
        if not isinstance(object_id, str) or not object_id.strip():
            raise ValueError(f"Missing object_id for {current!r}")
        if object_id in seen_ids:
            raise ValueError(f"Multiple eligible rows have object_id {object_id!r}")
        if names is not None and current in seen_names:
            raise ValueError(f"Multiple eligible rows match QA name {current!r}")
        seen_ids.add(object_id)
        seen_names.add(current)
        targets.append({
            "entity_type": name,
            "entity_id": object_id,
            "field_name": field.name,
            "current_text": current,
        })

    if names is not None:
        missing = [value for value in names if value not in seen_names]
        if missing:
            raise ValueError(f"No eligible row in {name}.{field.name} for {missing}")
        positions = {value: index for index, value in enumerate(names)}
        targets.sort(key=lambda target: positions[target["current_text"]])

    return {
        "validated_documents": ["technical", "tactical"],
        "qa_edit_targets": targets,
    }



    targets = prior_results.get("nrd", {}).get("qa_edit_targets")
    if targets is None:
        raise ValueError("The nrd feature must return qa_edit_targets")

    count = options.get("count", len(targets))
    if type(count) is not int or count < 1:
        raise ValueError("update_nominations.options.count must be a positive integer")

    if len(targets) < count:
        raise ValueError(
            f"Requested {count} draft proposals, found {len(targets)} matching "
            f"QA objects, shortfall {count - len(targets)}. No proposals submitted."
        )

    targets = targets[:count]
