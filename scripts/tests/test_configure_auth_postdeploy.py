# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
"""Tests for azd authentication postdeploy configuration."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "configure_auth_postdeploy.py"
SPEC = importlib.util.spec_from_file_location("configure_auth_postdeploy", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_given_no_explicit_mode_when_running_then_existing_auth_is_preserved(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.delenv("ENABLE_AUTHENTICATION", raising=False)
    monkeypatch.delenv("PUBLIC_DEMO_MODE", raising=False)
    calls: list[list[str]] = []
    monkeypatch.setattr(MODULE, "run_az", lambda arguments: calls.append(arguments))

    # Act
    result = MODULE.main()

    # Assert
    assert result == MODULE.EXIT_SUCCESS
    assert calls == []


def test_given_public_mode_when_configuring_then_api_and_web_auth_are_disabled(
    monkeypatch,
) -> None:
    # Arrange
    commands: list[list[str]] = []

    def fake_run_az(arguments: list[str], *, check: bool = True) -> str:
        del check
        commands.append(arguments)
        if arguments[:2] == ["webapp", "show"]:
            return "app.example.net"
        query = arguments[arguments.index("--query") + 1] if "--query" in arguments else ""
        if "DISABLE_AUTH" in query:
            return "true"
        if "TRUST_EASYAUTH_HEADER" in query:
            return "false"
        if "properties.platform.enabled" in query:
            return "false"
        if "properties.configuration.ingress.external" in query:
            return "true"
        if arguments[:3] == ["webapp", "auth", "show"]:
            return "false"
        return ""

    monkeypatch.setattr(MODULE, "run_az", fake_run_az)

    # Act
    MODULE.configure_public_mode("api", "web", "rg")

    # Assert
    assert ["webapp", "auth", "update"] == commands[1][:3]
    assert ["containerapp", "auth", "update"] == commands[2][:3]
    assert "DISABLE_AUTH=true" in commands[3]
    assert "--type" in commands[4] and "external" in commands[4]