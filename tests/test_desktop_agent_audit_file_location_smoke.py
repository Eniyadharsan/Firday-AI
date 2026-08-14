"""Smoke test for the local Audit_Log file location.

Asserts that the Audit_Log stores its entries locally on the user's PC: the
backing file lives inside the agent's local data directory rather than a
remote/network location (Req 7.4).

The ``AuditLog`` resolves its data directory from the ``FRIDAY_DATA_DIR``
environment variable when set, otherwise falling back to the project-local
``.friday-data`` directory. This smoke test verifies both paths keep the audit
file on the local filesystem within the configured data directory.

Validates: Requirements 7.4
"""

from __future__ import annotations

from pathlib import Path

from friday.desktop_agent.audit import (
    DEFAULT_AUDIT_FILENAME,
    AuditLog,
    _default_data_dir,
)
from friday.desktop_agent.models import AuditEntry


def test_audit_file_resides_in_configured_local_data_directory(tmp_path: Path) -> None:
    """The audit file lives inside the local data directory it was given.

    Validates: Requirements 7.4
    """
    log = AuditLog(data_dir=tmp_path)

    # The backing file must sit directly inside the provided local directory.
    assert log.path.parent == tmp_path
    assert log.path.name == DEFAULT_AUDIT_FILENAME

    # It must be a concrete local filesystem path (absolute, no URL scheme).
    assert log.path.is_absolute()
    assert "://" not in str(log.path)


def test_audit_file_is_created_locally_on_append(tmp_path: Path) -> None:
    """Appending an entry materializes the file within the local directory.

    Validates: Requirements 7.4
    """
    log = AuditLog(data_dir=tmp_path)

    log.append(
        AuditEntry(
            timestamp="2024-01-01T00:00:00Z",
            event_type="execute",
            command_id="launch_app",
            outcome="success",
        )
    )

    # The file now exists locally under the data directory we configured.
    assert log.path.exists()
    assert log.path.is_file()
    assert log.path.parent == tmp_path


def test_default_data_directory_is_local(monkeypatch) -> None:
    """The default (no-override) audit location is the local ``.friday-data`` dir.

    Validates: Requirements 7.4
    """
    # Ensure no environment override so we exercise the local fallback.
    monkeypatch.delenv("FRIDAY_DATA_DIR", raising=False)

    data_dir = _default_data_dir()

    assert data_dir.name == ".friday-data"
    # The fallback resolves relative to the project source tree (local disk).
    assert data_dir.is_absolute()
    assert "://" not in str(data_dir)


def test_environment_override_keeps_audit_file_in_that_local_directory(
    tmp_path: Path, monkeypatch
) -> None:
    """FRIDAY_DATA_DIR override still keeps the audit file in a local directory.

    Validates: Requirements 7.4
    """
    override_dir = tmp_path / "friday-data-override"
    monkeypatch.setenv("FRIDAY_DATA_DIR", str(override_dir))

    log = AuditLog()

    assert log.path.parent == override_dir
    assert log.path.name == DEFAULT_AUDIT_FILENAME
    assert log.path.is_absolute()
