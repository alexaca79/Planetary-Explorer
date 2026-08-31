# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
"""Tests for deployment-target adoption."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).parents[1] / "resolve_deployment_targets.py"
SPEC = importlib.util.spec_from_file_location("resolve_deployment_targets", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_given_legacy_resources_when_resolving_then_existing_names_and_plan_are_adopted() -> None:
    # Arrange
    container_apps = [
        {
            "name": "ca-web-xqpvvhppatu4i",
            "tags": {},
            "properties": {
                "environmentId": (
                    "/subscriptions/example/resourceGroups/rg-earthcopilot/"
                    "providers/Microsoft.App/managedEnvironments/cae-earthcopilot"
                ),
                "configuration": {
                    "ingress": {"fqdn": "ca-web-xqpvvhppatu4i.example.net"}
                }
            },
        }
    ]
    web_apps = [
        {
            "name": "app-earthcopilot-e1bb5a9c",
            "defaultHostName": "app-earthcopilot-e1bb5a9c.azurewebsites.net",
            "appServicePlanId": "/subscriptions/example/serverfarms/asp-earthcopilot",
            "tags": {},
        }
    ]

    # Act
    targets = MODULE.select_deployment_targets(
        container_apps=container_apps,
        web_apps=web_apps,
        environment_name="earthcopilot",
    )

    # Assert
    assert targets.api_container_app_name == "ca-web-xqpvvhppatu4i"
    assert targets.api_container_app_url == "https://ca-web-xqpvvhppatu4i.example.net"
    assert targets.container_apps_environment_name == "cae-earthcopilot"
    assert targets.frontend_web_app_name == "app-earthcopilot-e1bb5a9c"
    assert targets.frontend_app_service_plan_name == "asp-earthcopilot"
    assert targets.frontend_url == (
        "https://app-earthcopilot-e1bb5a9c.azurewebsites.net"
    )
    assert targets.deploy_api_container is False
    assert targets.deploy_frontend is False


def test_given_adopted_environment_when_writing_azd_then_exact_name_is_persisted(
    monkeypatch,
) -> None:
    # Arrange
    calls: list[list[str]] = []
    monkeypatch.setattr(MODULE, "run_command", lambda arguments: calls.append(arguments) or "")
    targets = MODULE.DeploymentTargets(
        api_container_app_name="api",
        container_apps_environment_name="cae-existing",
        deploy_api_container=False,
    )

    # Act
    MODULE.write_azd_environment(targets)

    # Assert
    assert [
        "azd",
        "env",
        "set",
        "EXISTING_CONTAINER_APPS_ENVIRONMENT_NAME",
        "cae-existing",
    ] in calls


def test_given_no_adopted_environment_when_writing_azd_then_stale_name_is_cleared(
    monkeypatch,
) -> None:
    # Arrange
    calls: list[list[str]] = []
    monkeypatch.setattr(MODULE, "run_command", lambda arguments: calls.append(arguments) or "")

    # Act
    MODULE.write_azd_environment(MODULE.DeploymentTargets())

    # Assert
    assert [
        "azd",
        "env",
        "set",
        "EXISTING_CONTAINER_APPS_ENVIRONMENT_NAME",
        "",
    ] in calls


def test_given_multiple_possible_apis_when_resolving_then_ambiguity_is_rejected() -> None:
    # Arrange
    container_apps = [
        {"name": "ca-earthcopilot-api", "tags": {}},
        {"name": "ca-web-xqpvvhppatu4i", "tags": {"azd-service-name": "web"}},
    ]

    # Act & Assert
    with pytest.raises(ValueError, match="ambiguous"):
        MODULE.select_deployment_targets(
            container_apps=container_apps,
            web_apps=[],
            environment_name="earthcopilot",
        )


def test_given_tagged_web_search_app_when_resolving_then_only_api_is_adopted() -> None:
    # Arrange
    container_apps = [
        {
            "name": "ca-earthcopilot-api",
            "tags": {"azd-service-name": "api"},
        },
        {
            "name": "ca-web-search-44gnuvaloryac",
            "tags": {"azd-service-name": "web-search-mcp"},
        },
    ]

    # Act
    targets = MODULE.select_deployment_targets(
        container_apps=container_apps,
        web_apps=[],
        environment_name="earthcopilot",
    )

    # Assert
    assert targets.api_container_app_name == "ca-earthcopilot-api"


def test_given_existing_web_app_and_wrong_plan_when_resolving_then_move_is_rejected() -> None:
    # Arrange
    web_apps = [
        {
            "name": "app-earthcopilot-e1bb5a9c",
            "defaultHostName": "app-earthcopilot-e1bb5a9c.azurewebsites.net",
            "appServicePlanId": "/subscriptions/example/serverfarms/asp-current",
            "tags": {"azd-service-name": "web"},
        }
    ]

    # Act & Assert
    with pytest.raises(ValueError, match="currently belongs"):
        MODULE.select_deployment_targets(
            container_apps=[],
            web_apps=web_apps,
            environment_name="earthcopilot",
            web_name="app-earthcopilot-e1bb5a9c",
            plan_name="asp-wrong",
        )


def test_given_fresh_targets_without_auth_mode_when_validating_then_configuration_is_rejected() -> None:
    # Arrange
    targets = MODULE.DeploymentTargets()

    # Act & Assert
    with pytest.raises(ValueError, match="exactly one"):
        MODULE.validate_fresh_authentication(targets, {})


def test_given_fresh_entra_mode_without_ids_when_validating_then_configuration_is_rejected() -> None:
    # Arrange
    targets = MODULE.DeploymentTargets()

    # Act & Assert
    with pytest.raises(ValueError, match="requires"):
        MODULE.validate_fresh_authentication(
            targets,
            {"ENABLE_AUTHENTICATION": "true"},
        )


def test_given_adopted_api_without_auth_inputs_when_validating_then_existing_mode_is_preserved() -> None:
    # Arrange
    targets = MODULE.DeploymentTargets(deploy_api_container=False)

    # Act
    MODULE.validate_fresh_authentication(targets, {})