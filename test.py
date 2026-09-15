"""Adapter around the vendor ELT CLI tool.

PLACEHOLDER: the real vendor CLI is not yet available. run_elt_cli keeps the
signature the real invocation will have (input path in, output path out,
non-zero exit raises) so swapping in subprocess.run touches this file only.
"""

import logging
import shutil
from pathlib import Path

from app.core.exceptions import ExternalToolError

logger = logging.getLogger(__name__)

# Replace with settings.ELT_CLI_PATH / settings.ELT_CLI_TIMEOUT_SECONDS
# once the vendor tool is delivered and mounted into the container.
_PLACEHOLDER_HEADER = b"NMDB-ELT-MDF-PLACEHOLDER\n"


def run_elt_cli(input_path: Path, output_path: Path) -> Path:
    """Produces an MDF at output_path from the threat XML at input_path."""
    if not input_path.is_file():
        raise ExternalToolError("ELT CLI input file is missing.")

    try:
        # Real implementation:
        #     result = subprocess.run(
        #         [settings.ELT_CLI_PATH, "--input", str(input_path),
        #          "--output", str(output_path)],
        #         capture_output=True,
        #         timeout=settings.ELT_CLI_TIMEOUT_SECONDS,
        #         check=False,
        #     )
        #     if result.returncode != 0:
        #         raise ExternalToolError(
        #             f"ELT CLI exited with {result.returncode}."
        #         )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("wb") as handle:
            handle.write(_PLACEHOLDER_HEADER)
            with input_path.open("rb") as source:
                shutil.copyfileobj(source, handle)
    except OSError as exc:
        raise ExternalToolError("ELT CLI invocation failed.") from exc

    if not output_path.is_file():
        raise ExternalToolError("ELT CLI produced no output file.")

    logger.info("ELT CLI (placeholder) produced %s", output_path.name)
    return output_path



"""Service layer for ELT MDF generation, retrieval and expiry purge."""

import logging
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql.functions import count

from app.core.config import settings
from app.core.exceptions import (
    BusinessValidationError,
    DatabaseError,
    ExternalToolError,
    NotFoundError,
    StorageError,
)
from app.models.orm_models import Mission
from app.models.sensor_programming_file_model import (
    SensorProgrammingFile,
    SensorProgrammingFileType,
)
from app.schemas.elt_mdf_schemas import MdfListResponse, MdfStatus, MdfSummary
from app.services.elt_cli_runner import run_elt_cli

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024


def create_elt_mdf(db: Session, mission_id: uuid.UUID, upload: UploadFile) -> MdfSummary:
    """Generates an MDF from an uploaded threat XML and records its metadata."""
    mission = _get_mission(db, mission_id)
    work_dir = Path(tempfile.mkdtemp(prefix="nmdb-elt-"))

    try:
        input_path = _persist_upload(upload, work_dir)
        _validate_threat_xml(input_path)

        output_name = f"{uuid.uuid4()}.mdf"
        produced = run_elt_cli(input_path, work_dir / output_name)
        stored_path = _store_artifact(produced, mission.id, output_name)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    generated_at = datetime.now(timezone.utc)
    expires_at = generated_at + timedelta(days=settings.EXPORT_LINK_TTL_DAYS)
    record = SensorProgrammingFile(
        mission_id=mission.id,
        file_type=SensorProgrammingFileType.MDF,
        source_filename=upload.filename or "threat.xml",
        file_path=str(stored_path),
        expires_at=expires_at,
        generated_at=generated_at,
    )

    try:
        db.add(record)
        db.flush()
        record.download_url = _build_download_url(mission.id, record.id)
        db.commit()
        db.refresh(record)
    except SQLAlchemyError as exc:
        db.rollback()
        stored_path.unlink(missing_ok=True)
        raise DatabaseError("Failed to persist sensor programming file.") from exc

    return _to_summary(record)


