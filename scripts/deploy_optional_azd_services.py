#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
"""Deploy optional azd services that were provisioned by feature flags."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys

EXIT_SUCCESS = 0
EXIT_FAILURE = 1

logger = logging.getLogger(__name__)


def run_command(arguments: list[str]) -> str:
    """Run a required command and return standard output."""
    executable = shutil.which(arguments[0])
    if executable is None:
        raise FileNotFoundError(f"Required command '{arguments[0]}' was not found.")
    result = subprocess.run(
        [executable, *arguments[1:]],
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout.strip()


def deploy_geofm(mcp_name: str, worker_name: str, resource_group: str) -> None:
    """Deploy and verify both GeoFM azd services."""
    run_command(["azd", "deploy", "geofm", "--no-prompt"])
    run_command(["azd", "deploy", "geofm-worker", "--no-prompt"])

    mcp_image = run_command(
        [
            "az",
            "containerapp",
            "show",
            "--name",
            mcp_name,
            "--resource-group",
            resource_group,
            "--query",
            "properties.template.containers[0].image",
            "--output",
            "tsv",
        ]
    )
    worker_state = json.loads(
        run_command(
        [
            "az",
            "containerapp",
            "show",
            "--name",
            worker_name,
            "--resource-group",
            resource_group,
            "--query",
            "{image:properties.template.containers[0].image,minReplicas:properties.template.scale.minReplicas}",
            "--output",
            "json",
        ]
        )
    )
    if "mcr.microsoft.com/dotnet/samples" in mcp_image:
        raise RuntimeError("GeoFM MCP still uses its bootstrap image.")
    if "mcr.microsoft.com/azuredocs/containerapps-helloworld" in str(
        worker_state.get("image", "")
    ):
        raise RuntimeError("GeoFM worker still uses its bootstrap image.")
    if worker_state.get("minReplicas") != 0:
        raise RuntimeError("GeoFM worker is not configured for scale-to-zero.")


def deploy_web_search_mcp(name: str, resource_group: str) -> None:
    """Deploy and verify the optional Azure Web Search MCP service."""
    run_command(["azd", "deploy", "web-search-mcp", "--no-prompt"])
    image = run_command(
        [
            "az",
            "containerapp",
            "show",
            "--name",
            name,
            "--resource-group",
            resource_group,
            "--query",
            "properties.template.containers[0].image",
            "--output",
            "tsv",
        ]
    )
    if "mcr.microsoft.com/dotnet/samples" in image:
        raise RuntimeError("Web Search MCP still uses its bootstrap image.")


def deploy_weather_stub(name: str, resource_group: str) -> None:
    """Publish the CPU weather adapter and verify its internal runtime."""
    run_command(["azd", "deploy", "weather-stub", "--no-prompt"])
    state = json.loads(run_command([
        "az", "containerapp", "show", "--name", name,
        "--resource-group", resource_group,
        "--query", "{image:properties.template.containers[0].image,external:properties.configuration.ingress.external,port:properties.configuration.ingress.targetPort}",
        "--output", "json",
    ]))
    if not state.get("image") or str(state["image"]).startswith("mcr.microsoft.com/"):
        raise RuntimeError("Weather adapter still uses a bootstrap image.")
    if state.get("external") is not False or state.get("port") != 8080:
        raise RuntimeError("Weather adapter must use internal HTTPS ingress on port 8080.")


def main() -> int:
    """Deploy configured optional services and skip disabled services."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    geofm_requested = os.getenv("DEPLOY_GEOFM", "false").strip().casefold() == "true"
    geofm_services = os.getenv("DEPLOY_GEOFM_SERVICES", "true").strip().casefold() == "true"
    geofm_requested = geofm_requested and geofm_services
    web_search_requested = os.getenv("DEPLOY_WEB_SEARCH_MCP", "false").strip().casefold() == "true"
    weather_requested = os.getenv("DEPLOY_WEATHER_STUB", "false").strip().casefold() == "true"
    weather_name = os.getenv("AZURE_WEATHER_STUB_CONTAINER_APP_NAME", "").strip()
    mcp_name = os.getenv("AZURE_GEOFM_MCP_CONTAINER_APP_NAME", "").strip()
    worker_name = os.getenv("AZURE_GEOFM_WORKER_CONTAINER_APP_NAME", "").strip()
    web_search_name = os.getenv(
        "AZURE_WEB_SEARCH_MCP_CONTAINER_APP_NAME", ""
    ).strip()
    resource_group = os.getenv("AZURE_RESOURCE_GROUP", "").strip()
    if not geofm_requested and not web_search_requested and not weather_requested:
        logger.info("No optional services are requested; skipping deployment.")
        return EXIT_SUCCESS
    if not resource_group:
        logger.error("AZURE_RESOURCE_GROUP is required for optional deployments.")
        return EXIT_FAILURE
    if geofm_requested and (not mcp_name or not worker_name):
        logger.error("GeoFM was requested but its resource outputs are incomplete.")
        return EXIT_FAILURE
    if web_search_requested and not web_search_name:
        logger.error("Web Search was requested but its resource output is missing.")
        return EXIT_FAILURE
    if weather_requested and not weather_name:
        logger.error("CPU weather was requested but its resource output is missing.")
        return EXIT_FAILURE

    try:
        if weather_requested:
            deploy_weather_stub(weather_name, resource_group)
        if web_search_requested:
            deploy_web_search_mcp(web_search_name, resource_group)
        if geofm_requested:
            deploy_geofm(mcp_name, worker_name, resource_group)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        logger.error("Optional service deployment failed: %s", exc)
        return EXIT_FAILURE
    logger.info("Optional azd services deployed successfully.")
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())