#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
"""Restore Planetary Explorer Container App runtime settings after azd deploy."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
API_PORT = 8080


@dataclass(frozen=True)
class RuntimeProfile:
    """Container App ingress and health-probe settings."""

    probes: tuple[dict[str, object], ...]
    sticky_sessions: bool


RUNTIME_PROFILES: dict[str, RuntimeProfile] = {
    "api": RuntimeProfile(
        sticky_sessions=True,
        probes=(
            {
                "type": "Liveness",
                "httpGet": {"path": "/api/health", "port": API_PORT},
                "initialDelaySeconds": 30,
                "periodSeconds": 10,
                "timeoutSeconds": 5,
                "failureThreshold": 3,
            },
            {
                "type": "Readiness",
                "httpGet": {"path": "/api/health", "port": API_PORT},
                "initialDelaySeconds": 10,
                "periodSeconds": 5,
                "timeoutSeconds": 3,
                "failureThreshold": 3,
            },
        ),
    ),
    "geofm": RuntimeProfile(
        sticky_sessions=False,
        probes=(
            {
                "type": "Startup",
                "httpGet": {"path": "/health", "port": API_PORT},
                "initialDelaySeconds": 2,
                "periodSeconds": 5,
                "timeoutSeconds": 3,
                "failureThreshold": 12,
            },
            {
                "type": "Liveness",
                "httpGet": {"path": "/health", "port": API_PORT},
                "periodSeconds": 30,
                "timeoutSeconds": 3,
                "failureThreshold": 3,
            },
            {
                "type": "Readiness",
                "httpGet": {"path": "/ready", "port": API_PORT},
                "initialDelaySeconds": 5,
                "periodSeconds": 15,
                "timeoutSeconds": 10,
                "failureThreshold": 4,
            },
        ),
    ),
}

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """Configure concise command-line logging."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def create_parser() -> argparse.ArgumentParser:
    """Create the postdeploy command-line parser."""
    parser = argparse.ArgumentParser(
        description="Restore Container App ingress and health-probe settings."
    )
    parser.add_argument("--profile", choices=sorted(RUNTIME_PROFILES), default="api")
    parser.add_argument("--name", default="")
    parser.add_argument("--resource-group", default="")
    return parser


def run_az(arguments: list[str]) -> str:
    """Run Azure CLI and return its standard output."""
    executable = shutil.which("az")
    if executable is None:
        raise FileNotFoundError("Required command 'az' was not found.")
    result = subprocess.run(
        [executable, *arguments],
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout


def build_update_document(
    resource: dict[str, object],
    profile_name: Literal["api", "geofm"] = "api",
) -> dict[str, object]:
    """Build a writable Container Apps YAML document from an ARM response."""
    profile = RUNTIME_PROFILES[profile_name]
    properties = dict(resource["properties"])
    configuration = dict(properties["configuration"])
    ingress = dict(configuration["ingress"])
    ingress.pop("fqdn", None)
    ingress["targetPort"] = API_PORT
    if profile.sticky_sessions:
        ingress["stickySessions"] = {"affinity": "sticky"}
    else:
        ingress.pop("stickySessions", None)
    configuration["ingress"] = ingress

    template = dict(properties["template"])
    containers = [dict(container) for container in template["containers"]]
    if not containers:
        raise ValueError("Container App does not define an application container.")
    containers[0]["probes"] = list(profile.probes)
    template["containers"] = containers

    writable_properties: dict[str, object] = {
        "configuration": configuration,
        "template": template,
    }
    for key in ("environmentId", "managedEnvironmentId", "workloadProfileName"):
        value = properties.get(key)
        if value is not None:
            writable_properties[key] = value

    document: dict[str, object] = {"properties": writable_properties}
    identity = resource.get("identity")
    if isinstance(identity, dict) and identity.get("type"):
        writable_identity: dict[str, object] = {"type": identity["type"]}
        user_identities = identity.get("userAssignedIdentities")
        if isinstance(user_identities, dict):
            writable_identity["userAssignedIdentities"] = {
                str(resource_id): {} for resource_id in user_identities
            }
        document["identity"] = writable_identity
    return document


def configure_container_app(
    name: str,
    resource_group: str,
    profile_name: Literal["api", "geofm"] = "api",
) -> None:
    """Apply and verify a production ingress and probe configuration."""
    resource = json.loads(
        run_az(
            [
                "containerapp",
                "show",
                "--name",
                name,
                "--resource-group",
                resource_group,
                "--output",
                "json",
            ]
        )
    )
    document = build_update_document(resource, profile_name)

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            delete=False,
        ) as temporary_file:
            json.dump(document, temporary_file)
            temporary_path = Path(temporary_file.name)

        run_az(
            [
                "containerapp",
                "update",
                "--name",
                name,
                "--resource-group",
                resource_group,
                "--yaml",
                str(temporary_path),
                "--output",
                "none",
            ]
        )
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    verification = json.loads(
        run_az(
            [
                "containerapp",
                "show",
                "--name",
                name,
                "--resource-group",
                resource_group,
                "--query",
                "{port:properties.configuration.ingress.targetPort,probes:properties.template.containers[0].probes}",
                "--output",
                "json",
            ]
        )
    )
    expected_probe_types = {
        probe["type"] for probe in RUNTIME_PROFILES[profile_name].probes
    }
    probe_types = {probe.get("type") for probe in verification.get("probes", [])}
    if verification.get("port") != API_PORT or probe_types != expected_probe_types:
        raise RuntimeError(
            f"Container App {profile_name} runtime configuration verification failed."
        )


def wait_for_geofm_readiness(
    name: str,
    resource_group: str,
    attempts: int = 40,
) -> None:
    """Wait for GeoFM storage and queue permissions to become usable."""
    readiness_command = (
        "python -c \"import urllib.request; "
        "urllib.request.urlopen('http://localhost:8080/ready', timeout=10).read()\""
    )
    for attempt in range(1, attempts + 1):
        revision = run_az(
            [
                "containerapp",
                "show",
                "--name",
                name,
                "--resource-group",
                resource_group,
                "--query",
                "properties.latestRevisionName",
                "--output",
                "tsv",
            ]
        ).strip()
        try:
            run_az(
                [
                    "containerapp",
                    "exec",
                    "--name",
                    name,
                    "--resource-group",
                    resource_group,
                    "--revision",
                    revision,
                    "--command",
                    readiness_command,
                ]
            )
            return
        except subprocess.CalledProcessError:
            if attempt == attempts:
                break
            time.sleep(15)
    raise RuntimeError("GeoFM dependency readiness did not become healthy.")


def main() -> int:
    """Configure a Container App target from arguments or azd environment."""
    configure_logging()
    arguments = create_parser().parse_args()
    default_name_variable = (
        "AZURE_CONTAINER_APP_NAME"
        if arguments.profile == "api"
        else "AZURE_GEOFM_MCP_CONTAINER_APP_NAME"
    )
    name = (arguments.name or os.getenv(default_name_variable, "")).strip()
    resource_group = (
        arguments.resource_group or os.getenv("AZURE_RESOURCE_GROUP", "")
    ).strip()
    if not name or not resource_group:
        logger.error(
            "%s and AZURE_RESOURCE_GROUP are required.", default_name_variable
        )
        return EXIT_FAILURE

    try:
        configure_container_app(name, resource_group, arguments.profile)
        if arguments.profile == "geofm":
            wait_for_geofm_readiness(name, resource_group)
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as exc:
        logger.error("%s postdeploy configuration failed: %s", arguments.profile, exc)
        return EXIT_FAILURE

    logger.info("Configured %s ingress and health probes.", arguments.profile)
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())