def list_elt_mdf(db: Session, mission_id: uuid.UUID) -> MdfListResponse:
    """Returns all MDF artifacts recorded against a mission, newest first."""
    _get_mission(db, mission_id)
    try:
        stmt = (
            select(SensorProgrammingFile)
            .where(SensorProgrammingFile.mission_id == mission_id)
            .order_by(SensorProgrammingFile.generated_at.desc())
        )
        records = db.execute(stmt).scalars().all()
        total = db.execute(
            select(count()).select_from(SensorProgrammingFile).where(
                SensorProgrammingFile.mission_id == mission_id
            )
        ).scalar_one()
    except SQLAlchemyError as exc:
        raise DatabaseError("Failed to list sensor programming files.") from exc

    return MdfListResponse(total=total, items=[_to_summary(r) for r in records])


def get_elt_mdf(db: Session, mission_id: uuid.UUID, mdf_id: uuid.UUID) -> MdfSummary:
    """Returns metadata for a single MDF scoped to its mission."""
    return _to_summary(_get_record(db, mission_id, mdf_id))


def resolve_download_path(
    db: Session, mission_id: uuid.UUID, mdf_id: uuid.UUID
) -> tuple[Path, str]:
    """Returns the on-disk path and filename for a downloadable MDF."""
    record = _get_record(db, mission_id, mdf_id)
    if _derive_status(record) is not MdfStatus.AVAILABLE:
        raise NotFoundError("MDF artifact is no longer available for download.")

    path = Path(record.file_path) if record.file_path else None
    if path is None or not path.is_file():
        raise StorageError("MDF artifact is missing from storage.")
    return path, path.name


def purge_expired_mdf_files(db: Session) -> int:
    """Deletes expired MDF artifacts from disk and marks their rows purged."""
    now = datetime.now(timezone.utc)
    try:
        stmt = select(SensorProgrammingFile).where(
            SensorProgrammingFile.expires_at <= now,
            SensorProgrammingFile.purged_at.is_(None),
        )
        records = db.execute(stmt).scalars().all()
    except SQLAlchemyError as exc:
        raise DatabaseError("Failed to query expired MDF artifacts.") from exc

    purged = 0
    for record in records:
        if record.file_path:
            Path(record.file_path).unlink(missing_ok=True)
        record.file_path = None
        record.download_url = None
        record.purged_at = now
        purged += 1

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseError("Failed to mark MDF artifacts purged.") from exc

    logger.info("Purged %s expired MDF artifacts.", purged)
    return purged


