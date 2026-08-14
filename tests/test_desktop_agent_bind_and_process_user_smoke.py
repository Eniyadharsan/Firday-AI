"""Smoke tests for the Local_Channel bind address, process user, and credentials.

These smoke tests assert three foundational security properties of the
Desktop_Agent's Local_Channel loopback server (``friday/desktop_agent/server.py``):

1. The command interface is bound exclusively to the loopback interface
   ``127.0.0.1`` and can never be bound to a non-loopback (network-facing)
   address (Req 1.2, 11.1).
2. The agent runs as a local in-process server under the operating-system
   permissions of the invoking user, rather than spawning a separate or
   elevated process with a different identity (Req 1.1, 1.8).
3. No operating-system credential field is persisted: neither the shared data
   models nor the on-disk Audit_Log carry any password/credential/PIN field
   (Req 12.3).

They are deliberately lightweight (a single bind/start/stop cycle and a field
scan) and use fakes for the OS side-effect seam so nothing real happens on the
host.

Validates: Requirements 1.1, 1.2, 1.8, 11.1, 12.3
"""

from __future__ import annotations

import dataclasses
import getpass
import inspect
import ipaddress
import json
import os
import threading
from pathlib import Path
from typing import Any, Optional

import pytest

from friday.desktop_agent import models as models_module
from friday.desktop_agent.audit import AuditLog
from friday.desktop_agent.auth import SessionTokenAuthenticator
from friday.desktop_agent.authorization import AuthorizationManager
from friday.desktop_agent.executor import CommandExecutor
from friday.desktop_agent.models import AuditEntry
from friday.desktop_agent.server import (
    LOOPBACK_HOST,
    LoopbackCommandServer,
    is_loopback,
)
from friday.desktop_agent.state import AgentStateMachine

# Substrings that would indicate a stored operating-system credential (Req 12.3).
# ``token`` is intentionally excluded: a per-session auth token is not an OS
# credential and is required by design (Req 1.4).
_CREDENTIAL_FIELD_MARKERS = (
    "password",
    "passwd",
    "pwd",
    "credential",
    "passphrase",
    "secret",
    "pin",
)


class _FakeOSHandlers:
    """Recording stand-in for the OS side-effect seam (no real OS actions)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def launch_app(self, app_name: str) -> None:
        self.calls.append("launch_app")

    def open_path(self, path: str) -> None:
        self.calls.append("open_path")

    def open_browser(self, url: str) -> None:
        self.calls.append("open_browser")

    def set_volume(self, level: int) -> None:
        self.calls.append("set_volume")

    def media_action(self, action: str) -> None:
        self.calls.append("media_action")

    def type_text(self, text: str) -> None:
        self.calls.append("type_text")

    def window_action(self, action: str, target: Optional[str]) -> None:
        self.calls.append("window_action")

    def lock_workstation(self) -> None:
        self.calls.append("lock_workstation")


def _make_server(
    tmp_path: Path,
    host: str = LOOPBACK_HOST,
    port: int = 0,
) -> LoopbackCommandServer:
    """Build a loopback server wired to real components + a fake OS seam."""
    audit = AuditLog(data_dir=tmp_path)
    authenticator = SessionTokenAuthenticator()
    authorization = AuthorizationManager(audit_sink=audit.append)
    state = AgentStateMachine(audit_sink=audit.append)
    executor = CommandExecutor(handlers=_FakeOSHandlers(), audit_sink=audit.append)
    return LoopbackCommandServer(
        authenticator=authenticator,
        authorization=authorization,
        state=state,
        executor=executor,
        audit=audit,
        host=host,
        port=port,
    )


# -- 1. Bind address is loopback (127.0.0.1) ---------------------------------


def test_default_bind_host_is_ipv4_loopback() -> None:
    """The server's one-and-only bind host is ``127.0.0.1`` (Req 1.2, 11.1)."""
    assert LOOPBACK_HOST == "127.0.0.1"
    assert ipaddress.ip_address(LOOPBACK_HOST).is_loopback is True


def test_started_server_is_bound_to_loopback(tmp_path: Path) -> None:
    """Starting the server binds the socket to a loopback address (Req 1.2, 11.1)."""
    server = _make_server(tmp_path)
    try:
        host, port = server.start()
        # The bound host is a loopback address and matches the requested one.
        assert host == "127.0.0.1"
        assert ipaddress.ip_address(host).is_loopback is True
        # A concrete ephemeral port was assigned (port 0 -> OS-selected).
        assert isinstance(port, int) and port > 0
        assert server.bound_address == (host, port)
    finally:
        server.stop()


