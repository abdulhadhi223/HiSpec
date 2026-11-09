        raise RuntimeError("Use one pytest worker per NEC database; do not use -n for this fixture")

    required = {"cached_mission", "cached_sensor_catalog", "nec_sync_log"}
    actual = {table.name for table in NECBase.metadata.tables.values()}
    if actual != required:
        raise RuntimeError(
            f"Unexpected NEC metadata: {sorted(actual)}; expected {sorted(required)}"
        )
    for table in NECBase.metadata.tables.values():
        if table.schema != "public":
            raise RuntimeError(f"NEC model must target public: {table.fullname}")
        for column in table.columns:
            if isinstance(column.type, SAEnum):
                if column.type.schema not in (None, "public"):
                    raise RuntimeError(f"NEC ENUM must target public: {column.type.name}")
                if getattr(column.type, "create_type", True) is False:
                    raise RuntimeError(
                        "NEC model ENUM has create_type=False; give the test metadata an explicit "
                        "ENUM create/drop hook or enable ORM type DDL before using create_all"
                    )

    url = make_url(pg_test_url)
    engine = create_async_engine(
        url, echo=False, poolclass=NullPool,
        connect_args={"server_settings": {"search_path": "public"}},
    )
    try:
        async with engine.begin() as conn:
            database = await conn.scalar(text("SELECT current_database()"))
            if database != url.database:
                raise RuntimeError("Connected database does not match the validated NEC test URL")
            schema = await conn.scalar(text("SELECT current_schema()"))
            if schema != "public":
                raise RuntimeError("NEC test connection must use public")
            if await conn.scalar(text("SELECT to_regclass('public.alembic_version')")):
                raise RuntimeError(
                    "This database has migration history. Provision a fresh disposable NEC test database; "
                    "do not erase migration history to bypass this check"
                )

            # Only this application's metadata, only the validated test database.
            await conn.run_sync(NECBase.metadata.drop_all)
            await conn.run_sync(NECBase.metadata.create_all)
            tables = await conn.run_sync(
                lambda sync_conn: set(inspect(sync_conn).get_table_names(schema="public"))
            )
            if not required.issubset(tables):
                raise RuntimeError(f"Missing NEC test tables: {sorted(required - tables)}")
        print(f"NEC pytest database: {url.database}; schema=public; initialization=metadata")
        yield engine
    finally:
        # Per-test transaction fixtures handle data isolation; do not drop at teardown.
        await engine.dispose()
