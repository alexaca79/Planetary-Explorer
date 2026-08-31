# =============================================================================
# Entra ID Authentication Middleware for FastAPI
# =============================================================================
# Two paths, both verify the user is signed into the Entra tenant:
#
#   (A) OPTIONAL — `X-MS-CLIENT-PRINCIPAL` header (trusted proxy only)
#       Set by App Service / Container Apps EasyAuth when the request flows
#       through an auth-gated origin. This path is disabled unless
#       TRUST_EASYAUTH_HEADER=true because the public Container App ingress
#       otherwise lets clients forge the header.
#
#   (B) FALLBACK — `Authorization: Bearer <jwt>` (transitional)
#       The current topology has the browser calling the backend container
#       directly, bypassing EasyAuth. While we still operate that way, the
#       frontend forwards the user's `/.auth/me` ID token and we validate its
#       signature, tenant issuer, and application-specific audience here.
#
#       This fallback can be removed once the UI App Service proxies /api/*
#       through itself so that EasyAuth headers are injected on every
#       backend request (see `docs/auth-architecture.md`).
#
# Downstream data access (Fabric, OneLake, Power BI) does NOT use the user's
# token. The backend uses its own Managed Identity via `fabric_client`. So
# this middleware's only job is "is this person signed in?" — not "what can
# this person see?".
# =============================================================================

import base64
import json
import os
import logging
from typing import List, Optional, Set

import jwt
from jwt import PyJWKClient

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TENANT_ID = os.environ.get("AZURE_AD_TENANT_ID", "")
CLIENT_ID = os.environ.get("AZURE_AD_CLIENT_ID", "")

# Separate JWKS endpoints for v1.0 vs v2.0 tokens. AAD signs v1 and v2 tokens
# with overlapping but not identical key sets; pick by the token's `iss` claim.
JWKS_URL_V2 = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"
JWKS_URL_V1 = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/keys"
# Cross-tenant common endpoints provide a fallback during signing-key rotation.
JWKS_URL_COMMON_V2 = "https://login.microsoftonline.com/common/discovery/v2.0/keys"
JWKS_URL_COMMON_V1 = "https://login.microsoftonline.com/common/discovery/keys"

# Accept both v1.0 and v2.0 issuer formats
VALID_ISSUERS: List[str] = [
    f"https://login.microsoftonline.com/{TENANT_ID}/v2.0",
    f"https://sts.windows.net/{TENANT_ID}/",
]

# Accept only audiences bound to an application surface controlled by this
# deployment. Tenant-signed Graph or unrelated API tokens do not prove that a
# caller is assigned to Planetary Explorer.
VALID_AUDIENCES: List[str] = (
    [CLIENT_ID, f"api://{CLIENT_ID}"] if CLIENT_ID else []
)

# M365 declarative agent surface — separate app registration so its lifecycle
# (revoke, rescope, secret rotation) is independent from the UI's. Backward
# compatible: if the env var is absent, behavior is unchanged.
M365_APP_CLIENT_ID = os.environ.get("M365_APP_CLIENT_ID")
if M365_APP_CLIENT_ID:
    VALID_AUDIENCES.extend([M365_APP_CLIENT_ID, f"api://{M365_APP_CLIENT_ID}"])

# ---------------------------------------------------------------------------
# Paths that do NOT require authentication
# ---------------------------------------------------------------------------
OPEN_PATHS: Set[str] = {
    "/api/health",
    "/api/config",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/pc_rendering_config.json",
    "/pc_collections_metadata.json",
    "/stac_collections.json",
    "/favicon.ico",
    "/",
}

OPEN_PREFIXES: List[str] = [
    "/assets/",
    "/static/",
    "/api/pro/tile/",
    "/api/pro/tilejson",
    # Mosaic tilejson is synthesized server-side from a search_id and
    # served same-origin to the browser; no user AAD context required
    # (the upstream Pro raster API is talked to via managed identity).
    "/api/pro/mosaic/",
]


def _is_open_path(path: str) -> bool:
    """Return True if the path should be accessible without auth."""
    if path in OPEN_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in OPEN_PREFIXES)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
class EntraAuthMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that validates Entra ID Bearer tokens on protected
    routes.  Unauthenticated requests to protected routes receive 401.
    """

    def __init__(self, app):
        super().__init__(app)
        # Up to four JWKS clients — one per AAD endpoint variant. Lazy-init.
        self._jwks_clients: dict[str, PyJWKClient] = {}
        self._trust_easyauth_header = os.environ.get(
            "TRUST_EASYAUTH_HEADER", "false"
        ).lower() in ("true", "1", "yes")
        explicitly_disabled = os.environ.get("DISABLE_AUTH", "").lower() in (
            "true",
            "1",
            "yes",
        )
        dev_bypass = os.environ.get("RESILIENCE_DEV_BYPASS_AUTH", "0").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if dev_bypass and not explicitly_disabled:
            raise RuntimeError(
                "RESILIENCE_DEV_BYPASS_AUTH requires DISABLE_AUTH=true"
            )
        entra_configured = bool(TENANT_ID.strip() and CLIENT_ID.strip())
        self._enabled = not explicitly_disabled
        if self._enabled and entra_configured:
            logger.info(
                "[AUTH] Entra ID auth middleware ENABLED  "
                f"(tenant={TENANT_ID}, client={CLIENT_ID})"
            )
        elif self._enabled:
            logger.error(
                "[AUTH] Entra ID auth middleware ENABLED but "
                "AZURE_AD_TENANT_ID or AZURE_AD_CLIENT_ID is missing; "
                "protected routes will fail closed"
            )
        else:
            logger.info("[AUTH] Entra ID auth middleware DISABLED (DISABLE_AUTH=true)")

    def _get_jwks(self, url: str) -> PyJWKClient:
        c = self._jwks_clients.get(url)
        if c is None:
            c = PyJWKClient(url, cache_keys=True)
            self._jwks_clients[url] = c
        return c

    def _signing_key_for_token(self, token: str, iss: str):
        """Resolve the signing key for `token` by trying multiple JWKS endpoints.

        AAD's discovery endpoints aren't a single source of truth. We try the
        most likely endpoint first based on the issuer, then fall back.
        """
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid", "")
        is_v1 = "sts.windows.net" in iss

        # Try tenant-scoped first (matches iss), then cross-tenant common.
        urls = (
            [JWKS_URL_V1, JWKS_URL_V2, JWKS_URL_COMMON_V1, JWKS_URL_COMMON_V2]
            if is_v1
            else [JWKS_URL_V2, JWKS_URL_V1, JWKS_URL_COMMON_V2, JWKS_URL_COMMON_V1]
        )

        last_exc: Exception | None = None
        for url in urls:
            try:
                key = self._get_jwks(url).get_signing_key_from_jwt(token)
                logger.debug("[AUTH] kid=%s resolved via %s", kid, url)
                return key
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                continue
        logger.warning("[AUTH] kid=%s NOT FOUND in any JWKS feed (iss=%s)", kid, iss)
        assert last_exc is not None
        raise last_exc

    # -----------------------------------------------------------------------
    # Path A: EasyAuth-injected X-MS-CLIENT-PRINCIPAL header
    # -----------------------------------------------------------------------
    # EasyAuth has already validated the user before injecting this header.
    # Callers may use this path only when TRUST_EASYAUTH_HEADER=true and the
    # network topology prevents direct clients from reaching this ingress.
    @staticmethod
    def _principal_from_easyauth_header(header_b64: str) -> Optional[dict]:
        try:
            decoded = base64.b64decode(header_b64).decode("utf-8")
            principal = json.loads(decoded)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AUTH] X-MS-CLIENT-PRINCIPAL decode failed: %s", exc)
            return None
        # EasyAuth principal shape:
        #   { auth_typ, name_typ, role_typ, claims: [ {typ, val}, ... ] }
        claims = {c.get("typ"): c.get("val") for c in principal.get("claims", [])}
        tid = (
            claims.get("http://schemas.microsoft.com/identity/claims/tenantid")
            or claims.get("tid")
        )
        if not TENANT_ID or not tid or tid != TENANT_ID:
            logger.warning("[AUTH] X-MS-CLIENT-PRINCIPAL wrong tenant: %s", tid)
            return None
        subject = (
            claims.get("http://schemas.microsoft.com/identity/claims/objectidentifier")
            or claims.get("oid")
            or claims.get("sub")
        )
        if not subject:
            logger.warning("[AUTH] X-MS-CLIENT-PRINCIPAL missing stable subject")
            return None
        return {
            "sub": subject,
            "tid": tid,
            "preferred_username": (
                claims.get("preferred_username")
                or claims.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn")
                or claims.get("upn")
                or claims.get("name")
            ),
            "name": claims.get("name"),
            "claims": claims,
            "auth_source": "easyauth_header",
        }

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # --- Always allow open paths ---
        if _is_open_path(path):
            return await call_next(request)

        # --- Always allow CORS preflight (OPTIONS) ---
        if request.method == "OPTIONS":
            return await call_next(request)

        # --- Auth disabled — pass through ---
        if not self._enabled:
            return await call_next(request)

        # ----------------------------------------------------------------
        # Path A: EasyAuth header (preferred — used when the request comes
        # through an EasyAuth-fronted origin like the UI App Service proxy)
        # ----------------------------------------------------------------
        easyauth_header = request.headers.get("X-MS-CLIENT-PRINCIPAL") or request.headers.get(
            "x-ms-client-principal"
        )
        if self._trust_easyauth_header and easyauth_header:
            principal = self._principal_from_easyauth_header(easyauth_header)
            if principal is not None:
                request.state.user = principal
                logger.debug(
                    "[AUTH] OK (easyauth) — user=%s on %s",
                    principal.get("preferred_username") or principal.get("sub"),
                    path,
                )
                return await call_next(request)
            # If the header was present but malformed, fall through to bearer
            # rather than 401 — gives the frontend a chance to retry with a
            # token if the proxy is misconfigured.

        # ----------------------------------------------------------------
        # Path B: bearer JWT (transitional — used while the browser still
        # talks directly to the backend container)
        # ----------------------------------------------------------------
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.warning(f"[AUTH] 401 — missing Bearer token on {request.method} {path}")
            return JSONResponse(
                status_code=401,
                content={"error": "Missing or invalid Authorization header"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = auth_header[len("Bearer "):]

        # --- Validate JWT ---
        try:
            # Peek at the issuer (unverified) so we pick the right JWKS endpoint
            unverified = jwt.decode(token, options={"verify_signature": False})
            iss = unverified.get("iss", "")
            signing_key = self._signing_key_for_token(token, iss)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=VALID_AUDIENCES,
                options={
                    "verify_exp": True,
                    "verify_iss": False,  # manual issuer check below (accept v1 + v2)
                },
            )

            # Manual issuer validation (v1.0 and v2.0)
            iss = payload.get("iss", "")
            if iss not in VALID_ISSUERS:
                logger.warning(f"[AUTH] 401 — invalid issuer '{iss}' on {path}")
                return JSONResponse(
                    status_code=401,
                    content={"error": f"Invalid token issuer: {iss}"},
                )

            # Attach user claims to request state for downstream handlers
            payload["auth_source"] = "bearer_jwt"
            request.state.user = payload
            logger.debug(
                f"[AUTH] OK (bearer) — user={payload.get('preferred_username') or payload.get('upn') or payload.get('sub')} on {path}"
            )

        except jwt.ExpiredSignatureError:
            logger.warning(f"[AUTH] 401 — expired token on {path}")
            return JSONResponse(
                status_code=401,
                content={"error": "Token has expired"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        except jwt.InvalidAudienceError:
            logger.warning(f"[AUTH] 401 — invalid audience on {path}")
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid token audience"},
            )

        except Exception as e:
            # On any other failure, log the token header + claims (no signature)
            # so we can diagnose without round-tripping through DevTools.
            try:
                hdr = jwt.get_unverified_header(token)
                claims = jwt.decode(token, options={"verify_signature": False})
                logger.warning(
                    "[AUTH] 401 — bearer validation failed on %s: %s | "
                    "header=%s | iss=%s aud=%s ver=%s appid=%s upn=%s",
                    path, e, hdr,
                    claims.get("iss"), claims.get("aud"), claims.get("ver"),
                    claims.get("appid"), claims.get("upn") or claims.get("preferred_username"),
                )
            except Exception:
                logger.warning(f"[AUTH] 401 — bearer validation failed on {path}: {e} (token undecodable)")
            return JSONResponse(
                status_code=401,
                content={"error": f"Token validation failed: {str(e)}"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await call_next(request)
