
from importlib import import_module
from pathlib import Path
from types import ModuleType

import pytest


XML_V1 = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Root><Name><![CDATA[Caf\u00e9 & Test]]></Name></Root>'
)

XML_V2 = (
    "<Root><Name><![CDATA[Updated]]></Name></Root>"
)


@pytest.fixture
def export_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> ModuleType:
    """Use the real file service with an isolated export directory."""

    # Import during fixture execution because your test setup
    # reloads application modules.
    service = import_module(
        "app.services.nrd.export_file_service"
    )

    monkeypatch.setattr(
        service,
        "EXPORT_DIR",
        tmp_path / "exports" / "nrd",
    )

    return service


@pytest.mark.parametrize(
    ("export_type", "filename"),
    [
        ("technical", "nrd_technical.xml"),
        ("Technical", "nrd_technical.xml"),
        ("tactical", "nrd_tactical.xml"),
    ],
)
def test_get_export_path(
    export_files: ModuleType,
    export_type: str,
    filename: str,
) -> None:
    """Resolve the correct filename, including case normalization."""

    result = export_files.get_export_path(export_type)

    assert result == export_files.EXPORT_DIR / filename


@pytest.mark.parametrize("export_type", ["invalid", ""])
def test_invalid_export_type(
    export_files: ModuleType,
    export_type: str,
) -> None:
    """Reject invalid types without creating an export directory."""

    with pytest.raises(ValueError, match="Invalid export type"):
        export_files.get_export_path(export_type)

    with pytest.raises(ValueError, match="Invalid export type"):
        export_files.save_export_xml(
            export_type=export_type,
            xml_content=XML_V1,
        )

    assert not export_files.EXPORT_DIR.exists()


@pytest.mark.parametrize("export_type", ["technical", "tactical"])
def test_save_export_xml_creates_and_overwrites(
    export_files: ModuleType,
    export_type: str,
) -> None:
    """Create directories, save XML, and replace the same file."""

    assert not export_files.EXPORT_DIR.exists()

    first = export_files.save_export_xml(
        export_type=export_type,
        xml_content=XML_V1,
    )

    assert isinstance(first, Path)
    assert first.name == f"nrd_{export_type}.xml"
    assert first.read_bytes() == XML_V1.encode("utf-8")

    second = export_files.save_export_xml(
        export_type=export_type,
        xml_content=XML_V2,
    )

    assert second == first
    assert second.read_bytes() == XML_V2.encode("utf-8")

    # Only the final XML remains; no temporary files.
    assert list(first.parent.iterdir()) == [first]


def test_save_keeps_technical_and_tactical_separate(
    export_files: ModuleType,
) -> None:
    """Saving one export type must not overwrite the other."""

    technical = export_files.save_export_xml(
        "technical",
        XML_V1,
    )
    tactical = export_files.save_export_xml(
        "tactical",
        XML_V2,
    )

    assert technical != tactical
    assert technical.read_bytes() == XML_V1.encode("utf-8")
    assert tactical.read_bytes() == XML_V2.encode("utf-8")

    assert set(technical.parent.iterdir()) == {
        technical,
        tactical,
    }


def test_failed_replace_preserves_previous_export(
    export_files: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A replacement failure must preserve the previous XML."""

    original = export_files.save_export_xml(
        "technical",
        XML_V1,
    )

    def fail_replace(
        source: Path,
        destination: Path,
    ) -> None:
        assert source.is_file()
        assert destination == original
        raise PermissionError("Simulated replacement failure")

    with monkeypatch.context() as patcher:
        patcher.setattr(
            export_files.os,
            "replace",
            fail_replace,
        )

        with pytest.raises(
            PermissionError,
            match="Simulated replacement",
        ):
            export_files.save_export_xml(
                "technical",
                XML_V2,
            )

    assert original.read_bytes() == XML_V1.encode("utf-8")
    assert list(original.parent.iterdir()) == [original]


def test_failed_write_removes_partial_temporary_file(
    export_files: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial write must not replace or damage the previous XML."""

    original = export_files.save_export_xml(
        "technical",
        XML_V1,
    )

    def fail_write(
        path: Path,
        content: str,
        *,
        encoding: str,
    ) -> int:
        # Simulate failure after writing part of the temporary file.
        path.write_bytes(content[:8].encode(encoding))
        raise OSError("Simulated write failure")

    with monkeypatch.context() as patcher:
        patcher.setattr(
            Path,
            "write_text",
            fail_write,
        )

        with pytest.raises(
            OSError,
            match="Simulated write failure",
        ):
            export_files.save_export_xml(
                "technical",
                XML_V2,
            )

    assert original.read_bytes() == XML_V1.encode("utf-8")
    assert list(original.parent.iterdir()) == [original]


@pytest.mark.parametrize("export_type", ["technical", "tactical"])
def test_candidate_is_not_published_until_requested(
    export_files: ModuleType,
    export_type: str,
) -> None:
    """Writing a candidate must not immediately replace the export."""

    final_path = export_files.get_export_path(export_type)

    candidate = export_files.write_export_candidate(
        export_type,
        XML_V1,
    )

    assert candidate.is_file()
    assert candidate.parent == final_path.parent
    assert not final_path.exists()
    assert candidate.read_bytes() == XML_V1.encode("utf-8")

    result = export_files.publish_export_candidate(
        candidate,
        export_type,
    )

    assert result == final_path
    assert not candidate.exists()
    assert final_path.read_bytes() == XML_V1.encode("utf-8")

    replacement = export_files.write_export_candidate(
        export_type,
        XML_V2,
    )

    # The published file must still contain the previous XML.
    assert final_path.read_bytes() == XML_V1.encode("utf-8")

    export_files.publish_export_candidate(
        replacement,
        export_type,
    )

    assert final_path.read_bytes() == XML_V2.encode("utf-8")
    assert list(final_path.parent.iterdir()) == [final_path]


def test_failed_candidate_write_cleans_partial_file(
    export_files: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed candidate write must clean up its temporary file."""

    original = export_files.save_export_xml(
        "technical",
        XML_V1,
    )

    def fail_write_bytes(
        path: Path,
        content: bytes,
    ) -> int:
        with path.open("wb") as handle:
            handle.write(content[:8])

        raise OSError("Simulated candidate write failure")

    with monkeypatch.context() as patcher:
        patcher.setattr(
            Path,
            "write_bytes",
            fail_write_bytes,
        )

        with pytest.raises(
            OSError,
            match="Simulated candidate write",
        ):
            export_files.write_export_candidate(
                "technical",
                XML_V2,
            )

    assert original.read_bytes() == XML_V1.encode("utf-8")
    assert list(original.parent.iterdir()) == [original]
