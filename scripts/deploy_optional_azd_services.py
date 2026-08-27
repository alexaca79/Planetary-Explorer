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


def main() -> int:
    """Deploy configured optional services and skip disabled services."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    mcp_name = os.getenv("AZURE_GEOFM_MCP_CONTAINER_APP_NAME", "").strip()
    worker_name = os.getenv("AZURE_GEOFM_WORKER_CONTAINER_APP_NAME", "").strip()
    web_search_name = os.getenv(
        "AZURE_WEB_SEARCH_MCP_CONTAINER_APP_NAME", ""
    ).strip()
    resource_group = os.getenv("AZURE_RESOURCE_GROUP", "").strip()
    if not mcp_name and not worker_name and not web_search_name:
        logger.info("No optional services are provisioned; skipping deployment.")
        return EXIT_SUCCESS
    if not resource_group:
        logger.error("AZURE_RESOURCE_GROUP is required for optional deployments.")
        return EXIT_FAILURE
    if bool(mcp_name) != bool(worker_name):
        logger.error("GeoFM outputs are incomplete; refusing partial deployment.")
        return EXIT_FAILURE

    try:
        if web_search_name:
            deploy_web_search_mcp(web_search_name, resource_group)
        if mcp_name and worker_name:
            deploy_geofm(mcp_name, worker_name, resource_group)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        logger.error("Optional GeoFM deployment failed: %s", exc)
        return EXIT_FAILURE
    logger.info("Optional azd services deployed successfully.")
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())