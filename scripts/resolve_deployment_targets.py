#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
"""Resolve existing Planetary Explorer deployment targets before provisioning."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

EXIT_SUCCESS = 0
EXIT_FAILURE = 1

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeploymentTargets:
    """Exact resource names that Bicep should adopt."""

    api_container_app_name: str = ""
    api_container_app_url: str = ""
    container_apps_environment_name: str = ""
    frontend_web_app_name: str = ""
    frontend_app_service_plan_name: str = ""
    frontend_url: str = ""
    deploy_api_container: bool = True
    deploy_frontend: bool = True


def create_parser() -> argparse.ArgumentParser:
    """Create the target-resolution command-line parser."""
    parser = argparse.ArgumentParser(
        description="Adopt existing Planetary Explorer deployment targets."
    )
    parser.add_argument("--resource-group", default="")
    parser.add_argument("--environment-name", default="")
    parser.add_argument("--api-name", default="")
    parser.add_argument("--web-name", default="")
    parser.add_argument("--plan-name", default="")
    parser.add_argument("--frontend-url", default="")
    parser.add_argument("--write-azd-env", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    return parser


def run_command(arguments: list[str]) -> str:
    """Run a command and return its standard output."""
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


def _resource_name(resource: dict[str, object]) -> str:
    return str(resource.get("name", "")).strip()


def _service_tag(resource: dict[str, object]) -> str:
    tags = resource.get("tags")
    return str(tags.get("azd-service-name", "")) if isinstance(tags, dict) else ""


def _resolve_api_name(
    container_apps: list[dict[str, object]],
    environment_name: str,
    explicit_name: str,
) -> tuple[str, bool]:
    canonical_name = f"ca-{environment_name}-api" if environment_name else ""
    candidates = {
        _resource_name(app)
        for app in container_apps
        if _resource_name(app)
        and (
            _resource_name(app) == canonical_name
            or _service_tag(app) in {"api", "web"}
            or (
                not _service_tag(app)
                and _resource_name(app).startswith("ca-web-")
            )
        )
    }
    if explicit_name:
        conflicting = candidates - {explicit_name}
        if conflicting:
            raise ValueError(
                "The explicit API target conflicts with existing possible API targets: "
                + ", ".join(sorted(conflicting))
            )
        return explicit_name, any(
            _resource_name(app) == explicit_name for app in container_apps
        )
    if len(candidates) > 1:
        raise ValueError(
            "API Container App discovery is ambiguous: "
            + ", ".join(sorted(candidates))
        )
    resolved_name = next(iter(candidates), "")
    return resolved_name, bool(resolved_name)


def _api_url(container_apps: list[dict[str, object]], api_name: str) -> str:
    selected = next(
        (app for app in container_apps if _resource_name(app) == api_name),
        None,
    )
    if selected is None:
        return ""
    properties = selected.get("properties")
    configuration = properties.get("configuration") if isinstance(properties, dict) else None
    ingress = configuration.get("ingress") if isinstance(configuration, dict) else None
    fqdn = ingress.get("fqdn") if isinstance(ingress, dict) else None
    return f"https://{fqdn}" if fqdn else ""


def _container_apps_environment_name(
    container_apps: list[dict[str, object]],
    api_name: str,
) -> str:
    selected = next(
        (app for app in container_apps if _resource_name(app) == api_name),
        None,
    )
    properties = selected.get("properties") if isinstance(selected, dict) else None
    environment_id = (
        properties.get("environmentId") or properties.get("managedEnvironmentId")
        if isinstance(properties, dict)
        else ""
    )
    return str(environment_id).rstrip("/").rsplit("/", maxsplit=1)[-1]


def _plan_name(web_app: dict[str, object]) -> str:
    plan_id = str(web_app.get("appServicePlanId", "")).rstrip("/")
    return plan_id.rsplit("/", maxsplit=1)[-1] if plan_id else ""


def _resolve_frontend(
    web_apps: list[dict[str, object]],
    explicit_web_name: str,
    explicit_plan_name: str,
    explicit_frontend_url: str,
) -> tuple[str, str, str, bool]:
    if explicit_plan_name and not explicit_web_name:
        raise ValueError("A frontend plan name requires an exact frontend Web App name.")

    selected: dict[str, object] | None = None
    if explicit_web_name:
        selected = next(
            (app for app in web_apps if _resource_name(app) == explicit_web_name),
            None,
        )
        if selected is None and not explicit_plan_name:
            raise ValueError(
                "A new or unavailable frontend Web App requires an explicit App Service plan name."
            )
    else:
        tagged = [app for app in web_apps if _service_tag(app) == "web"]
        candidates = tagged if tagged else web_apps
        if len(candidates) > 1:
            raise ValueError(
                "Frontend Web App discovery is ambiguous: "
                + ", ".join(sorted(_resource_name(app) for app in candidates))
            )
        selected = candidates[0] if candidates else None

    web_name = explicit_web_name or (_resource_name(selected) if selected else "")
    current_plan_name = _plan_name(selected) if selected else ""
    if explicit_plan_name and current_plan_name and explicit_plan_name != current_plan_name:
        raise ValueError(
            f"Frontend Web App '{web_name}' currently belongs to plan "
            f"'{current_plan_name}', not '{explicit_plan_name}'."
        )
    plan_name = explicit_plan_name or current_plan_name

    default_hostname = str(selected.get("defaultHostName", "")) if selected else ""
    frontend_url = explicit_frontend_url or (
        f"https://{default_hostname}" if default_hostname else ""
    )
    return web_name, plan_name, frontend_url, selected is not None


def select_deployment_targets(
    *,
    container_apps: list[dict[str, object]],
    web_apps: list[dict[str, object]],
    environment_name: str,
    api_name: str = "",
    web_name: str = "",
    plan_name: str = "",
    frontend_url: str = "",
) -> DeploymentTargets:
    """Select exact deployment targets from an Azure resource inventory."""
    resolved_api_name, api_exists = _resolve_api_name(
        container_apps,
        environment_name,
        api_name,
    )
    (
        resolved_web_name,
        resolved_plan_name,
        resolved_frontend_url,
        frontend_exists,
    ) = _resolve_frontend(web_apps, web_name, plan_name, frontend_url)
    return DeploymentTargets(
        api_container_app_name=resolved_api_name,
        api_container_app_url=_api_url(container_apps, resolved_api_name),
        container_apps_environment_name=_container_apps_environment_name(
            container_apps,
            resolved_api_name,
        ),
        frontend_web_app_name=resolved_web_name,
        frontend_app_service_plan_name=resolved_plan_name,
        frontend_url=resolved_frontend_url,
        deploy_api_container=not api_exists,
        deploy_frontend=not frontend_exists,
    )


def resolve_from_azure(
    *,
    resource_group: str,
    environment_name: str,
    api_name: str = "",
    web_name: str = "",
    plan_name: str = "",
    frontend_url: str = "",
) -> DeploymentTargets:
    """Load a resource-group inventory and select exact deployment targets."""
    group_exists = run_command(
        ["az", "group", "exists", "--name", resource_group, "--output", "tsv"]
    ).lower() == "true"
    if not group_exists:
        return select_deployment_targets(
            container_apps=[],
            web_apps=[],
            environment_name=environment_name,
            api_name=api_name,
            web_name=web_name,
            plan_name=plan_name,
            frontend_url=frontend_url,
        )

    container_apps = json.loads(
        run_command(
            [
                "az",
                "containerapp",
                "list",
                "--resource-group",
                resource_group,
                "--output",
                "json",
            ]
        )
        or "[]"
    )
    web_apps = json.loads(
        run_command(
            [
                "az",
                "webapp",
                "list",
                "--resource-group",
                resource_group,
                "--output",
                "json",
            ]
        )
        or "[]"
    )
    return select_deployment_targets(
        container_apps=container_apps,
        web_apps=web_apps,
        environment_name=environment_name,
        api_name=api_name,
        web_name=web_name,
        plan_name=plan_name,
        frontend_url=frontend_url,
    )


def write_azd_environment(targets: DeploymentTargets) -> None:
    """Persist resolved target names into the selected azd environment."""
    values = {
        "API_CONTAINER_APP_NAME": targets.api_container_app_name,
        "API_CONTAINER_APP_URL": targets.api_container_app_url,
        "EXISTING_CONTAINER_APPS_ENVIRONMENT_NAME": (
            targets.container_apps_environment_name
        ),
        "AZURE_WEB_APP_NAME": targets.frontend_web_app_name,
        "AZURE_APP_SERVICE_PLAN_NAME": targets.frontend_app_service_plan_name,
        "FRONTEND_URL": targets.frontend_url,
        "DEPLOY_API_CONTAINER": str(targets.deploy_api_container).lower(),
        "DEPLOY_FRONTEND": str(targets.deploy_frontend).lower(),
    }
    for name, value in values.items():
        run_command(["azd", "env", "set", name, str(value)])
        logger.info("Adopting %s=%s", name, value)


def validate_fresh_authentication(
    targets: DeploymentTargets,
    environment: dict[str, str],
) -> None:
    """Require an explicit, complete auth mode for a newly provisioned API."""
    if not targets.deploy_api_container:
        return
    authentication_enabled = environment.get("ENABLE_AUTHENTICATION", "").lower() in {
        "1",
        "true",
        "yes",
    }
    public_demo_mode = environment.get("PUBLIC_DEMO_MODE", "").lower() in {
        "1",
        "true",
        "yes",
    }
    if authentication_enabled == public_demo_mode:
        raise ValueError(
            "Fresh deployments must set exactly one of ENABLE_AUTHENTICATION=true "
            "or PUBLIC_DEMO_MODE=true."
        )
    if authentication_enabled and not (
        environment.get("MICROSOFT_ENTRA_CLIENT_ID", "").strip()
        and environment.get("MICROSOFT_ENTRA_TENANT_ID", "").strip()
    ):
        raise ValueError(
            "ENABLE_AUTHENTICATION=true requires MICROSOFT_ENTRA_CLIENT_ID and "
            "MICROSOFT_ENTRA_TENANT_ID."
        )


def validate_feature_configuration(environment: dict[str, str]) -> None:
    """Reject incomplete create-or-reference settings before Azure writes."""
    boolean_settings = (
        "DEPLOY_AI_FOUNDRY", "DEPLOY_GPT5", "DEPLOY_GPT56", "DEPLOY_EMBEDDING_MODEL",
        "DEPLOY_CHAT_HISTORY", "ENABLE_FABRIC", "DEPLOY_FABRIC_CAPACITY",
        "ENABLE_MPC_PRO", "ENABLE_PRIVATE_ENDPOINTS", "DEPLOY_WEATHER_STUB",
        "FORECAST_AGENT_ENABLED", "DEPLOY_GEOFM", "DEPLOY_GEOFM_SERVICES",
        "DEPLOY_WEB_SEARCH_MCP", "GEOFM_ENABLED", "WEB_SEARCH_ENABLED",
        "ENABLE_AUTHENTICATION", "PUBLIC_DEMO_MODE",
    )
    for name in boolean_settings:
        if name in environment and environment[name].strip().lower() not in {"true", "false"}:
            raise ValueError(f"{name} must be true or false.")

    def enabled(name: str, default: str = "false") -> bool:
        return environment.get(name, default).strip().lower() == "true"

    def require(name: str) -> str:
        value = environment.get(name, "").strip()
        if not value:
            raise ValueError(f"{name} is required for the selected deployment option.")
        return value

    if not enabled("DEPLOY_AI_FOUNDRY", "true"):
        require("AZURE_OPENAI_ENDPOINT")
        require("EXISTING_AI_PROJECT_ENDPOINT")
    if enabled("DEPLOY_FABRIC_CAPACITY") and not enabled("ENABLE_FABRIC"):
        raise ValueError("DEPLOY_FABRIC_CAPACITY requires ENABLE_FABRIC=true.")
    if enabled("ENABLE_FABRIC"):
        require("FABRIC_WORKSPACE_ID")
        require("FABRIC_LAKEHOUSE_ID")
    if enabled("DEPLOY_FABRIC_CAPACITY"):
        administrators = json.loads(require("FABRIC_ADMINISTRATORS"))
        if not isinstance(administrators, list) or not administrators or not all(
            isinstance(value, str) and value.strip() for value in administrators
        ):
            raise ValueError("FABRIC_ADMINISTRATORS must be a nonempty JSON array of identities.")
    if enabled("ENABLE_MPC_PRO"):
        require("MPC_PRO_STAC_URL")
    if enabled("GEOFM_ENABLED") and not enabled("DEPLOY_GEOFM"):
        require("GEOFM_MCP_URL")
    if enabled("WEB_SEARCH_ENABLED") and not enabled("DEPLOY_WEB_SEARCH_MCP"):
        require("WEB_SEARCH_MCP_URL")
    if enabled("DEPLOY_GEOFM") or enabled("GEOFM_ENABLED"):
        api_key = require("GEOFM_MCP_API_KEY")
        owner_key = require("GEOFM_OWNER_SIGNING_KEY")
        if len(api_key) < 32 or len(owner_key) < 32:
            raise ValueError("GEOFM_MCP_API_KEY and GEOFM_OWNER_SIGNING_KEY require at least 32 characters.")
        if api_key == owner_key:
            raise ValueError("GeoFM API and owner-signing keys must be distinct.")
    if enabled("DEPLOY_WEB_SEARCH_MCP") or enabled("WEB_SEARCH_ENABLED"):
        if len(require("WEB_SEARCH_MCP_API_KEY")) < 32:
            raise ValueError("WEB_SEARCH_MCP_API_KEY requires at least 32 characters.")
        if enabled("DEPLOY_WEB_SEARCH_MCP") and not enabled("DEPLOY_AI_FOUNDRY", "true"):
            require("WEB_SEARCH_FOUNDRY_ACCOUNT_NAME")
            require("WEB_SEARCH_FOUNDRY_PROJECT_ENDPOINT")

    for name in (
        "AZURE_OPENAI_ENDPOINT", "EXISTING_AI_PROJECT_ENDPOINT", "MPC_PRO_STAC_URL",
        "AURORA_ENDPOINT_URL", "EARTH2_FCN_ENDPOINT_URL", "MAI_WEATHER_ENDPOINT_URL",
        "WEB_SEARCH_FOUNDRY_PROJECT_ENDPOINT", "FRONTEND_URL", "GEOFM_MCP_URL",
        "WEB_SEARCH_MCP_URL",
    ):
        value = environment.get(name, "").strip()
        if not value:
            continue
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError(f"{name} must be an absolute HTTPS URL.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(f"{name} must not contain credentials, a query, or a fragment.")
    try:
        pool_count = int(environment.get("ACR_AGENT_POOL_COUNT", "0"))
    except ValueError as error:
        raise ValueError("ACR_AGENT_POOL_COUNT must be a nonnegative integer.") from error
    if pool_count < 0:
        raise ValueError("ACR_AGENT_POOL_COUNT must be a nonnegative integer.")


def main(arguments: list[str] | None = None) -> int:
    """Resolve targets for a root script or azd preprovision hook."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parsed_arguments = create_parser().parse_args(arguments)
    if parsed_arguments.write_azd_env or parsed_arguments.validate_only:
        try:
            validate_feature_configuration(dict(os.environ))
        except ValueError as exc:
            logger.error("Deployment configuration is incomplete: %s", exc)
            return EXIT_FAILURE
    if parsed_arguments.validate_only:
        print(json.dumps({"configuration": "valid", "azure_resources_verified": False}))
        return EXIT_SUCCESS
    environment_name = (
        parsed_arguments.environment_name or os.getenv("AZURE_ENV_NAME", "")
    ).strip()
    resource_group = (
        parsed_arguments.resource_group
        or os.getenv("AZURE_RESOURCE_GROUP", "")
        or (f"rg-{environment_name}" if environment_name else "")
    ).strip()
    if not environment_name or not resource_group:
        logger.error("Environment name and resource group are required.")
        return EXIT_FAILURE
    if parsed_arguments.write_azd_env and resource_group != f"rg-{environment_name}":
        logger.error("This azd template targets rg-<AZURE_ENV_NAME>; the supplied resource group differs.")
        return EXIT_FAILURE

    try:
        targets = resolve_from_azure(
            resource_group=resource_group,
            environment_name=environment_name,
            api_name=parsed_arguments.api_name
            or os.getenv("API_CONTAINER_APP_NAME", "").strip(),
            web_name=parsed_arguments.web_name
            or os.getenv("AZURE_WEB_APP_NAME", "").strip(),
            plan_name=parsed_arguments.plan_name
            or os.getenv("AZURE_APP_SERVICE_PLAN_NAME", "").strip(),
            frontend_url=parsed_arguments.frontend_url
            or os.getenv("FRONTEND_URL", "").strip(),
        )
        if parsed_arguments.write_azd_env:
            validate_fresh_authentication(targets, dict(os.environ))
            write_azd_environment(targets)
        print(json.dumps(asdict(targets)))
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        logger.error("Deployment target resolution failed: %s", exc)
        return EXIT_FAILURE
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())