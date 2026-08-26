# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
"""Tests for conditional optional azd service deployment."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "deploy_optional_azd_services.py"
SPEC = importlib.util.spec_from_file_location("deploy_optional_azd_services", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_given_geofm_disabled_when_running_then_no_deployment_occurs(monkeypatch) -> None:
    # Arrange
    monkeypatch.delenv("AZURE_GEOFM_MCP_CONTAINER_APP_NAME", raising=False)
    monkeypatch.delenv("AZURE_GEOFM_WORKER_CONTAINER_APP_NAME", raising=False)
    calls: list[list[str]] = []
    monkeypatch.setattr(MODULE, "run_command", lambda arguments: calls.append(arguments))

    # Act
    result = MODULE.main()

    # Assert
    assert result == MODULE.EXIT_SUCCESS
    assert calls == []


def test_given_geofm_enabled_when_deploying_then_both_services_are_published(
    monkeypatch,
) -> None:
    # Arrange
    commands: list[list[str]] = []

    def fake_run_command(arguments: list[str]) -> str:
        commands.append(arguments)
        if arguments[:3] == ["az", "containerapp", "show"]:
            if "worker" in arguments:
                return '{"image":"registry/worker:latest","minReplicas":0}'
            return "registry/geofm:latest"
        return ""

    monkeypatch.setattr(MODULE, "run_command", fake_run_command)

    # Act
    MODULE.deploy_geofm("geofm", "worker", "rg-geofm")

    # Assert
    assert ["azd", "deploy", "geofm", "--no-prompt"] in commands
    assert ["azd", "deploy", "geofm-worker", "--no-prompt"] in commands