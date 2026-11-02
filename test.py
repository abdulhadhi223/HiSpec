
import os
from pathlib import Path
from uuid import uuid4

EXPORT_DIR = Path(
    os.getenv(
        "NRD_EXPORT_DIR",
        "./storage/nrd_exports",
    )
)

EXPORT_FILES = {
    "technical": "nrd_technical.xml",
    "tactical": "nrd_tactical.xml",
}


def get_export_path(export_type: str) -> Path:
    """Return the fixed path for an NRD export."""

    filename = EXPORT_FILES.get(export_type.lower())

    if filename is None:
        raise ValueError(
            "Export type must be technical or tactical"
        )

    return EXPORT_DIR / filename


def save_export_xml(
    export_type: str,
    xml_content: str,
) -> Path:
    """Atomically replace the existing XML export."""

    EXPORT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    file_path = get_export_path(export_type)

    temp_path = file_path.with_name(
        f".{file_path.name}.{uuid4().hex}.tmp"
    )

    try:
        temp_path.write_bytes(
            xml_content.encode("utf-8")
        )

        # Replace the existing export atomically.
        os.replace(temp_path, file_path)

    finally:
        temp_path.unlink(missing_ok=True)

    return file_path



from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.nrd.export_service import ExportService
from app.services.nrd.export_file_service import (
    get_export_path,
    save_export_xml,
)


@router.get(
    "/export/{export_type}",
    summary="Export NRD XML",
)
def export(
    export_type: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, str]:

    export_type = export_type.lower()

    if export_type not in {"technical", "tactical"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid export type",
        )

    service = ExportService()

    try:
        xml_data = service.export_all(
            db,
            export_type,
        )

        file_path = save_export_xml(
            export_type,
            xml_data,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    download_url = str(
        request.url_for(
            "download_nrd_export",
            export_type=export_type,
        )
    )

    return {
        "export_type": export_type,
        "filename": file_path.name,
        "download_url": download_url,
        "message": "XML exported successfully",
    }




from fastapi.responses import FileResponse


@router.get(
    "/export/download/{export_type}",
    name="download_nrd_export",
    summary="Download NRD XML",
)
def download_nrd_export(
    export_type: str,
) -> FileResponse:

    try:
        file_path = get_export_path(export_type)

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Export file not found",
        )

    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type="application/xml",
        content_disposition_type="attachment",
    )


services:
  nmdb:
    environment:
      NRD_EXPORT_DIR: /var/lib/nmdb/nrd_exports
    volumes:
      - nrd_export_data:/var/lib/nmdb/nrd_exports

volumes:
  nrd_export_data:



from pathlib import Path

from app.services.nrd import export_file_service


def test_export_file_is_overwritten(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        export_file_service,
        "EXPORT_DIR",
        tmp_path,
    )

    first_xml = "<Root>First Export</Root>"
    second_xml = "<Root>Second Export</Root>"

    path = export_file_service.save_export_xml(
        "technical",
        first_xml,
    )

    assert path.name == "nrd_technical.xml"
    assert path.read_text() == first_xml

    updated_path = export_file_service.save_export_xml(
        "technical",
        second_xml,
    )

    assert updated_path == path
    assert path.read_text() == second_xml

    assert len(list(tmp_path.iterdir())) == 1


def test_technical_and_tactical_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        export_file_service,
        "EXPORT_DIR",
        tmp_path,
    )

    export_file_service.save_export_xml(
        "technical",
        "<Technical/>",
    )

    export_file_service.save_export_xml(
        "tactical",
        "<Tactical/>",
    )

    assert (
        tmp_path / "nrd_technical.xml"
    ).is_file()

    assert (
        tmp_path / "nrd_tactical.xml"
    ).is_file()



import os
from pathlib import Path
from uuid import uuid4

EXPORT_DIR = Path(
    os.getenv(
        "NRD_EXPORT_DIR",
        "./storage/nrd_exports",
    )
)

EXPORT_FILES = {
    "technical": "nrd_technical.xml",
    "tactical": "nrd_tactical.xml",
}


def get_export_path(export_type: str) -> Path:
    """Get the fixed export path for Technical or Tactical XML."""

    filename = EXPORT_FILES.get(export_type.lower())

    if filename is None:
        raise ValueError(
            "Invalid export type. Use technical or tactical."
        )

    return EXPORT_DIR / filename


def save_export_xml(
    export_type: str,
    xml_content: str,
) -> Path:
    """Save XML, replacing the existing export atomically."""

    file_path = get_export_path(export_type)

    file_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_path = file_path.with_name(
        f".{file_path.name}.{uuid4().hex}.tmp"
    )

    try:
        temp_path.write_text(
            xml_content,
            encoding="utf-8",
        )

        os.replace(temp_path, file_path)

    finally:
        temp_path.unlink(missing_ok=True)

    return file_path
