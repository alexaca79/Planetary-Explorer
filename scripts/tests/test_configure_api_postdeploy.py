# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
"""Tests for the Container App postdeploy configurator."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "configure_api_postdeploy.py"
SPEC = importlib.util.spec_from_file_location("configure_api_postdeploy", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


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