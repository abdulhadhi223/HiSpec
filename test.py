purged_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True), nullable=True
)

Make file_path and download_url nullable if they aren't already, and add an index so the sweep query doesn't seq-scan:

python
__table_args__ = (
    Index(
        "ix_threat_export_purge_candidates",
        "expires_at",
        postgresql_where=text("purged_at IS NULL"),
    ),
)

Alembic migration for all three.

3. app/services/export_cleanup_service.py
python
"""Removes expired threat export artifacts from disk.

Export rows are retained as an audit record; only the generated file and its
download link are cleared.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging_manager import get_logger
from app.models.mission_models import ThreatExport

logger = get_logger(__name__)

# Namespaced identifier so only export sweeps contend for this lock.
_CLEANUP_LOCK_KEY = 8_214_507_331


async def _try_acquire_lock(db: AsyncSession) -> bool:
    """Takes a session-scoped advisory lock so only one replica sweeps."""
    result = await db.execute(
        text("SELECT pg_try_advisory_lock(:key)"), {"key": _CLEANUP_LOCK_KEY}
    )
    return bool(result.scalar_one())


async def _release_lock(db: AsyncSession) -> None:
    await db.execute(
        text("SELECT pg_advisory_unlock(:key)"), {"key": _CLEANUP_LOCK_KEY}
    )


def _remove_artifact(file_path: str | None, export_id: uuid.UUID) -> None:
    """Deletes one artifact, tolerating a file that is already gone."""
    if file_path is None:
        return
    try:
        Path(file_path).unlink(missing_ok=True)
    except OSError:
        logger.exception(
            "Failed to remove expired export artifact",
            extra={"export_id": str(export_id), "file_path": file_path},
        )


async def purge_expired_exports(db: AsyncSession) -> int:
    """Clears artifacts for exports whose expiry has passed.

    Returns the number of exports purged. Rows already purged are skipped, so
    repeated runs are idempotent.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)

    stmt = (
        select(ThreatExport)
        .where(
            ThreatExport.expires_at < now,
            ThreatExport.purged_at.is_(None),
        )
        .order_by(ThreatExport.expires_at)
        .limit(settings.EXPORT_CLEANUP_BATCH_SIZE)
    )
    expired = list((await db.execute(stmt)).scalars())

    for export in expired:
        _remove_artifact(export.file_path, export.id)
        export.file_path = None
        export.download_url = None
        export.purged_at = now

    await db.commit()

    if expired:
        logger.info(
            "Purged expired threat exports", extra={"purged_count": len(expired)}
        )
    return len(expired)


async def run_cleanup_cycle(db: AsyncSession) -> int:
    """Runs one sweep if no other replica currently holds the lock."""
    if not await _try_acquire_lock(db):
        logger.debug("Export cleanup skipped; lock held by another worker")
        return 0
    try:
        return await purge_expired_exports(db)
    finally:
        await _release_lock(db)
4. Scheduler wiring in main.py
python
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger


async def _scheduled_export_cleanup() -> None:
    from app.core.database import AsyncSessionLocal
    from app.services import export_cleanup_service

    async with AsyncSessionLocal() as db:
        await export_cleanup_service.run_cleanup_cycle(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    scheduler: AsyncIOScheduler | None = None

    if settings.EXPORT_CLEANUP_ENABLED:
        scheduler = AsyncIOScheduler(timezone="UTC")
        scheduler.add_job(
            _scheduled_export_cleanup,
            trigger=IntervalTrigger(
                hours=settings.EXPORT_CLEANUP_INTERVAL_HOURS
            ),
            id="expired_export_cleanup",
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now(timezone.utc),
        )
        scheduler.start()

    yield

    if scheduler is not None:
        scheduler.shutdown(wait=False)

coalesce=True and max_instances=1 mean a long sweep won't stack up backlogged runs.

5. Serving must check expiry

Whatever endpoint serves download_url has to reject expired exports itself. Between expiry and the next sweep there's up to a day where the file still exists on disk:

python
if export.purged_at is not None or export.expires_at < datetime.now(timezone.utc):
    raise NotFoundError(f"Export {export_id} has expired")
6. Tests
python
class TestPurgeExpiredExports:
    async def test_removes_artifact_for_an_expired_export(...) -> None:
        """Deletes the file on disk once the export has passed its expiry."""

    async def test_clears_download_url_for_an_expired_export(...) -> None:
        """Clears the download link so an expired export cannot be served."""

    async def test_retains_the_export_row_as_an_audit_record(...) -> None:
        """Keeps the export row after purging its artifact."""

    async def test_retains_artifact_for_an_unexpired_export(...) -> None:
        """Leaves exports whose expiry lies in the future untouched."""

    async def test_skips_rows_already_purged(...) -> None:
        """Ignores exports that a previous sweep has already cleared."""

    async def test_is_idempotent_across_repeated_runs(...) -> None:
        """Purges nothing further when run twice in succession."""

    async def test_tolerates_an_artifact_missing_from_disk(...) -> None:
        """Completes the purge when the file has already been removed."""

    async def test_respects_the_configured_batch_size(...) -> None:
        """Purges no more than the configured number of exports per run."""

    async def test_expired_export_is_not_served(...) -> None:
        """Returns 404 for an export whose expiry has passed but is unpurged."""