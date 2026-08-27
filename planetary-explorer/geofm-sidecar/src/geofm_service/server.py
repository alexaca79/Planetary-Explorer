"""Authenticated Streamable HTTP MCP control plane for durable GeoFM runs."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlparse
from uuid import UUID

import anyio
import uvicorn
from azure.identity import DefaultAzureCredential
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    ContainerClient,
    generate_blob_sas,
)
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .contracts import EvidenceEnvelope, EvidenceReference, EvidenceRung, RunArtifact
from .jobs import (
    AzureQueueDispatcher,
    BlobRunRepository,
    CompareEpochsRequest,
    NoopDispatcher,
    RunService,
    SQLiteRunRepository,
)
from .policy import PLAN_AURA_HLS
from .stac import get_catalog

mcp = FastMCP(
    "planetary-explorer-geofm",
    instructions=(
        "Submit durable GeoFM runs and return immediately. Poll run state; never send "
        "raster arrays or full embeddings into language-model context."
    ),
    host="0.0.0.0",
    port=int(os.getenv("PORT", "8080")),
    streamable_http_path="/mcp",
    json_response=True,
    stateless_http=True,
)
UTC = timezone.utc

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
SUBMIT = ToolAnnotations(
    title="Submit PlanAura Epoch Comparison",
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
CANCEL = ToolAnnotations(
    title="Cancel GeoFM Run",
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)
RETRY = ToolAnnotations(
    title="Retry Failed GeoFM Run",
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)


def _validate_owner_signature(
    action: str,
    requested_by: str,
    resource: object,
    expires_at: int,
    nonce: str,
    signature: str,
) -> None:
    key = (os.getenv("GEOFM_OWNER_SIGNING_KEY") or "").encode("utf-8")
    if len(key) < 32:
        raise PermissionError("GeoFM owner signing is not configured.")
    now = int(time.time())
    if expires_at < now or expires_at > now + 300:
        raise PermissionError("GeoFM owner signature has expired or is invalid.")
    if len(nonce) != 32:
        raise PermissionError("GeoFM owner signature nonce is invalid.")
    payload = json.dumps(
        [
            action,
            requested_by,
            _canonical_owner_resource(resource),
            expires_at,
            nonce,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    expected = hmac.new(key, payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise PermissionError("GeoFM owner signature is invalid.")


def _canonical_owner_resource(value: object, *, key: str | None = None) -> object:
    if isinstance(value, dict):
        return {
            child_key: _canonical_owner_resource(child, key=child_key)
            for child_key, child in value.items()
        }
    if isinstance(value, list):
        return [_canonical_owner_resource(child) for child in value]
    if key == "run_id" and isinstance(value, str):
        return str(UUID(value))
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return format(float(value), ".17g")
    return value


def _readiness_snapshot(owner_signing_key: str) -> dict[str, object]:
    checks: dict[str, bool] = {
        "owner_signing": len(owner_signing_key) >= 32,
    }
    blob_url = (os.getenv("AZURE_STORAGE_BLOB_ENDPOINT") or "").strip()
    queue_url = (os.getenv("AZURE_STORAGE_QUEUE_ENDPOINT") or "").strip()
    if not blob_url and not queue_url:
        checks["local_storage"] = True
        return {"ready": all(checks.values()), "checks": checks}
    if not blob_url or not queue_url:
        checks["storage_configuration"] = False
        return {"ready": False, "checks": checks}

    from azure.storage.queue import QueueClient

    credential = DefaultAzureCredential()
    container = ContainerClient(
        account_url=blob_url,
        container_name=os.getenv("GEOFM_CONTAINER_NAME", "geofm"),
        credential=credential,
    )
    work_queue = QueueClient(
        account_url=queue_url,
        queue_name=os.getenv("GEOFM_QUEUE_NAME", "geofm-jobs"),
        credential=credential,
    )
    poison_queue = QueueClient(
        account_url=queue_url,
        queue_name=os.getenv("GEOFM_POISON_QUEUE_NAME", "geofm-poison"),
        credential=credential,
    )
    blob_service = BlobServiceClient(account_url=blob_url, credential=credential)
    try:
        checks["blob_container"] = bool(container.exists())
        work_queue.get_queue_properties()
        checks["work_queue"] = True
        poison_queue.get_queue_properties()
        checks["poison_queue"] = True
        start = datetime.now(UTC) - timedelta(minutes=1)
        blob_service.get_user_delegation_key(start, start + timedelta(minutes=6))
        checks["blob_delegation"] = True
    except Exception:
        checks["dependencies"] = False
    finally:
        container.close()
        work_queue.close()
        poison_queue.close()
        blob_service.close()
        credential.close()
    return {"ready": all(checks.values()), "checks": checks}


def _readiness_response(snapshot: dict[str, object]) -> JSONResponse:
    ready = bool(snapshot.get("ready"))
    return JSONResponse(
        {
            "status": "ready" if ready else "degraded",
            **snapshot,
        },
        status_code=200 if ready else 503,
    )


def _sign_artifacts(artifacts: list[RunArtifact]) -> list[RunArtifact]:
    """Return five-minute read-only user-delegation URLs for private artifacts."""
    if not artifacts:
        return []
    account_url = (os.getenv("AZURE_STORAGE_BLOB_ENDPOINT") or "").rstrip("/")
    account_host = (urlparse(account_url).hostname or "").casefold()
    if not account_host:
        return artifacts
    account_name = account_host.split(".", 1)[0]
    credential = DefaultAzureCredential()
    service = BlobServiceClient(account_url=account_url, credential=credential)
    start = datetime.now(UTC) - timedelta(minutes=1)
    expiry = start + timedelta(minutes=6)
    try:
        delegation_key = service.get_user_delegation_key(start, expiry)
        signed: list[RunArtifact] = []
        for artifact in artifacts:
            parsed = urlparse(artifact.uri)
            if (
                parsed.scheme != "https"
                or (parsed.hostname or "").casefold() != account_host
            ):
                raise PermissionError("GeoFM artifact host does not match configured storage.")
            container_name, separator, blob_name = parsed.path.lstrip("/").partition("/")
            if not separator or container_name != os.getenv("GEOFM_CONTAINER_NAME", "geofm"):
                raise PermissionError("GeoFM artifact path is outside the configured container.")
            sas = generate_blob_sas(
                account_name=account_name,
                container_name=container_name,
                blob_name=blob_name,
                user_delegation_key=delegation_key,
                permission=BlobSasPermissions(read=True),
                start=start,
                expiry=expiry,
            )
            signed.append(
                artifact.model_copy(
                    update={
                        "uri": f"{account_url}/{quote(container_name)}/"
                        f"{quote(blob_name, safe='/')}?{sas}"
                    }
                )
            )
        return signed
    finally:
        service.close()
        credential.close()


@mcp.tool(name="geofm_list_models", annotations=READ_ONLY, structured_output=True)
async def geofm_list_models() -> EvidenceEnvelope:
    """List exact GeoFM revisions, capabilities, and deployment gates."""
    descriptor = PLAN_AURA_HLS.model_dump(mode="json")
    return EvidenceEnvelope(
        evidence_rung=EvidenceRung.CATALOGUE,
        summary="One pinned GeoFM profile is available: PlanAura HLS.",
        payload={"models": [descriptor]},
        evidence=[
            EvidenceReference(kind="calculation", identifier="geofm_model_registry")
        ],
    )


@mcp.tool(name="geofm_compare_epochs", annotations=SUBMIT, structured_output=True)
async def geofm_compare_epochs(
    request: CompareEpochsRequest,
    owner_signature: str,
    owner_signature_expires_at: int,
    owner_signature_nonce: str,
) -> EvidenceEnvelope:
    """Validate, persist, and enqueue a bi-temporal PlanAura comparison."""
    _validate_owner_signature(
        "submit",
        request.requested_by,
        request.model_dump(mode="json"),
        owner_signature_expires_at,
        owner_signature_nonce,
        owner_signature,
    )
    record, created = await anyio.to_thread.run_sync(get_service().submit, request)
    return EvidenceEnvelope(
        evidence_rung=EvidenceRung.CATALOGUE,
        summary=f"GeoFM run {record.run_id} is {record.status}.",
        payload={
            "run_id": str(record.run_id),
            "status": record.status,
            "created": created,
            "attempt": record.attempt,
            "model": record.selected_model["model_id"],
            "model_revision": record.selected_model["model_revision"],
            "warnings": record.warnings,
        },
        evidence=[
            EvidenceReference(kind="stac_item", identifier=request.item_id_epoch_a),
            EvidenceReference(kind="stac_item", identifier=request.item_id_epoch_b),
            EvidenceReference(kind="calculation", identifier=str(record.run_id)),
        ],
        warnings=record.warnings,
    )


@mcp.tool(name="geofm_get_run", annotations=READ_ONLY, structured_output=True)
async def geofm_get_run(
    run_id: UUID,
    requested_by: str,
    owner_signature: str,
    owner_signature_expires_at: int,
    owner_signature_nonce: str,
) -> EvidenceEnvelope:
    """Return durable state and validated results for one GeoFM run."""
    _validate_owner_signature(
        "get",
        requested_by,
        {"run_id": str(run_id)},
        owner_signature_expires_at,
        owner_signature_nonce,
        owner_signature,
    )
    record = await anyio.to_thread.run_sync(
        get_service().get_for_owner,
        run_id,
        requested_by,
    )
    artifacts = await anyio.to_thread.run_sync(_sign_artifacts, record.artifacts)
    rung = EvidenceRung.VECTOR if record.features else (
        EvidenceRung.STATISTIC if record.statistics else EvidenceRung.CATALOGUE
    )
    references = [
        EvidenceReference(
            kind="artefact",
            identifier=artifact.kind,
            uri=artifact.uri,
            sha256=artifact.sha256,
        )
        for artifact in artifacts
    ]
    if not references:
        references.append(EvidenceReference(kind="calculation", identifier=str(run_id)))
    return EvidenceEnvelope(
        evidence_rung=rung,
        summary=f"GeoFM run {record.run_id} is {record.status} at {record.progress_pct}%.",
        payload={
            "run_id": str(record.run_id),
            "status": record.status,
            "progress_pct": record.progress_pct,
            "attempt": record.attempt,
            "statistics": record.statistics,
            "features": record.features[: record.request.max_features],
            "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
            "model": record.selected_model["model_id"],
            "model_revision": record.selected_model["model_revision"],
            "error": record.error,
        },
        evidence=references,
        warnings=record.warnings,
    )


@mcp.tool(name="geofm_retry_run", annotations=RETRY, structured_output=True)
async def geofm_retry_run(
    run_id: UUID,
    requested_by: str,
    owner_signature: str,
    owner_signature_expires_at: int,
    owner_signature_nonce: str,
) -> EvidenceEnvelope:
    """Start a new durable attempt for one failed run."""
    _validate_owner_signature(
        "retry",
        requested_by,
        {"run_id": str(run_id)},
        owner_signature_expires_at,
        owner_signature_nonce,
        owner_signature,
    )
    record = await anyio.to_thread.run_sync(
        get_service().retry_for_owner,
        run_id,
        requested_by,
    )
    return EvidenceEnvelope(
        evidence_rung=EvidenceRung.CATALOGUE,
        summary=f"GeoFM run {run_id} retry attempt {record.attempt} is queued.",
        payload={
            "run_id": str(run_id),
            "status": record.status,
            "attempt": record.attempt,
        },
        evidence=[EvidenceReference(kind="calculation", identifier=str(run_id))],
    )


@mcp.tool(name="geofm_cancel_run", annotations=CANCEL, structured_output=True)
async def geofm_cancel_run(
    run_id: UUID,
    requested_by: str,
    owner_signature: str,
    owner_signature_expires_at: int,
    owner_signature_nonce: str,
) -> EvidenceEnvelope:
    """Cancel a queued or running GeoFM run."""
    _validate_owner_signature(
        "cancel",
        requested_by,
        {"run_id": str(run_id)},
        owner_signature_expires_at,
        owner_signature_nonce,
        owner_signature,
    )
    record = await anyio.to_thread.run_sync(
        get_service().cancel_for_owner,
        run_id,
        requested_by,
    )
    return EvidenceEnvelope(
        evidence_rung=EvidenceRung.CATALOGUE,
        summary=f"GeoFM run {run_id} is cancelled.",
        payload={"run_id": str(run_id), "status": record.status},
        evidence=[EvidenceReference(kind="calculation", identifier=str(run_id))],
    )


class McpSuccessStatusMiddleware(BaseHTTPMiddleware):
    """Return HTTP 200 for successful MCP notifications."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if request.url.path == "/mcp" and response.status_code == 202:
            response.status_code = 200
        return response


