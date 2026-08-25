"""Authenticated Streamable HTTP MCP control plane for durable GeoFM runs."""

from __future__ import annotations

import hmac
import os
from functools import lru_cache
from pathlib import Path
from uuid import UUID

import anyio
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .contracts import EvidenceEnvelope, EvidenceReference, EvidenceRung
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
async def geofm_compare_epochs(request: CompareEpochsRequest) -> EvidenceEnvelope:
    """Validate, persist, and enqueue a bi-temporal PlanAura comparison."""
    record, created = await anyio.to_thread.run_sync(get_service().submit, request)
    return EvidenceEnvelope(
        evidence_rung=EvidenceRung.CATALOGUE,
        summary=f"GeoFM run {record.run_id} is {record.status}.",
        payload={
            "run_id": str(record.run_id),
            "status": record.status,
            "created": created,
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
async def geofm_get_run(run_id: UUID, requested_by: str) -> EvidenceEnvelope:
    """Return durable state and validated results for one GeoFM run."""
    record = await anyio.to_thread.run_sync(
        get_service().get_for_owner,
        run_id,
        requested_by,
    )
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
        for artifact in record.artifacts
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
            "statistics": record.statistics,
            "features": record.features[: record.request.max_features],
            "artifacts": [artifact.model_dump(mode="json") for artifact in record.artifacts],
            "model": record.selected_model["model_id"],
            "model_revision": record.selected_model["model_revision"],
            "error": record.error,
        },
        evidence=references,
        warnings=record.warnings,
    )


@mcp.tool(name="geofm_cancel_run", annotations=CANCEL, structured_output=True)
async def geofm_cancel_run(run_id: UUID, requested_by: str) -> EvidenceEnvelope:
    """Cancel a queued or running GeoFM run."""
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
    require_api_key = os.getenv("GEOFM_REQUIRE_API_KEY", "false").casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if require_api_key and not api_key:
        raise RuntimeError("GEOFM_MCP_API_KEY is required in this environment.")

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "planetary-explorer-geofm"})

    application = mcp.streamable_http_app()
    application.routes.insert(0, Route("/health", endpoint=health, methods=["GET"]))
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