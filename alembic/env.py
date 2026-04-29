from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

from alembic import context

# Load app config so DATABASE_URL is available
from app.core.config import get_settings

# Import all models so autogenerate sees every table
import app.models.orm_models       # noqa: F401
import app.models.common_models    # noqa: F401
import app.models.ew_track_models  # noqa: F401

from app.core.database import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url from app settings (respects .env overrides)
config.set_main_option("sqlalchemy.url", get_settings().DATABASE_URL)

target_metadata = Base.metadata

# ---------------------------------------------------------------------------
# PostgreSQL enum types that the ORM uses with create_type=False.
# Alembic autogenerate won't emit CREATE TYPE, so we do it here
# inside a DO block so the migration is idempotent.
# ---------------------------------------------------------------------------
from app.core.enum import (
    Classification,
    HostilityType,
    PlatformCategoryType,
    SensorRoleType,
    SignalType,
)

_ENUM_TYPES = [
    ("classification_type", Classification),
    ("signal_type", SignalType),
    ("hostility_type", HostilityType),
    ("platform_category_type", PlatformCategoryType),
    ("sensor_role_type", SensorRoleType),
]


def _ensure_enum_types(conn):
    for type_name, enum_cls in _ENUM_TYPES:
        values_sql = ", ".join(f"'{v.value}'" for v in enum_cls)
        conn.execute(text(
            f"DO $$ BEGIN "
            f"  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{type_name}') "
            f"  THEN CREATE TYPE {type_name} AS ENUM ({values_sql}); "
            f"  END IF; "
            f"END $$;"
        ))


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        _ensure_enum_types(connection)
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
