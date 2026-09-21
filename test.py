def _write_placeholder_output(input_path: Path, output_path: Path) -> None:
    """Writes the placeholder MDF standing in for the vendor CLI output."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        handle.write(_PLACEHOLDER_HEADER)
        with input_path.open("rb") as source:
            shutil.copyfileobj(source, handle)


def run_elt_cli(input_path: Path, output_path: Path) -> Path:
    """Produces an MDF at output_path from the threat XML at input_path."""
    if not input_path.is_file():
        raise ExternalToolError(
            ErrorCode.ELT_CLI_FAILED, detail="ELT CLI input file is missing."
        )

    try:
        _write_placeholder_output(input_path, output_path)
    except OSError as exc:
        raise ExternalToolError(
            ErrorCode.ELT_CLI_FAILED, detail="ELT CLI invocation failed."
        ) from exc

    if not output_path.is_file():
        raise ExternalToolError(
            ErrorCode.ELT_CLI_FAILED, detail="ELT CLI produced no output file."
        )

    logger.info("ELT CLI (placeholder) produced %s", output_path.name)
    return output_path

Test, in test_elt_cli_runner.py:

python
def test_raises_when_no_output_produced(tmp_path, monkeypatch) -> None:
    """Raises ExternalToolError when the CLI leaves no output file behind."""
    from app.core.exception import ExternalToolError
    from app.services.mission import elt_cli_runner

    source = tmp_path / "in.xml"
    source.write_bytes(VALID_XML)
    monkeypatch.setattr(
        elt_cli_runner, "_write_placeholder_output", lambda src, dst: None
    )

    with pytest.raises(ExternalToolError):
        elt_cli_runner.run_elt_cli(source, tmp_path / "out.mdf")


        def test_persist_upload_rejects_missing_filename(tmp_path) -> None:
    """Raises ValidationError when the upload carries no filename."""
    import io

    import pytest
    from fastapi import UploadFile

    from app.core.exception import ValidationError
    from app.services.mission.elt_mdf_service import _persist_upload

    upload = UploadFile(file=io.BytesIO(VALID_XML), filename=None)

    with pytest.raises(ValidationError):
        _persist_upload(upload, tmp_path)


def test_returns_404_for_unknown_mdf(client, mdf_url) -> None:
    """Returns 404 for a well-formed but unmapped MDF id on an existing mission."""
    response = client.get(f"{mdf_url}/{uuid.uuid4()}")

    assert response.status_code == 404


def test_returns_404_when_platform_columns_null(client, db_session, mission_id) -> None:
    """Returns the no-platform error when the assignment row has null columns."""
    from app.models.mission_models import MissionPlatform

    db_session.add(
        MissionPlatform(
            mission_id=uuid.UUID(str(mission_id)),
            platform_type=None,
            platform_instance_id=None,
        )
    )
    db_session.commit()

    response = client.get(f"/missions/{mission_id}/platform-instance")

    assert response.status_code == 400


def test_resolves_platform_instance_name(
    client, mission_with_platform, monkeypatch
) -> None:
    """Returns the resolved display name when the platform instance exists."""
    from types import SimpleNamespace

    from sqlalchemy.orm import Session

    monkeypatch.setattr(
        Session, "get", lambda self, model, ident: SimpleNamespace(name="Test Platform")
    )

    body = client.get(f"/missions/{mission_with_platform}/platform-instance").json()

    assert body["platform_instance_name"] == "Test Platform"


    The produced file is in a per-request temp directory created by mkdtemp, and run_elt_cli already verifies it exists before returning, so nothing else can remove it before the move. If it did go missing, shutil.move raises FileNotFoundError, which is caught by the OSError handler and surfaced as a storage error. An extra existence check would just add a check-then-act gap without removing the need for the except, so I've left it as is.