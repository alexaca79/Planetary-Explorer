"""Prepare a tenant-specific optional sign-in registration without emitting secrets."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
import uuid


def run_az(arguments: list[str], *, manifest_error: bool = False) -> str:
    """Run Azure CLI without including secret arguments in failure messages."""
    executable = shutil.which("az")
    if not executable:
        raise RuntimeError("Azure CLI is required.")
    result = subprocess.run([executable, *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        detail = f" {result.stderr[:1500]}" if manifest_error else ""
        raise RuntimeError(f"Azure CLI {arguments[0]} {arguments[1]} failed with exit code {result.returncode}.{detail}")
    return result.stdout.strip()


def create_parser() -> argparse.ArgumentParser:
    """Expose preview-first identity configuration for an existing frontend."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--web-app-name", required=True)
    parser.add_argument("--application-name", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser


def main() -> int:
    """Reuse an exact registration or create it, storing a new secret only if needed."""
    arguments = create_parser().parse_args()
    if not arguments.apply:
        print(json.dumps({"mode": "preview", "application": arguments.application_name, "webApp": arguments.web_app_name, "secretOutput": False}))
        return 0
    if not os.getenv("AZURE_CONFIG_DIR") or not os.getenv("AZD_CONFIG_DIR"):
        raise RuntimeError("Tenant-isolated Azure configuration is required.")
    account = json.loads(run_az(["account", "show", "-o", "json"]))
    if account["tenantId"] != arguments.tenant_id or account["id"] != arguments.subscription_id:
        raise RuntimeError("Azure tenant/subscription does not match the requested deployment.")
    host = run_az(["webapp", "show", "-n", arguments.web_app_name, "-g", arguments.resource_group, "--query", "defaultHostName", "-o", "tsv"])
    redirect = f"https://{host}/.auth/login/aad/callback"
    if not urlsplit(redirect).hostname:
        raise RuntimeError("Frontend hostname was not resolved.")
    escaped_name = arguments.application_name.replace("'", "''")
    registrations = json.loads(run_az(["ad", "app", "list", "--filter", f"displayName eq '{escaped_name}'", "-o", "json"]))
    if len(registrations) > 1:
        raise RuntimeError("Multiple matching registrations; resolve the ambiguity before deployment.")
    if registrations:
        registration = registrations[0]
        if redirect not in registration.get("web", {}).get("redirectUris", []):
            raise RuntimeError("Existing registration does not match the target frontend; refusing to replace redirect URIs.")
    else:
        registration = json.loads(run_az([
            "ad", "app", "create", "--display-name", arguments.application_name,
            "--sign-in-audience", "AzureADMyOrg", "--web-redirect-uris", redirect,
            "--enable-id-token-issuance", "true", "-o", "json",
        ]))
        run_az(["ad", "sp", "create", "--id", registration["appId"], "-o", "none"])
    application_uri = f"api://{registration['appId']}"
    scopes = registration.get("api", {}).get("oauth2PermissionScopes", [])
    scope = next((item for item in scopes if item.get("value") == "user_impersonation"), None)
    if scope is None:
        scope = {
            "id": str(uuid.uuid4()), "value": "user_impersonation", "type": "User", "isEnabled": True,
            "adminConsentDisplayName": "Use your Planetary Explorer history",
            "adminConsentDescription": "Read and update the signed-in user's own chat history and memory.",
            "userConsentDisplayName": "Use your Planetary Explorer history",
            "userConsentDescription": "Read and update your own chat history and memory.",
        }
        scopes.append(scope)
    api = {**registration.get("api", {}), "requestedAccessTokenVersion": 2, "oauth2PermissionScopes": scopes}
    preauthorized = list(api.get("preAuthorizedApplications") or [])
    cli_client_id = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
    if not any(item.get("appId") == cli_client_id for item in preauthorized):
        preauthorized.append({"appId": cli_client_id, "delegatedPermissionIds": [scope["id"]]})
    patch = {"identifierUris": list(dict.fromkeys([*registration.get("identifierUris", []), application_uri])), "api": api}
    with tempfile.TemporaryDirectory(prefix="pe-history-identity-") as temporary:
        body_path = Path(temporary) / "registration.json"
        body_path.write_text(json.dumps(patch), encoding="utf-8")
        run_az(["rest", "--method", "PATCH", "--url", f"https://graph.microsoft.com/v1.0/applications/{registration['id']}", "--body", f"@{body_path}", "-o", "none"], manifest_error=True)
        api["preAuthorizedApplications"] = preauthorized
        body_path.write_text(json.dumps({"api": api}), encoding="utf-8")
        run_az(["rest", "--method", "PATCH", "--url", f"https://graph.microsoft.com/v1.0/applications/{registration['id']}", "--body", f"@{body_path}", "-o", "none"], manifest_error=True)
    settings = json.loads(run_az(["webapp", "config", "appsettings", "list", "-n", arguments.web_app_name, "-g", arguments.resource_group, "-o", "json"]))
    if not any(setting["name"] == "HISTORY_AUTH_CLIENT_SECRET" and setting.get("value") for setting in settings):
        secret = run_az([
            "ad", "app", "credential", "reset", "--id", registration["appId"],
            "--append", "--display-name", "History EasyAuth", "--years", "1",
            "--query", "password", "-o", "tsv",
        ])
        run_az([
            "webapp", "config", "appsettings", "set", "-n", arguments.web_app_name,
            "-g", arguments.resource_group, "--settings", f"HISTORY_AUTH_CLIENT_SECRET={secret}", "-o", "none",
        ])
    print(json.dumps({"applicationId": registration["appId"], "objectId": registration["id"], "tenantId": arguments.tenant_id, "redirectUri": redirect, "apiScope": f"{application_uri}/user_impersonation", "secretStored": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())