def _get_mission(db: Session, mission_id: uuid.UUID) -> Mission:
    """Returns the mission or raises NotFoundError."""
    try:
        mission = db.execute(
            select(Mission).where(Mission.id == mission_id)
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise DatabaseError("Failed to load mission.") from exc

    if mission is None:
        raise NotFoundError(f"Mission {mission_id} was not found.")
    return mission


def _get_record(
    db: Session, mission_id: uuid.UUID, mdf_id: uuid.UUID
) -> SensorProgrammingFile:
    """Returns an MDF row scoped to its mission or raises NotFoundError."""
    _get_mission(db, mission_id)
    try:
        record = db.execute(
            select(SensorProgrammingFile).where(
                SensorProgrammingFile.id == mdf_id,
                SensorProgrammingFile.mission_id == mission_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise DatabaseError("Failed to load sensor programming file.") from exc

    if record is None:
        raise NotFoundError(f"MDF {mdf_id} was not found for this mission.")
    return record


def _persist_upload(upload: UploadFile, work_dir: Path) -> Path:
    """Streams the upload to disk, enforcing the 50 MB cap."""
    if not upload.filename:
        raise BusinessValidationError("No threat XML file was supplied.")

    target = work_dir / "input.xml"
    written = 0
    try:
        with target.open("wb") as handle:
            while chunk := upload.file.read(_CHUNK_BYTES):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise BusinessValidationError(
                        "Threat XML exceeds the 50 MB upload limit."
                    )
                handle.write(chunk)
    except OSError as exc:
        raise StorageError("Failed to buffer the uploaded threat XML.") from exc
    finally:
        upload.file.close()

    if written == 0:
        raise BusinessValidationError("The uploaded threat XML is empty.")
    return target


def _validate_threat_xml(path: Path) -> None:
    """Confirms the uploaded file parses as well-formed XML."""
    try:
        ElementTree.parse(path)
    except ElementTree.ParseError as exc:
        raise BusinessValidationError("The uploaded file is not well-formed XML.") from exc


def _store_artifact(produced: Path, mission_id: uuid.UUID, name: str) -> Path:
    """Moves the generated MDF into the durable export storage root."""
    destination_dir = Path(settings.EXPORT_STORAGE_ROOT) / str(mission_id) / "mdf"
    try:
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / name
        shutil.move(str(produced), destination)
    except OSError as exc:
        raise StorageError("Failed to store the generated MDF.") from exc
    return destination


def _build_download_url(mission_id: uuid.UUID, mdf_id: uuid.UUID) -> str:
    """Builds the download URL without duplicating the configured base path."""
    base = settings.EXPORT_DOWNLOAD_BASE_URL.rstrip("/")
    return f"{base}/missions/{mission_id}/exports/mdf/elt/{mdf_id}/download"


def _derive_status(record: SensorProgrammingFile) -> MdfStatus:
    """Derives availability at read time rather than storing it."""
    if record.purged_at is not None:
        return MdfStatus.PURGED
    if record.expires_at <= datetime.now(timezone.utc):
        return MdfStatus.EXPIRED
    return MdfStatus.AVAILABLE


def _to_summary(record: SensorProgrammingFile) -> MdfSummary:
    """Maps an ORM row to its response schema, hiding stale download URLs."""
    status = _derive_status(record)
    return MdfSummary(
        id=record.id,
        mission_id=record.mission_id,
        file_type=record.file_type.value,
        source_filename=record.source_filename,
        status=status,
        download_url=record.download_url if status is MdfStatus.AVAILABLE else None,
        expires_at=record.expires_at,
        generated_at=record.generated_at,
    )


"""Tests for the ELT MDF generation, retrieval and purge flow."""

import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest

VALID_XML = b"<?xml version='1.0'?><threats><threat id='1'/></threats>"


def _upload(content: bytes = VALID_XML, name: str = "tech.xml") -> dict:
    """Builds a multipart payload for the MDF endpoint."""
    return {"file": (name, io.BytesIO(content), "application/xml")}


@pytest.fixture
def mdf_url(seeded_mission) -> str:
    """Returns the MDF collection URL for the seeded mission."""
    return f"/missions/{seeded_mission.id}/exports/mdf/elt"


def test_generates_mdf_and_returns_download_url(client, mdf_url) -> None:
    """Returns 201 with an available artifact and a download URL."""
    response = client.post(mdf_url, files=_upload())

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "available"
    assert body["file_type"] == "mdf"
    assert body["source_filename"] == "tech.xml"
    assert body["download_url"].endswith("/download")


def test_persists_artifact_to_storage_root(client, mdf_url, tmp_path) -> None:
    """Writes the generated MDF under the configured export storage root."""
    from pathlib import Path

    from app.core.config import settings

    response = client.post(mdf_url, files=_upload())
    mdf_id = response.json()["id"]

    stored = list(Path(settings.EXPORT_STORAGE_ROOT).rglob("*.mdf"))
    assert len(stored) == 1
    assert stored[0].read_bytes().startswith(b"NMDB-ELT-MDF-PLACEHOLDER")
    assert mdf_id


def test_rejects_malformed_xml(client, mdf_url) -> None:
    """Returns 422 for a file that is not well-formed XML."""
    response = client.post(mdf_url, files=_upload(content=b"<threats><unclosed>"))

    assert response.status_code == 422


def test_rejects_empty_upload(client, mdf_url) -> None:
    """Returns 422 when the uploaded file has no content."""
    response = client.post(mdf_url, files=_upload(content=b""))

    assert response.status_code == 422


def test_rejects_upload_over_size_limit(client, mdf_url) -> None:
    """Returns 422 when the threat XML exceeds the 50 MB cap."""
    from app.services.elt_mdf_service import MAX_UPLOAD_BYTES

    oversized = b"<threats>" + b"a" * (MAX_UPLOAD_BYTES + 1)
    response = client.post(mdf_url, files=_upload(content=oversized))

    assert response.status_code == 422


def test_returns_404_for_unknown_mission(client) -> None:
    """Returns 404 for a well-formed but unmapped mission id."""
    response = client.post(
        f"/missions/{uuid.uuid4()}/exports/mdf/elt", files=_upload()
    )

    assert response.status_code == 404


def test_cli_failure_writes_no_row(client, db_session, mdf_url, monkeypatch) -> None:
    """Records no metadata when the ELT CLI invocation fails."""
    from sqlalchemy import select
    from sqlalchemy.sql.functions import count

    from app.core.exceptions import ExternalToolError
    from app.models.sensor_programming_file_model import SensorProgrammingFile
    from app.services import elt_mdf_service

    def _fail(input_path, output_path):
        raise ExternalToolError("ELT CLI exited with 1.")

    monkeypatch.setattr(elt_mdf_service, "run_elt_cli", _fail)
    response = client.post(mdf_url, files=_upload())

    assert response.status_code == 502
    rows = db_session.execute(
        select(count()).select_from(SensorProgrammingFile)
    ).scalar_one()
    assert rows == 0


def test_lists_artifacts_newest_first(client, mdf_url) -> None:
    """Returns every MDF for the mission ordered by generation time."""
    client.post(mdf_url, files=_upload(name="first.xml"))
    client.post(mdf_url, files=_upload(name="second.xml"))

    body = client.get(mdf_url).json()

    assert body["total"] == 2
    assert body["items"][0]["source_filename"] == "second.xml"


def test_get_single_artifact_scoped_to_mission(client, db_session, mdf_url) -> None:
    """Returns 404 when the MDF belongs to a different mission."""
    mdf_id = client.post(mdf_url, files=_upload()).json()["id"]

    response = client.get(f"/missions/{uuid.uuid4()}/exports/mdf/elt/{mdf_id}")

    assert response.status_code == 404


def test_download_streams_generated_file(client, mdf_url) -> None:
    """Streams the stored MDF back with octet-stream content type."""
    mdf_id = client.post(mdf_url, files=_upload()).json()["id"]

    response = client.get(f"{mdf_url}/{mdf_id}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.content.startswith(b"NMDB-ELT-MDF-PLACEHOLDER")


def test_expired_artifact_hides_download_url(client, db_session, mdf_url) -> None:
    """Suppresses the download URL once the artifact has expired."""
    from app.models.sensor_programming_file_model import SensorProgrammingFile

    mdf_id = client.post(mdf_url, files=_upload()).json()["id"]
    record = db_session.get(SensorProgrammingFile, uuid.UUID(mdf_id))
    record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    body = client.get(f"{mdf_url}/{mdf_id}").json()

    assert body["status"] == "expired"
    assert body["download_url"] is None


def test_download_rejected_after_expiry(client, db_session, mdf_url) -> None:
    """Returns 404 when downloading an expired artifact."""
    from app.models.sensor_programming_file_model import SensorProgrammingFile

    mdf_id = client.post(mdf_url, files=_upload()).json()["id"]
    record = db_session.get(SensorProgrammingFile, uuid.UUID(mdf_id))
    record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    response = client.get(f"{mdf_url}/{mdf_id}/download")

    assert response.status_code == 404


def test_purge_removes_expired_files_and_marks_rows(
    client, db_session, mdf_url
) -> None:
    """Deletes expired artifacts from disk and flags their rows purged."""
    from pathlib import Path

    from app.models.sensor_programming_file_model import SensorProgrammingFile
    from app.services.elt_mdf_service import purge_expired_mdf_files

    mdf_id = client.post(mdf_url, files=_upload()).json()["id"]
    record = db_session.get(SensorProgrammingFile, uuid.UUID(mdf_id))
    stored = Path(record.file_path)
    record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    assert purge_expired_mdf_files(db_session) == 1

    db_session.refresh(record)
    assert not stored.exists()
    assert record.purged_at is not None
    assert record.file_path is None
    assert client.get(f"{mdf_url}/{mdf_id}").json()["status"] == "purged"


"""API routes for ELT MDF generation and retrieval.

Kong permission group for these endpoints is still open — nmdb.export.mdf
proposed, needs Mikkel's sign-off before US5's mapping table is updated.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.schemas.elt_mdf_schemas import MdfListResponse, MdfSummary
from app.services import elt_mdf_service

router = APIRouter(prefix="/missions", tags=["ELT MDF"])


@router.post(
    "/{mission_id}/exports/mdf/elt",
    response_model=MdfSummary,
    status_code=status.HTTP_201_CREATED,
)
def create_elt_mdf(
    mission_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> MdfSummary:
    """Generates an ELT MDF from an uploaded threat XML."""
    summary = elt_mdf_service.create_elt_mdf(db, mission_id, file)
    background_tasks.add_task(elt_mdf_service.purge_expired_mdf_files, db)
    return summary


@router.get("/{mission_id}/exports/mdf/elt", response_model=MdfListResponse)
def list_elt_mdf(
    mission_id: uuid.UUID, db: Session = Depends(get_db)
) -> MdfListResponse:
    """Lists MDF artifacts generated for a mission."""
    return elt_mdf_service.list_elt_mdf(db, mission_id)


@router.get("/{mission_id}/exports/mdf/elt/{mdf_id}", response_model=MdfSummary)
def get_elt_mdf(
    mission_id: uuid.UUID, mdf_id: uuid.UUID, db: Session = Depends(get_db)
) -> MdfSummary:
    """Returns metadata for a single MDF artifact."""
    return elt_mdf_service.get_elt_mdf(db, mission_id, mdf_id)


@router.get("/{mission_id}/exports/mdf/elt/{mdf_id}/download")
def download_elt_mdf(
    mission_id: uuid.UUID, mdf_id: uuid.UUID, db: Session = Depends(get_db)
) -> FileResponse:
    """Streams the generated MDF file back to the operator."""
    path, filename = elt_mdf_service.resolve_download_path(db, mission_id, mdf_id)
    return FileResponse(
        path=path, filename=filename, media_type="application/octet-stream"
    )


"""Pydantic v2 schemas for ELT MDF generation and retrieval."""

import enum
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MdfStatus(str, enum.Enum):
    """Derived availability state of an MDF artifact."""

    AVAILABLE = "available"
    EXPIRED = "expired"
    PURGED = "purged"


class MdfSummary(BaseModel):
    """Metadata for a single generated MDF."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    mission_id: uuid.UUID
    file_type: str
    source_filename: str
    status: MdfStatus
    download_url: str | None = None
    expires_at: datetime
    generated_at: datetime


class MdfListResponse(BaseModel):
    """Collection of MDF artifacts for a mission."""

    total: int = Field(ge=0)
    items: list[MdfSummary]


"""ORM model for the ELT MDF artifact (sensor programming file).

NOTE: mirrors the CURRENT threat_export shape (purged_at, nullable
file_path/download_url), not the v5 ERD screenshot. sensor_id is dropped:
"sensor programming file" is the domain term for the MDF, not a per-sensor row.
Requires a new Alembic migration.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.orm_models import Base


class SensorProgrammingFileType(str, enum.Enum):
    """Artifact type stored against a sensor programming file row."""

    MDF = "mdf"


class SensorProgrammingFile(Base):
    """Mission Data File generated by the vendor ELT CLI from a threat XML."""

    __tablename__ = "sensor_programming_file"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    mission_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("mission.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_type: Mapped[SensorProgrammingFileType] = mapped_column(
        Enum(
            SensorProgrammingFileType,
            name="sensor_programming_file_type",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=SensorProgrammingFileType.MDF,
    )
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    download_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    purged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    mission = relationship("Mission", back_populates="sensor_programming_files")
