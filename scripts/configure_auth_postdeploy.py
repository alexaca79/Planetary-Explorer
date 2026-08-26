#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
"""Configure Planetary Explorer API and Web App authentication after azd up."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys

EXIT_SUCCESS = 0
EXIT_FAILURE = 1

logger = logging.getLogger(__name__)


def run_az(arguments: list[str], *, check: bool = True) -> str:
    """Run Azure CLI and return standard output."""
    executable = shutil.which("az")
    if executable is None:
        raise FileNotFoundError("Required command 'az' was not found.")
    result = subprocess.run(
        [executable, *arguments],
        capture_output=True,
        check=check,
        text=True,
    )
    return result.stdout.strip()


def _enabled(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def _web_url(web_app_name: str, resource_group: str) -> str:
    hostname = run_az(
        [
            "webapp",
            "show",
            "--name",
            web_app_name,
            "--resource-group",
            resource_group,
            "--query",
            "defaultHostName",
            "--output",
            "tsv",
        ]
    )
    if not hostname:
        raise RuntimeError(f"Web App '{web_app_name}' has no default hostname.")
    return f"https://{hostname}"


def _set_api_environment(
    api_name: str,
    resource_group: str,
    values: list[str],
) -> None:
    run_az(
        [
            "containerapp",
            "update",
            "--name",
            api_name,
            "--resource-group",
            resource_group,
            "--set-env-vars",
            *values,
            "--output",
            "none",
        ]
    )


def configure_public_mode(api_name: str, web_name: str, resource_group: str) -> None:
    """Configure an explicitly requested public demo deployment."""
    web_url = _web_url(web_name, resource_group)
    run_az(
        [
            "webapp",
            "auth",
            "update",
            "--name",
            web_name,
            "--resource-group",
            resource_group,
            "--enabled",
            "false",
            "--output",
            "none",
        ]
    )
    run_az(
        [
            "containerapp",
            "auth",
            "update",
            "--name",
            api_name,
            "--resource-group",
            resource_group,
            "--enabled",
            "false",
            "--output",
            "none",
        ]
    )
    _set_api_environment(
        api_name,
        resource_group,
        [
            "DISABLE_AUTH=true",
            "TRUST_EASYAUTH_HEADER=false",
            f"CORS_ORIGINS={web_url},http://localhost:5173",
        ],
    )
    run_az(
        [
            "containerapp",
            "ingress",
            "update",
            "--name",
            api_name,
            "--resource-group",
            resource_group,
            "--type",
            "external",
            "--output",
            "none",
        ]
    )
    api_auth = run_az(
        [
            "containerapp",
            "show",
            "--name",
            api_name,
            "--resource-group",
            resource_group,
            "--query",
            "properties.template.containers[0].env[?name=='DISABLE_AUTH'].value | [0]",
            "--output",
            "tsv",
        ]
    )
    api_trust_header = run_az(
        [
            "containerapp",
            "show",
            "--name",
            api_name,
            "--resource-group",
            resource_group,
            "--query",
            "properties.template.containers[0].env[?name=='TRUST_EASYAUTH_HEADER'].value | [0]",
            "--output",
            "tsv",
        ]
    )
    api_platform_auth = run_az(
        [
            "containerapp",
            "auth",
            "show",
            "--name",
            api_name,
            "--resource-group",
            resource_group,
            "--query",
            "properties.platform.enabled",
            "--output",
            "tsv",
        ]
    )
    api_external = run_az(
        [
            "containerapp",
            "show",
            "--name",
            api_name,
            "--resource-group",
            resource_group,
            "--query",
            "properties.configuration.ingress.external",
            "--output",
            "tsv",
        ]
    )
    web_auth = run_az(
        [
            "webapp",
            "auth",
            "show",
            "--name",
            web_name,
            "--resource-group",
            resource_group,
            "--query",
            "enabled",
            "--output",
            "tsv",
        ]
    )
    if (
        api_auth != "true"
        or api_trust_header != "false"
        or api_platform_auth == "true"
        or api_external != "true"
        or web_auth != "false"
    ):
        raise RuntimeError("Public authentication mode verification failed.")


def configure_entra_mode(
    api_name: str,
    web_name: str,
    resource_group: str,
    tenant_id: str,
    client_id: str,
) -> None:
    """Configure Microsoft Entra authentication on the SPA and API."""
    web_url = _web_url(web_name, resource_group)
    redirect_uri = f"{web_url}/.auth/login/aad/callback"
    run_az(
        [
            "containerapp",
            "ingress",
            "update",
            "--name",
            api_name,
            "--resource-group",
            resource_group,
            "--type",
            "internal",
            "--output",
            "none",
        ]
    )
    try:
        run_az(
            [
                "ad",
                "app",
                "update",
                "--id",
                client_id,
                "--web-redirect-uris",
                redirect_uri,
                "--output",
                "none",
            ]
        )
    except subprocess.CalledProcessError:
        logger.warning("Configure this Entra redirect URI manually: %s", redirect_uri)

    run_az(
        [
            "containerapp",
            "auth",
            "update",
            "--name",
            api_name,
            "--resource-group",
            resource_group,
            "--enabled",
            "false",
            "--output",
            "none",
        ]
    )
    _set_api_environment(
        api_name,
        resource_group,
        [
            f"AZURE_AD_TENANT_ID={tenant_id}",
            f"AZURE_AD_CLIENT_ID={client_id}",
            "DISABLE_AUTH=false",
            "TRUST_EASYAUTH_HEADER=false",
            f"CORS_ORIGINS={web_url},http://localhost:5173",
        ],
    )
    run_az(
        [
            "webapp",
            "auth",
            "update",
            "--name",
            web_name,
            "--resource-group",
            resource_group,
            "--enabled",
            "true",
            "--action",
            "LoginWithAzureActiveDirectory",
            "--aad-allowed-token-audiences",
            f"api://{client_id}",
            "--aad-client-id",
            client_id,
            "--aad-token-issuer-url",
            f"https://sts.windows.net/{tenant_id}/",
            "--token-store",
            "true",
            "--output",
            "none",
        ]
    )
    api_auth = run_az(
        [
            "containerapp",
            "show",
            "--name",
            api_name,
            "--resource-group",
            resource_group,
            "--query",
            "properties.template.containers[0].env[?name=='DISABLE_AUTH'].value | [0]",
            "--output",
            "tsv",
        ]
    )
    api_trust_header = run_az(
        [
            "containerapp",
            "show",
            "--name",
            api_name,
            "--resource-group",
            resource_group,
            "--query",
            "properties.template.containers[0].env[?name=='TRUST_EASYAUTH_HEADER'].value | [0]",
            "--output",
            "tsv",
        ]
    )
    api_tenant_id = run_az(
        [
            "containerapp",
            "show",
            "--name",
            api_name,
            "--resource-group",
            resource_group,
            "--query",
            "properties.template.containers[0].env[?name=='AZURE_AD_TENANT_ID'].value | [0]",
            "--output",
            "tsv",
        ]
    )
    api_client_id = run_az(
        [
            "containerapp",
            "show",
            "--name",
            api_name,
            "--resource-group",
            resource_group,
            "--query",
            "properties.template.containers[0].env[?name=='AZURE_AD_CLIENT_ID'].value | [0]",
            "--output",
            "tsv",
        ]
    )
    api_platform_auth = run_az(
        [
            "containerapp",
            "auth",
            "show",
            "--name",
            api_name,
            "--resource-group",
            resource_group,
            "--query",
            "properties.platform.enabled",
            "--output",
            "tsv",
        ]
    )
    web_auth = run_az(
        [
            "webapp",
            "auth",
            "show",
            "--name",
            web_name,
            "--resource-group",
            resource_group,
            "--query",
            "enabled",
            "--output",
            "tsv",
        ]
    )
    if (
        api_auth != "false"
        or api_trust_header != "false"
        or api_tenant_id != tenant_id
        or api_client_id != client_id
        or api_platform_auth == "true"
        or web_auth != "true"
    ):
        raise RuntimeError("Microsoft Entra authentication verification failed.")
    run_az(
        [
            "containerapp",
            "ingress",
            "update",
            "--name",
            api_name,
            "--resource-group",
            resource_group,
            "--type",
            "external",
            "--output",
            "none",
        ]
    )
    api_external = run_az(
        [
            "containerapp",
            "show",
            "--name",
            api_name,
            "--resource-group",
            resource_group,
            "--query",
            "properties.configuration.ingress.external",
            "--output",
            "tsv",
        ]
    )
    if api_external != "true":
        raise RuntimeError("API external ingress verification failed.")


def main() -> int:
    """Apply explicit auth mode or preserve an adopted environment."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    authentication_enabled = _enabled(os.getenv("ENABLE_AUTHENTICATION", ""))
    public_demo_mode = _enabled(os.getenv("PUBLIC_DEMO_MODE", ""))
    if not authentication_enabled and not public_demo_mode:
        logger.info("No authentication mode requested; preserving existing state.")
        return EXIT_SUCCESS
    if authentication_enabled and public_demo_mode:
        logger.error("ENABLE_AUTHENTICATION and PUBLIC_DEMO_MODE are mutually exclusive.")
        return EXIT_FAILURE

    api_name = os.getenv("AZURE_CONTAINER_APP_NAME", "").strip()
    web_name = os.getenv("AZURE_WEB_APP_NAME", "").strip()
    resource_group = os.getenv("AZURE_RESOURCE_GROUP", "").strip()
    if not api_name or not web_name or not resource_group:
        logger.error("API, Web App, and resource-group names are required.")
        return EXIT_FAILURE

    try:
        if public_demo_mode:
            configure_public_mode(api_name, web_name, resource_group)
        else:
            tenant_id = os.getenv("MICROSOFT_ENTRA_TENANT_ID", "").strip()
            client_id = os.getenv("MICROSOFT_ENTRA_CLIENT_ID", "").strip()
            if not tenant_id or not client_id:
                raise ValueError("Microsoft Entra tenant and client IDs are required.")
            configure_entra_mode(
                api_name,
                web_name,
                resource_group,
                tenant_id,
                client_id,
            )
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        logger.error("Authentication postdeploy configuration failed: %s", exc)
        return EXIT_FAILURE
    logger.info("Authentication postdeploy configuration completed.")
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())