class McpApiKeyMiddleware(BaseHTTPMiddleware):
    """Require a shared key on internal MCP requests when configured."""

    def __init__(self, app, *, api_key: str | None) -> None:
        super().__init__(app)
        self._api_key = api_key

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path == "/mcp" and self._api_key:
            supplied = request.headers.get("x-api-key", "")
            if not hmac.compare_digest(supplied, self._api_key):
                return JSONResponse(
                    {"error": "unauthorized", "message": "A valid MCP API key is required."},
                    status_code=401,
                )
        return await call_next(request)


@lru_cache(maxsize=1)
def get_service() -> RunService:
    """Build the configured local or Azure-backed run service."""
    catalog = get_catalog()
    blob_url = (os.getenv("AZURE_STORAGE_BLOB_ENDPOINT") or "").strip()
    queue_url = (os.getenv("AZURE_STORAGE_QUEUE_ENDPOINT") or "").strip()
    allow_conditional = os.getenv("GEOFM_ALLOW_CONDITIONAL", "false").casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if bool(blob_url) != bool(queue_url):
        raise RuntimeError(
            "AZURE_STORAGE_BLOB_ENDPOINT and AZURE_STORAGE_QUEUE_ENDPOINT "
            "must be configured together."
        )
    if blob_url and queue_url:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import ContainerClient
        from azure.storage.queue import QueueClient

        credential = DefaultAzureCredential()
        repository = BlobRunRepository(
            ContainerClient(
                account_url=blob_url,
                container_name=os.getenv("GEOFM_CONTAINER_NAME", "geofm"),
                credential=credential,
            )
        )
        dispatcher = AzureQueueDispatcher(
            QueueClient(
                account_url=queue_url,
                queue_name=os.getenv("GEOFM_QUEUE_NAME", "geofm-jobs"),
                credential=credential,
            )
        )
    else:
        repository = SQLiteRunRepository(
            Path(os.getenv("GEOFM_RUN_DB_PATH", ".data/geofm-runs.sqlite3"))
        )
        dispatcher = NoopDispatcher()
    return RunService(
        repository,
        dispatcher,
        inventory_lookup=catalog.get_asset_inventory,
        allow_conditional_models=allow_conditional,
    )


