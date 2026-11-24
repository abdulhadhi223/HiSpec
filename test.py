"""Run selected sample-data features with their declared prerequisites."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from copy import deepcopy
from typing import Any

FEATURES = frozenset({
    "nrd", "update_nominations", "sensor_catalog", "sensor_status", "mission_management",
    "intercept_correlation", "ew_tracks", "activity_reports", "nec",
})


class SeedError(RuntimeError):
    """A feature failed. Completed features are recorded in report."""

    def __init__(self, feature: str, cause: Exception, report: dict):
        super().__init__(f"{feature}: {cause}")
        self.report = {**report, "failed": feature, "error": str(cause)}


# Defaults for linked QA runs that declare one shared platform.
_LINKED_PARENT = {
    "sensor_status": "sensor_catalog",
    "mission_management": "sensor_catalog",
    "ew_tracks": "mission_management",
    "activity_reports": "ew_tracks",
}


def _execution_order(features: dict, selected: list[str], linked: bool = False) -> list[str]:
    order: list[str] = []
    active: list[str] = []

    def visit(name: str) -> None:
        if name in order:
            return
        if name in active:
            raise ValueError("Dependency cycle: " + " -> ".join([*active, name]))
        if name not in features:
            raise ValueError(f"Missing feature configuration for {name!r}")
        settings = features[name]
        if not isinstance(settings, dict) or settings.keys() - {"depends_on", "options"}:
            raise ValueError(f"{name}: expected a feature object with depends_on/options")
        parent = _LINKED_PARENT.get(name) if linked else None
        deps = settings.get("depends_on", [parent] if parent else [])
        if not isinstance(deps, list) or not all(isinstance(key, str) for key in deps):
            raise ValueError(f"{name}.depends_on must be a list of feature names")
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
    config: dict, handlers: dict[str, Callable], sessions: dict[str, Callable],
    only: list[str] | None = None,
) -> dict:
    """Each callback gets (session, dataset, options, previously committed results)."""
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
    if only is not None and (not isinstance(only, list) or not only
                             or not all(isinstance(k, str) for k in only)):
        raise ValueError("Feature selection must be a nonempty list of names")
    platform = config.get("platform")
    if "platform" in config and (
        not isinstance(platform, dict)
        or platform.keys() != {"platform_type", "platform_instance_id"}
        or not all(isinstance(v, str) and v.strip() for v in platform.values())
    ):
        raise ValueError("platform requires platform_type and platform_instance_id")
    order = _execution_order(features, list(features) if only is None else only, platform is not None)
    targets = {name: "nec" if name == "nec" else "nmdb" for name in order}
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
                    options = deepcopy(features[name].get("options", {}))
                    if platform is not None and name in {"sensor_catalog", "mission_management"}:
                        field, value = ("platform", platform) if name == "sensor_catalog" else ("platforms", [platform])
                        if field in options and options[field] != value:
                            raise ValueError(f"{name}.{field} conflicts with the shared platform")
                        options[field] = deepcopy(value)
                    if name in {"sensor_status", "mission_management"} and "created_by" not in options:
                        actor = os.environ.get("NMDB_SEED_ACTOR_ID")
                        if not actor:
                            raise ValueError("Set NMDB_SEED_ACTOR_ID to the QA user's UUID")
                        options["created_by"] = actor
                    result = handlers[name](db, dataset, options, deepcopy(completed))
                    if not isinstance(result, dict):
                        raise TypeError("A feature must return a JSON-compatible dictionary")
                    # Capture plain data before commit can expire ORM objects.
                    snapshot = json.loads(json.dumps(result, allow_nan=False))
                    db.commit()
                    completed[name] = snapshot
                except Exception:
                    db.rollback()
                    raise
        except Exception as exc:
            raise SeedError(name, exc, report) from exc
    return report
