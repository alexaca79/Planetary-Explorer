# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
"""Tests for conditional optional azd service deployment."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


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
    monkeypatch.delenv("AZURE_WEB_SEARCH_MCP_CONTAINER_APP_NAME", raising=False)
    calls: list[list[str]] = []
    monkeypatch.setattr(MODULE, "run_command", lambda arguments: calls.append(arguments))

    # Act
    result = MODULE.main()

    # Assert
    assert result == MODULE.EXIT_SUCCESS
    assert calls == []


@pytest.mark.parametrize("requested", [None, "false"])
def test_given_stale_gpu_outputs_when_not_requested_then_no_deployment_occurs(
    monkeypatch, requested: str | None,
) -> None:
    monkeypatch.delenv("DEPLOY_GEOFM", raising=False)
    if requested is not None:
        monkeypatch.setenv("DEPLOY_GEOFM", requested)
    monkeypatch.setenv("DEPLOY_WEB_SEARCH_MCP", "false")
    monkeypatch.setenv("DEPLOY_WEATHER_STUB", "false")
    monkeypatch.setenv("AZURE_GEOFM_MCP_CONTAINER_APP_NAME", "existing-control")
    monkeypatch.setenv("AZURE_GEOFM_WORKER_CONTAINER_APP_NAME", "existing-gpu")
    monkeypatch.setenv("AZURE_RESOURCE_GROUP", "rg-existing")
    calls: list[list[str]] = []
    monkeypatch.setattr(MODULE, "run_command", lambda arguments: calls.append(arguments) or "")

    result = MODULE.main()

    assert result == MODULE.EXIT_SUCCESS
    assert calls == []


def test_given_requested_service_without_resource_when_running_then_failure_is_explicit(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEPLOY_GEOFM", "false")
    monkeypatch.setenv("DEPLOY_WEB_SEARCH_MCP", "true")
    monkeypatch.setenv("DEPLOY_WEATHER_STUB", "false")
    monkeypatch.delenv("AZURE_WEB_SEARCH_MCP_CONTAINER_APP_NAME", raising=False)
    monkeypatch.setenv("AZURE_RESOURCE_GROUP", "rg-existing")
    calls: list[list[str]] = []
    monkeypatch.setattr(MODULE, "run_command", lambda arguments: calls.append(arguments) or "")

    result = MODULE.main()

    assert result == MODULE.EXIT_FAILURE
    assert calls == []


def test_given_cpu_weather_requested_when_running_then_only_adapter_is_published(monkeypatch) -> None:
    monkeypatch.setenv("DEPLOY_GEOFM", "false")
    monkeypatch.setenv("DEPLOY_WEB_SEARCH_MCP", "false")
    monkeypatch.setenv("DEPLOY_WEATHER_STUB", "true")
    monkeypatch.setenv("AZURE_WEATHER_STUB_CONTAINER_APP_NAME", "weather")
    monkeypatch.setenv("AZURE_RESOURCE_GROUP", "rg-cpu")
    commands: list[list[str]] = []

    def fake_run(arguments: list[str]) -> str:
        commands.append(arguments)
        if arguments[:3] == ["az", "containerapp", "show"]:
            return '{"image":"registry/weather:release","external":false,"port":8080}'
        return ""

    monkeypatch.setattr(MODULE, "run_command", fake_run)

    result = MODULE.main()

    assert result == MODULE.EXIT_SUCCESS
    assert [command for command in commands if command[:2] == ["azd", "deploy"]] == [
        ["azd", "deploy", "weather-stub", "--no-prompt"],
    ]


@pytest.mark.parametrize(
    "state",
    [
        '{"image":"mcr.microsoft.com/k8se/quickstart:latest","external":false,"port":8080}',
        '{"image":"registry/weather:release","external":true,"port":8080}',
        '{"image":"registry/weather:release","external":false,"port":80}',
    ],
)
def test_given_unusable_weather_when_verifying_then_deployment_fails(monkeypatch, state: str) -> None:
    monkeypatch.setattr(MODULE, "run_command", lambda arguments: state)

    with pytest.raises(RuntimeError):
        MODULE.deploy_weather_stub("weather", "rg-cpu")


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


def test_given_web_search_enabled_when_deploying_then_service_is_published(
    monkeypatch,
) -> None:
    # Arrange
    commands: list[list[str]] = []

    def fake_run_command(arguments: list[str]) -> str:
        commands.append(arguments)
        if arguments[:3] == ["az", "containerapp", "show"]:
            return "registry/web-search-mcp:latest"
        return ""

    monkeypatch.setattr(MODULE, "run_command", fake_run_command)

    # Act
    MODULE.deploy_web_search_mcp("web-search", "rg-search")

    # Assert
    assert ["azd", "deploy", "web-search-mcp", "--no-prompt"] in commands