def build_app():
    """Build the authenticated MCP ASGI application."""
    api_key = os.getenv("GEOFM_MCP_API_KEY") or None
    owner_signing_key = os.getenv("GEOFM_OWNER_SIGNING_KEY") or ""
    require_api_key = os.getenv("GEOFM_REQUIRE_API_KEY", "false").casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if require_api_key and not api_key:
        raise RuntimeError("GEOFM_MCP_API_KEY is required in this environment.")
    if require_api_key and len(owner_signing_key) < 32:
        raise RuntimeError(
            "GEOFM_OWNER_SIGNING_KEY is required in this environment."
        )
    if api_key and owner_signing_key and hmac.compare_digest(api_key, owner_signing_key):
        raise RuntimeError(
            "GEOFM_MCP_API_KEY and GEOFM_OWNER_SIGNING_KEY must be distinct."
        )

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "planetary-explorer-geofm"})

    async def ready(_: Request) -> JSONResponse:
        snapshot = await anyio.to_thread.run_sync(
            _readiness_snapshot,
            owner_signing_key,
        )
        return _readiness_response(snapshot)

    application = mcp.streamable_http_app()
    application.routes.insert(0, Route("/health", endpoint=health, methods=["GET"]))
    application.routes.insert(1, Route("/ready", endpoint=ready, methods=["GET"]))
    application.add_middleware(McpSuccessStatusMiddleware)
    application.add_middleware(
        McpApiKeyMiddleware,
        api_key=api_key,
    )
    return application


app = build_app()


def main() -> None:
    """Run the GeoFM MCP service on the Container Apps convention port."""
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))


if __name__ == "__main__":
    main()