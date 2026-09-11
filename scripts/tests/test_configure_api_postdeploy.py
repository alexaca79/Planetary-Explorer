# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
"""Tests for the Container App postdeploy configurator."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).parents[1] / "configure_api_postdeploy.py"
SPEC = importlib.util.spec_from_file_location("configure_api_postdeploy", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


@pytest.fixture(autouse=True)
def isolated_optional_configuration(monkeypatch):
    for name in (
        "DEPLOY_GEOFM", "DEPLOY_GEOFM_SERVICES", "GEOFM_ENABLED", "GEOFM_MCP_URL",
        "DEPLOY_WEB_SEARCH_MCP", "WEB_SEARCH_ENABLED", "WEB_SEARCH_MCP_URL",
        "DEPLOY_CHAT_HISTORY", "DEPLOY_WEATHER_STUB", "FORECAST_AGENT_ENABLED",
        "AZURE_WEATHER_STUB_CONTAINER_APP_NAME", "AURORA_ENDPOINT_URL",
        "EARTH2_FCN_ENDPOINT_URL", "MAI_WEATHER_ENDPOINT_URL", "MAI_WEATHER_SCORE_PATH",
        "ENABLE_FABRIC", "ENABLE_MPC_PRO", "DEPLOY_AI_FOUNDRY",
        "EXISTING_AI_PROJECT_ENDPOINT", "AZURE_OPENAI_ENDPOINT",
        "CHAT_HISTORY_REMOTE_URL", "AZURE_CHAT_HISTORY_REMOTE_URL",
        "AZURE_CHAT_MEMORY_SEARCH_ENDPOINT", "AZURE_CHAT_MEMORY_SEARCH_INDEX",
    ):
        monkeypatch.delenv(name, raising=False)


def test_given_cpu_settings_with_stale_outputs_when_reconciling_then_gpu_stays_disabled(monkeypatch) -> None:
    monkeypatch.setenv("DEPLOY_GEOFM", "false")
    monkeypatch.setenv("DEPLOY_WEB_SEARCH_MCP", "false")
    monkeypatch.setenv("DEPLOY_CHAT_HISTORY", "false")
    monkeypatch.setenv("FORECAST_AGENT_ENABLED", "false")
    monkeypatch.setenv("AZURE_GEOFM_MCP_URL", "https://old-gpu.internal")
    monkeypatch.setenv("AZURE_WEB_SEARCH_MCP_URL", "https://old-search.internal")
    monkeypatch.setenv("AZURE_WEATHER_STUB_URL", "https://old-weather.internal")
    commands: list[list[str]] = []
    monkeypatch.setattr(MODULE, "run_az", lambda arguments: commands.append(arguments) or "")

    MODULE.reconcile_api_optional_services("api", "rg")

    update = next(command for command in commands if command[:2] == ["containerapp", "update"])
    assert "GEOFM_ENABLED=false" in update
    assert "WEB_SEARCH_ENABLED=false" in update
    assert "PE_FEATURE_CHAT_HISTORY=false" in update
    assert "FORECAST_AGENT_ENABLED=0" in update
    assert not any(command[:3] == ["containerapp", "secret", "set"] for command in commands)


def test_given_existing_weather_overrides_when_reconciling_then_explicit_endpoints_win(monkeypatch) -> None:
    monkeypatch.delenv("AZURE_GEOFM_MCP_URL", raising=False)
    monkeypatch.delenv("AZURE_WEB_SEARCH_MCP_URL", raising=False)
    monkeypatch.setenv("AZURE_WEATHER_STUB_URL", "https://weather.internal")
    monkeypatch.setenv("AURORA_ENDPOINT_URL", "https://aurora.example")
    monkeypatch.setenv("MAI_WEATHER_ENDPOINT_URL", "https://mai.example")
    monkeypatch.setenv("MAI_WEATHER_SCORE_PATH", "/score")
    commands: list[list[str]] = []
    monkeypatch.setattr(MODULE, "run_az", lambda arguments: commands.append(arguments) or "")

    MODULE.reconcile_api_optional_services("api", "rg")

    update = next(command for command in commands if command[:2] == ["containerapp", "update"])
    assert "AURORA_ENDPOINT_URL=https://aurora.example" in update
    assert "EARTH2_FCN_ENDPOINT_URL=https://weather.internal" in update
    assert "MAI_WEATHER_ENDPOINT_URL=https://mai.example" in update
    assert "MAI_WEATHER_SCORE_PATH=/score" in update
    assert update[update.index("--name") + 1] == "api"


def test_given_private_history_bridge_when_reconciling_public_api_then_auth_and_remote_store_are_retained(monkeypatch):
    monkeypatch.setenv("PUBLIC_DEMO_MODE", "true")
    monkeypatch.setenv("AZURE_CHAT_HISTORY_REMOTE_URL", "https://history.example")
    monkeypatch.setenv("MICROSOFT_ENTRA_TENANT_ID", "tenant")
    monkeypatch.setenv("MICROSOFT_ENTRA_CLIENT_ID", "client")
    commands = []
    monkeypatch.setattr(MODULE, "run_az", lambda arguments: commands.append(arguments) or "")

    MODULE.reconcile_api_optional_services("api", "rg")

    update = next(command for command in commands if command[:2] == ["containerapp", "update"])
    assert "CHAT_HISTORY_STORE=remote" in update
    assert "CHAT_HISTORY_ALLOW_ANONYMOUS=false" in update
    assert "AZURE_AD_CLIENT_ID=client" in update
    assert "PE_FEATURE_CHAT_HISTORY=false" not in update


def test_given_memory_outputs_when_reconciling_then_dedicated_endpoint_and_index_are_wired(monkeypatch):
    monkeypatch.delenv("PUBLIC_DEMO_MODE", raising=False)
    monkeypatch.setenv("AZURE_CHAT_MEMORY_SEARCH_ENDPOINT", "https://memory.search.windows.net")
    monkeypatch.setenv("AZURE_CHAT_MEMORY_SEARCH_INDEX", "chat-memory-v1")
    commands = []
    monkeypatch.setattr(MODULE, "run_az", lambda arguments: commands.append(arguments) or "")

    MODULE.reconcile_api_optional_services("api", "rg")

    update = next(command for command in commands if command[:2] == ["containerapp", "update"])
    assert "CHAT_MEMORY_SEARCH_ENDPOINT=https://memory.search.windows.net" in update
    assert "CHAT_MEMORY_AUTO_SETUP=true" in update


def test_given_adopted_api_when_referencing_existing_services_then_inputs_are_wired(monkeypatch) -> None:
    monkeypatch.delenv("AZURE_GEOFM_MCP_URL", raising=False)
    monkeypatch.delenv("AZURE_WEB_SEARCH_MCP_URL", raising=False)
    monkeypatch.setenv("DEPLOY_AI_FOUNDRY", "false")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://models.example")
    monkeypatch.setenv("EXISTING_AI_PROJECT_ENDPOINT", "https://foundry.example/api/projects/existing")
    monkeypatch.setenv("ENABLE_FABRIC", "true")
    monkeypatch.setenv("FABRIC_WORKSPACE_ID", "workspace")
    monkeypatch.setenv("FABRIC_LAKEHOUSE_ID", "lakehouse")
    monkeypatch.setenv("ENABLE_MPC_PRO", "true")
    monkeypatch.setenv("MPC_PRO_STAC_URL", "https://catalog.example/stac")
    commands: list[list[str]] = []
    monkeypatch.setattr(MODULE, "run_az", lambda arguments: commands.append(arguments) or "")

    MODULE.reconcile_api_optional_services("api", "rg")

    update = next(command for command in commands if command[:2] == ["containerapp", "update"])
    assert "AZURE_OPENAI_ENDPOINT=https://models.example" in update
    assert "AZURE_AI_PROJECT_ENDPOINT=https://foundry.example/api/projects/existing" in update
    assert "PE_FEATURE_FABRIC=true" in update
    assert "FABRIC_LAKEHOUSE_WORKSPACE_ID=workspace" in update
    assert "FABRIC_LAKEHOUSE_ID=lakehouse" in update
    assert "MPC_PRO_STAC_URL=https://catalog.example/stac" in update
    assert update[update.index("--name") + 1] == "api"


def test_given_container_app_when_building_update_then_runtime_settings_are_restored() -> None:
    # Arrange
    resource = {
        "identity": {"type": "SystemAssigned"},
        "properties": {
            "environmentId": "/subscriptions/example/environments/example",
            "configuration": {"ingress": {"external": True, "targetPort": 80}},
            "template": {
                "containers": [
                    {
                        "name": "web",
                        "image": "example.azurecr.io/api:latest",
                        "env": [{"name": "DISABLE_AUTH", "value": "false"}],
                    }
                ],
                "scale": {"minReplicas": 1, "maxReplicas": 10},
            },
        },
    }

    # Act
    document = MODULE.build_update_document(resource)

    # Assert
    properties = document["properties"]
    assert properties["configuration"]["ingress"]["targetPort"] == 8080
    assert properties["configuration"]["ingress"]["stickySessions"] == {
        "affinity": "sticky"
    }
    probes = properties["template"]["containers"][0]["probes"]
    assert {probe["type"] for probe in probes} == {"Liveness", "Readiness"}
    assert {probe["httpGet"]["path"] for probe in probes} == {"/api/health"}
    assert properties["template"]["containers"][0]["env"] == [
        {"name": "DISABLE_AUTH", "value": "false"}
    ]


def test_given_geofm_profile_when_building_update_then_dependency_probe_is_restored() -> None:
    # Arrange
    resource = {
        "identity": {
            "type": "UserAssigned",
            "principalId": "read-only",
            "userAssignedIdentities": {"/identities/geofm": {}},
        },
        "properties": {
            "environmentId": "/subscriptions/example/environments/example",
            "configuration": {
                "ingress": {
                    "external": False,
                    "fqdn": "read-only.internal.example",
                    "targetPort": 8080,
                }
            },
            "template": {
                "revisionSuffix": "existing-revision",
                "containers": [{"name": "geofm", "image": "example/geofm:latest"}],
                "scale": {"minReplicas": 1, "maxReplicas": 3},
            },
        },
    }

    # Act
    document = MODULE.build_update_document(resource, "geofm")

    # Assert
    properties = document["properties"]
    assert "revisionSuffix" not in properties["template"]
    ingress = properties["configuration"]["ingress"]
    assert "fqdn" not in ingress
    assert "stickySessions" not in ingress
    probes = properties["template"]["containers"][0]["probes"]
    assert {probe["type"] for probe in probes} == {
        "Startup",
        "Liveness",
        "Readiness",
    }
    assert next(
        probe["httpGet"]["path"]
        for probe in probes
        if probe["type"] == "Readiness"
    ) == "/ready"
    assert document["identity"] == {
        "type": "UserAssigned",
        "userAssignedIdentities": {"/identities/geofm": {}},
    }


def test_given_web_search_profile_when_building_update_then_mcp_probes_are_restored() -> None:
    # Arrange
    resource = {
        "identity": {"type": "SystemAssigned"},
        "properties": {
            "environmentId": "/subscriptions/example/environments/example",
            "configuration": {"ingress": {"external": False, "targetPort": 8080}},
            "template": {
                "containers": [{"name": "web-search-mcp", "image": "example/search:latest"}],
                "scale": {"minReplicas": 1, "maxReplicas": 3},
            },
        },
    }

    # Act
    document = MODULE.build_update_document(resource, "web-search")

    # Assert
    probes = document["properties"]["template"]["containers"][0]["probes"]
    assert {probe["type"] for probe in probes} == {
        "Startup",
        "Liveness",
        "Readiness",
    }
    assert next(
        probe["httpGet"]["path"]
        for probe in probes
        if probe["type"] == "Readiness"
    ) == "/ready"


def test_given_cpu_weather_when_building_update_then_internal_health_probes_are_restored() -> None:
    resource = {
        "identity": {"type": "SystemAssigned"},
        "properties": {
            "environmentId": "/subscriptions/example/environments/example",
            "configuration": {"ingress": {"external": False, "targetPort": 80}},
            "template": {
                "containers": [{"name": "weather-stub", "image": "example/weather:release"}],
                "scale": {"minReplicas": 0, "maxReplicas": 2},
            },
        },
    }

    document = MODULE.build_update_document(resource, "weather")

    ingress = document["properties"]["configuration"]["ingress"]
    assert ingress["external"] is False
    assert ingress["targetPort"] == 8080
    probes = document["properties"]["template"]["containers"][0]["probes"]
    assert {probe["httpGet"]["path"] for probe in probes} == {"/health"}
    assert document["properties"]["template"]["scale"] == {"minReplicas": 0, "maxReplicas": 2}


def test_given_optional_outputs_when_reconciling_api_then_services_are_configured(
    monkeypatch,
) -> None:
    # Arrange
    commands: list[list[str]] = []
    monkeypatch.setenv("AZURE_COSMOS_CHAT_HISTORY_ENDPOINT", "https://cosmos.example")
    monkeypatch.setenv("AZURE_COSMOS_CHAT_HISTORY_DATABASE", "planetary-explorer")
    monkeypatch.setenv("AZURE_COSMOS_CHAT_HISTORY_CONTAINER", "chat-history")
    monkeypatch.setenv("AZURE_CHAT_ARTIFACT_BLOB_ENDPOINT", "https://blob.example")
    monkeypatch.setenv("AZURE_CHAT_ARTIFACT_CONTAINER", "chat-artifacts")
    monkeypatch.setenv("AZURE_WEB_SEARCH_MCP_URL", "https://search.internal")
    monkeypatch.setenv("DEPLOY_WEB_SEARCH_MCP", "true")
    monkeypatch.setenv("WEB_SEARCH_MCP_API_KEY", "w" * 32)
    monkeypatch.setenv("AZURE_WEATHER_STUB_URL", "https://weather.example")
    monkeypatch.delenv("PUBLIC_DEMO_MODE", raising=False)
    monkeypatch.delenv("AZURE_GEOFM_MCP_URL", raising=False)
    monkeypatch.setattr(MODULE, "run_az", lambda arguments: commands.append(arguments) or "")

    # Act
    MODULE.reconcile_api_optional_services("api", "rg")

    # Assert
    update = next(command for command in commands if command[:2] == ["containerapp", "update"])
    assert "PE_FEATURE_CHAT_HISTORY=true" in update
    assert "CHAT_HISTORY_STORE=cosmos" in update
    assert "WEB_SEARCH_ENABLED=true" in update
    assert "WEB_SEARCH_MCP_URL=https://search.internal" in update
    assert "WEB_SEARCH_MCP_API_KEY=secretref:web-search-mcp-api-key" in update
    assert "FORECAST_AGENT_ENABLED=1" in update
    assert "AURORA_ENDPOINT_URL=https://weather.example" in update
    assert "EARTH2_FCN_ENDPOINT_URL=https://weather.example" in update
    assert any(command[:3] == ["containerapp", "secret", "set"] for command in commands)


def test_given_public_demo_when_reconciling_api_then_history_endpoints_are_removed(
    monkeypatch,
) -> None:
    # Arrange
    commands: list[list[str]] = []
    monkeypatch.setenv("PUBLIC_DEMO_MODE", "true")
    monkeypatch.delenv("AZURE_WEB_SEARCH_MCP_URL", raising=False)
    monkeypatch.delenv("AZURE_GEOFM_MCP_URL", raising=False)
    monkeypatch.setattr(MODULE, "run_az", lambda arguments: commands.append(arguments) or "")

    # Act
    MODULE.reconcile_api_optional_services("api", "rg")

    # Assert
    update = commands[0]
    assert "PE_FEATURE_CHAT_HISTORY=false" in update
    assert "CHAT_HISTORY_STORE=disabled" in update
    assert "COSMOS_CHAT_ENDPOINT" in update
    assert "CHAT_ARTIFACT_BLOB_ENDPOINT" in update
    assert "--remove-env-vars" in update
    assert not any(value.endswith("=") for value in update)


def test_given_transient_rbac_delay_when_waiting_for_geofm_then_readiness_retries(
    monkeypatch,
) -> None:
    # Arrange
    execution_attempts = 0

    def fake_run_az(arguments: list[str]) -> str:
        nonlocal execution_attempts
        if arguments[1] == "show":
            if "{external:" in arguments[arguments.index("--query") + 1]:
                return json.dumps({"external": False, "fqdn": ""})
            return "geofm--revision"
        execution_attempts += 1
        if execution_attempts == 1:
            raise subprocess.CalledProcessError(1, arguments)
        return ""

    monkeypatch.setattr(MODULE, "run_az", fake_run_az)
    monkeypatch.setattr(MODULE.time, "sleep", lambda _seconds: None)

    # Act
    MODULE.wait_for_geofm_readiness("geofm", "rg-geofm", attempts=2)

    # Assert
    assert execution_attempts == 2


def test_given_external_geofm_when_waiting_then_https_readiness_is_used(
    monkeypatch,
) -> None:
    # Arrange
    executed_commands: list[list[str]] = []

    def fake_run_az(arguments: list[str]) -> str:
        executed_commands.append(arguments)
        return json.dumps({"external": True, "fqdn": "geofm.example"})

    class ReadyResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return b'{"ready":true}'

    monkeypatch.setattr(MODULE, "run_az", fake_run_az)
    monkeypatch.setattr(
        MODULE,
        "urlopen",
        lambda url, timeout: ReadyResponse(),
    )

    # Act
    MODULE.wait_for_geofm_readiness("geofm", "rg-geofm", attempts=1)

    # Assert
    assert len(executed_commands) == 1