def test_server_refuses_to_bind_a_non_loopback_host(tmp_path: Path) -> None:
    """Constructing the server with a network-facing host is rejected (Req 1.2, 11.1)."""
    for network_host in ("0.0.0.0", "192.168.1.10", "10.0.0.5"):
        assert is_loopback(network_host) is False
        with pytest.raises(ValueError):
            _make_server(tmp_path, host=network_host)


def test_non_loopback_origins_are_not_accepted() -> None:
    """The origin gate treats network addresses as non-loopback (Req 11.1)."""
    assert is_loopback("127.0.0.1") is True
    assert is_loopback("::1") is True
    assert is_loopback("203.0.113.7") is False
    assert is_loopback(None) is False


# -- 2. Process runs under the invoking user ---------------------------------


def test_server_runs_in_process_under_the_invoking_user(tmp_path: Path) -> None:
    """The agent serves in-process as the invoking user, not a separate identity.

    ``start()`` runs the Local_Channel on a daemon thread inside the current
    process rather than spawning a subprocess or an elevated process, so the
    server inherits exactly the operating-system permissions of the invoking
    user (Req 1.1, 1.8). This smoke test confirms the process identity is
    unchanged across start/stop and that the serving thread belongs to this
    very process.
    """
    invoking_user = getpass.getuser()
    assert invoking_user  # a real invoking user exists

    pid_before = os.getpid()
    threads_before = {t.ident for t in threading.enumerate()}

    server = _make_server(tmp_path)
    try:
        server.start()

        # Same process: no subprocess/elevated process was spawned to serve.
        assert os.getpid() == pid_before
        # The invoking user identity is unchanged (no user switch / drop).
        assert getpass.getuser() == invoking_user

        # A new serving thread was created within THIS process.
        threads_after = {t.ident for t in threading.enumerate()}
        new_threads = threads_after - threads_before
        assert new_threads, "expected an in-process serving thread"

        serving = [
            t
            for t in threading.enumerate()
            if t.name == "friday-desktop-agent-loopback"
        ]
        assert serving, "loopback server thread should be running in-process"
        assert serving[0].daemon is True
        assert serving[0].is_alive() is True
    finally:
        server.stop()

    # After stopping, the process identity is still the invoking user's.
    assert os.getpid() == pid_before
    assert getpass.getuser() == invoking_user


# -- 3. No credential field is persisted -------------------------------------


def _field_names_of_dataclasses(module: Any) -> list[tuple[str, str]]:
    """Collect ``(dataclass_name, field_name)`` pairs for every model dataclass."""
    pairs: list[tuple[str, str]] = []
    for _name, obj in inspect.getmembers(module, inspect.isclass):
        if obj.__module__ != module.__name__:
            continue
        if not dataclasses.is_dataclass(obj):
            continue
        for f in dataclasses.fields(obj):
            pairs.append((obj.__name__, f.name))
    return pairs


def test_no_data_model_declares_a_credential_field() -> None:
    """No shared data model carries an OS-credential field (Req 12.3).

    The Desktop_Agent must not store operating-system credentials, so none of
    the persisted/exchanged models may declare a password/credential/PIN field.
    """
    offenders = [
        (cls, field_name)
        for cls, field_name in _field_names_of_dataclasses(models_module)
        for marker in _CREDENTIAL_FIELD_MARKERS
        if marker in field_name.lower()
    ]
    assert offenders == [], f"credential-like model fields found: {offenders}"


def test_persisted_audit_log_contains_no_credential_fields(tmp_path: Path) -> None:
    """The on-disk Audit_Log never persists an OS-credential field (Req 12.3).

    Exercises the recorders for representative events (execute, decline,
    authorize, revoke, kill-switch, lockout) and then scans every persisted
    JSON key to ensure no credential-like field was written to local storage.
    """
    audit = AuditLog(data_dir=tmp_path)

    audit.record_execution("launch_app", {"app_name": "notepad"}, outcome="success")
    audit.record_decline("open_path", reason="parameter validation failed")
    audit.record_authorization(scope="launch_app")
    audit.record_revocation()
    audit.record_kill_switch()
    audit.record_lockout()
    audit.append(
        AuditEntry(
            timestamp="2024-01-01T00:00:00Z",
            event_type="execute",
            command_id="lock_pc",
            outcome="success",
        )
    )

    assert audit.path.exists()

    def _keys(obj: Any) -> set[str]:
        found: set[str] = set()
        if isinstance(obj, dict):
            for key, value in obj.items():
                found.add(str(key))
                found |= _keys(value)
        elif isinstance(obj, list):
            for item in obj:
                found |= _keys(item)
        return found

    persisted_keys: set[str] = set()
    with audit.path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            persisted_keys |= _keys(json.loads(line))

    offenders = [
        key
        for key in persisted_keys
        for marker in _CREDENTIAL_FIELD_MARKERS
        if marker in key.lower()
    ]
    assert offenders == [], f"credential-like keys persisted to audit log: {offenders}"
