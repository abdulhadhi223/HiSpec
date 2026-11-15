
class EWTrackCreate(EWTrackBase):
    source_track_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
    )

    @field_validator("source_track_id")
    @classmethod
    def validate_source_track_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("source_track_id cannot be blank")
        return value


class EWTrackPointCreate(EWTrackPointBase):
    model_config = ConfigDict(extra="forbid")


class EWTrackPointSensorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sensor_catalog_id: uuid.UUID
    role: SensorRoleType | None = None


class EWTrackEmitterCreate(EWTrackEmitterBase):
    model_config = ConfigDict(extra="forbid")
===========================
import logging

from fastapi import HTTPException
from sqlalchemy import func

from app.models.mission_models import Mission

logger = logging.getLogger(__name__)


def _validate_mission(
    db: Session,
    mission_id: uuid.UUID | None,
) -> None:
    if mission_id is None:
        return

    if db.get(Mission, mission_id) is None:
        raise HTTPException(
            status_code=404,
            detail="Mission not found",
        )


def _integrity_details(
    exc: IntegrityError,
) -> tuple[str | None, str | None]:
    original = exc.orig

    sqlstate = (
        getattr(original, "sqlstate", None)
        or getattr(original, "pgcode", None)
    )

    diag = getattr(original, "diag", None)
    constraint = getattr(diag, "constraint_name", None)

    return sqlstate, constraint
===========================
except IntegrityError as exc:
    db.rollback()

    sqlstate, constraint = _integrity_details(exc)

    if (
        sqlstate == "23505"
        and constraint == "ew_track_source_system"
    ):
        raise ConflictError(
            ErrorCode.TRACK_ALREADY_EXISTS
        ) from exc

    if (
        sqlstate == "23503"
        and constraint == "ew_track_mission_id_fkey"
    ):
        raise HTTPException(
            status_code=404,
            detail="Mission not found",
        ) from exc

    logger.exception(
        "EW track integrity failure: constraint=%s, sqlstate=%s",
        constraint,
        sqlstate,
    )

    raise DatabaseError(
        ErrorCode.DATABASE_OPERATION_FAILED
    ) from exc
===========================
def append_track_point(
    db: Session,
    track_id: uuid.UUID,
    data: EWTrackPointCreate,
) -> EWTrackPoint:
    """Append a new EW track point."""

    try:
        if db.get(EWTrack, track_id) is None:
            raise NotFoundError(ErrorCode.TRACK_NOT_FOUND)

        point = EWTrackPoint(
            track_id=track_id,
            **data.model_dump(exclude={"track_id"}),
        )

        db.add(point)
        db.commit()
        db.refresh(point)

        logger.info(
            "EW track point created: track_id=%s point_id=%s",
            track_id,
            point.id,
        )

        return point

    except IntegrityError as exc:
        db.rollback()

        sqlstate, constraint = _integrity_details(exc)

        if (
            sqlstate == "23505"
            and constraint == "ew_track_point_unique"
        ):
            raise ConflictError(
                ErrorCode.TRACK_POINT_ALREADY_EXISTS
            ) from exc

        if (
            sqlstate == "23503"
            and constraint == "ew_track_point_track_id_fkey"
        ):
            raise NotFoundError(
                ErrorCode.TRACK_NOT_FOUND
            ) from exc

        logger.exception(
            "EW track point integrity failure: %s, %s",
            sqlstate,
            constraint,
        )

        raise DatabaseError(
            ErrorCode.DATABASE_OPERATION_FAILED
        ) from exc

    except SQLAlchemyError as exc:
        db.rollback()

        logger.exception(
            "Failed to append EW track point: track_id=%s",
            track_id,
        )

        raise DatabaseError(
            ErrorCode.DATABASE_OPERATION_FAILED
        ) from exc
===========================
stmt = select(EWTrack).distinct(EWTrack.id)

stmt = _apply_track_filters(stmt, filters)
stmt = _apply_emitter_filters(stmt, filters)

count_stmt = select(func.count()).select_from(
    stmt.order_by(None).subquery()
)

total = db.scalar(count_stmt) or 0

stmt = stmt.order_by(
    EWTrack.id,
    EWTrack.created_at.desc(),
)

stmt = stmt.offset(skip).limit(limit)

records = list(db.execute(stmt).scalars().all())

return records, total
===========================
def list_track_points(
    db: Session,
    track_id: uuid.UUID,
    skip: int,
    limit: int,
) -> tuple[list[EWTrackPoint], int]:

    try:
        stmt = select(EWTrackPoint).where(
            EWTrackPoint.track_id == track_id
        )

        total = db.scalar(
            select(func.count()).select_from(
                stmt.subquery()
            )
        ) or 0

        stmt = (
            stmt.order_by(
                EWTrackPoint.observed_at,
                EWTrackPoint.id,
            )
            .offset(skip)
            .limit(limit)
        )

        records = list(db.execute(stmt).scalars().all())
        return records, total

    except SQLAlchemyError as exc:
        logger.exception("Failed to list EW track points")
        raise DatabaseError(
            ErrorCode.DATABASE_OPERATION_FAILED
        ) from exc