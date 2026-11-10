
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.nrd.nrd_export_state import NrdExportState
from app.services.nrd.export_file_service import (
    get_export_path,
    publish_export_candidate,
    write_export_candidate,
)
from app.services.nrd.export_service import ExportService


ExportType = Literal["technical", "tactical"]

EXPORT_LOCK_KEYS = {
    "technical": 704001,
    "tactical": 704002,
}

MAX_EXPORT_ATTEMPTS = 3


def get_exported_revision(
    state: NrdExportState,
    export_type: ExportType,
) -> int:
    if export_type == "technical":
        return state.technical_exported_revision
    return state.tactical_exported_revision


def set_exported_revision(
    state: NrdExportState,
    export_type: ExportType,
    revision: int,
) -> None:
    if export_type == "technical":
        state.technical_exported_revision = revision
    else:
        state.tactical_exported_revision = revision


def is_export_current(
    db: Session,
    export_type: ExportType,
) -> bool:
    state = db.get(NrdExportState, 1)
    file_path = get_export_path(export_type)

    if state is None or not file_path.is_file():
        return False

    return (
        state.data_revision
        == get_exported_revision(state, export_type)
    )


def generate_snapshot_xml(
    engine: Engine,
    export_type: ExportType,
) -> tuple[int, str]:
    """Read revision and XML data from one PostgreSQL snapshot."""

    snapshot_engine = engine.execution_options(
        isolation_level="REPEATABLE READ"
    )

    with Session(snapshot_engine) as snapshot_db:
        with snapshot_db.begin():
            state = snapshot_db.get(NrdExportState, 1)

            if state is None:
                raise RuntimeError("NRD export state is missing")

            revision = state.data_revision

            xml_data = ExportService().export_all(
                snapshot_db,
                export_type,
            )

            return revision, xml_data


def publish_if_current(
    engine: Engine,
    export_type: ExportType,
    revision: int,
    candidate_path: Path,
) -> bool:
    """Check the latest revision while locking the state row."""

    with Session(engine) as db:
        with db.begin():
            state = db.execute(
                select(NrdExportState)
                .where(NrdExportState.id == 1)
                .with_for_update()
            ).scalar_one()

            if state.data_revision != revision:
                return False

            # Invalidate metadata before filesystem replacement.
            set_exported_revision(
                state,
                export_type,
                -1,
            )
            db.flush()

            publish_export_candidate(
                candidate_path,
                export_type,
            )

            set_exported_revision(
                state,
                export_type,
                revision,
            )

            return True


def ensure_current_export(
    engine: Engine,
    export_type: ExportType,
) -> Path:
    """Reuse XML when current, otherwise regenerate safely."""

    file_path = get_export_path(export_type)

    with Session(engine) as db:
        if is_export_current(db, export_type):
            return file_path

    # Dedicated transaction-level lock prevents two exporters
    # for the same type from regenerating simultaneously.
    with engine.connect() as lock_conn:
        with lock_conn.begin():
            lock_conn.execute(
                text(
                    "SELECT pg_advisory_xact_lock(:lock_key)"
                ),
                {"lock_key": EXPORT_LOCK_KEYS[export_type]},
            )

            # Recheck after obtaining the lock.
            with Session(engine) as db:
                if is_export_current(db, export_type):
                    return file_path

            for _ in range(MAX_EXPORT_ATTEMPTS):
                revision, xml_data = generate_snapshot_xml(
                    engine,
                    export_type,
                )

                candidate_path = write_export_candidate(
                    export_type,
                    xml_data,
                )

                try:
                    if publish_if_current(
                        engine,
                        export_type,
                        revision,
                        candidate_path,
                    ):
                        return file_path
                finally:
                    candidate_path.unlink(
                        missing_ok=True
                    )

    raise HTTPException(
        status_code=409,
        detail=(
            "NRD data changed during export. "
            "Please retry the export."
        ),
    )
