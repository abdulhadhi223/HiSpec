
@pytest_asyncio.fixture(
    scope="session",
    loop_scope="session",
)
async def async_engine(
    pg_test_url: str,
    pytestconfig: pytest.Config,
):
    """
    NEC test database engine.

    Local:
      - Validate dedicated NEC test database.
      - Create NEC ORM tables.
      - Verify required tables.
      - Clean up local tables.

    Jenkins:
      - Use the existing NEC test schema.
      - Verify Alembic migration history.
      - Verify required NEC tables.
      - Never create or drop tables.

    Alembic is not invoked by this fixture.
    """

    db_prepared = pytestconfig.getoption(
        "--nec-db-prepared"
    )

    url = make_url(pg_test_url)
    metadata = _get_nec_metadata()
    local_tables_created = False

    engine = create_async_engine(
        url,
        echo=False,
        poolclass=NullPool,
        connect_args={
            "server_settings": {
                "search_path": NEC_SCHEMA,
            }
        },
    )

    # Read tables from the configured NEC schema.
    # Works for both local public and Jenkins schemas.
    async def schema_tables(conn):
        result = await conn.execute(
            text(
                "SELECT table_name "
                "FROM information_schema.tables "
                "WHERE table_schema = :schema"
            ),
            {"schema": NEC_SCHEMA},
        )

        return set(result.scalars().all())

    try:
        async with engine.begin() as conn:

            # STEP 1: Validate test database.
            await _validate_connection(
                conn,
                url.database or "",
            )

            # STEP 2: Validate current schema.
            active_schema = await conn.scalar(
                text("SELECT current_schema()")
            )

            if active_schema != NEC_SCHEMA:
                raise RuntimeError(
                    "NEC test schema mismatch: "
                    f"expected {NEC_SCHEMA!r}, "
                    f"got {active_schema!r}"
                )

            # STEP 3: Inspect configured schema.
            existing = await schema_tables(conn)

            if db_prepared:

                # STEP 4A: Jenkins - verify migration.
                # Tables have already been created by
                # the NEC Alembic stage.

                if "alembic_version" not in existing:
                    raise RuntimeError(
                        "Jenkins-prepared NEC schema is "
                        "missing migration history: "
                        f"{NEC_SCHEMA}.alembic_version. "
                        "Run NEC Alembic before pytest."
                    )

                # Quote the configured schema safely.
                quoted_schema = (
                    engine.sync_engine.dialect
                    .identifier_preparer
                    .quote_schema(NEC_SCHEMA)
                )

                revision = await conn.scalar(
                    text(
                        f"SELECT version_num FROM "
                        f"{quoted_schema}.alembic_version "
                        "LIMIT 1"
                    )
                )

                if revision is None:
                    raise RuntimeError(
                        "NEC Alembic version table "
                        f"is empty in {NEC_SCHEMA}"
                    )

            else:

                # STEP 4B: Local - initialize ORM tables.
                # No Alembic migration is executed.
                local_tables_created = True

                await conn.run_sync(
                    _prepare_local_tables,
                    metadata,
                    existing,
                )

            # STEP 5: Verify required NEC tables.
            tables = await schema_tables(conn)

            missing_tables = REQUIRED_TABLES - tables

            if missing_tables:
                raise RuntimeError(
                    "NEC tables are missing from "
                    f"{NEC_SCHEMA}: "
                    f"{sorted(missing_tables)}"
                )

        setup_mode = (
            "Jenkins-prepared tables"
            if db_prepared
            else "local ORM tables"
        )

        print(
            f"NEC test database: {url.database}; "
            f"schema: {NEC_SCHEMA}; "
            f"setup: {setup_mode}"
        )

        yield engine

    finally:
        try:
            # Clean up local ORM tables only.
            # Jenkins-prepared schemas are managed
            # by the Jenkins cleanup stage.
            if local_tables_created:
                async with engine.begin() as conn:
                    await conn.run_sync(
                        lambda sync_conn: metadata.drop_all(
                            bind=sync_conn,
                            checkfirst=True,
                        )
                    )

        finally:
            await engine.dispose()
