"""
BD Intelligence Platform - Unified API
Combines Cortellis deals database with Edgar BD SEC filings.
Uses Neo4j as graph integration layer for relationship queries.
"""
import structlog
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from unified_api.config import settings
from unified_api.services.operations_telemetry import OperationsTelemetryMiddleware
from unified_api.routers import (
    admin,
    agentic_rag,
    analytics,
    auth,
    briefings,
    chat,
    clinical_trials,
    collaboration,
    comps,
    competitors,
    contracts,
    conversations,
    data_access,
    dashboard,
    dd,
    edgar,
    enrichment,
    entities,
    export,
    export_docs,
    graph,
    health,
    mcp_http,
    operations,
    public_biology,
    recommendations,
    search,
    territory,
    watchlist,
    xref,
)
from unified_api.routers import settings as settings_router

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger(__name__)


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Add X-Response-Time header and log slow requests."""
    async def dispatch(self, request, call_next):
        start = time.time()
        response = await call_next(request)
        elapsed = time.time() - start
        response.headers["X-Response-Time"] = f"{elapsed:.3f}s"
        if elapsed > 5.0:
            logger.warning("Slow request", path=request.url.path, elapsed=f"{elapsed:.2f}s")
        return response


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Catch unhandled exceptions and return JSON error responses."""
    async def dispatch(self, request, call_next):
        try:
            return await call_next(request)
        except Exception as e:
            request.state.telemetry_error_type = type(e).__name__
            logger.error("Unhandled exception", path=request.url.path, error=str(e))
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error", "type": type(e).__name__},
            )


class OwnerAccessPolicyMiddleware(BaseHTTPMiddleware):
    """Optionally extend the owner access policy to existing application APIs."""

    _EXEMPT_PREFIXES = ("/api/auth", "/api/admin", "/api/v1")

    async def dispatch(self, request, call_next):
        path = request.url.path
        if path.startswith("/api") and not path.startswith(self._EXEMPT_PREFIXES):
            from unified_api.services.api_credentials import (
                authorize_existing_api_request,
            )

            try:
                principal = authorize_existing_api_request(request)
                if principal is not None:
                    request.state.data_principal = principal
            except Exception as exc:
                from fastapi import HTTPException

                if isinstance(exc, HTTPException):
                    return JSONResponse(
                        status_code=exc.status_code,
                        content={"detail": exc.detail},
                        headers=exc.headers,
                    )
                raise
        return await call_next(request)


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """Log user actions to audit log."""
    async def dispatch(self, request, call_next):
        from unified_api.services.audit import log_audit
        
        response = await call_next(request)
        
        # Only log successful requests to key endpoints
        if response.status_code < 400:
            path = request.url.path
            
            # Get user ID from Authorization header if present
            user_id = None
            auth_header = request.headers.get("authorization")
            if auth_header and auth_header.startswith("Bearer "):
                try:
                    from unified_api.services.auth import decode_token
                    token = auth_header.split(" ", 1)[1]
                    token_data = decode_token(token)
                    if token_data:
                        user_id = token_data.user_id
                except Exception:
                    pass
            
            # Get IP address
            ip_address = request.client.host if request.client else None
            
            # Log specific actions
            if path == "/api/auth/login" and request.method == "POST":
                log_audit("login", user_id=user_id, ip_address=ip_address)
            elif path == "/api/auth/logout" and request.method == "POST":
                log_audit("logout", user_id=user_id, ip_address=ip_address)
            elif "/api/search" in path and request.method == "POST":
                log_audit("search", user_id=user_id, ip_address=ip_address)
            elif "/api/export" in path and request.method == "POST":
                log_audit("export", user_id=user_id, ip_address=ip_address)
            elif "/api/dd" in path and request.method == "POST":
                log_audit("dd_generation", user_id=user_id, ip_address=ip_address)
            elif "/api/comps" in path and request.method == "POST":
                log_audit("comp_set_creation", user_id=user_id, ip_address=ip_address)
        
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown events."""
    # Startup
    logger.info(
        "BD Intelligence Platform starting",
        version=settings.app_version,
        endpoints=len(app.routes),
        debug=settings.debug,
    )
    try:
        from unified_api.services.operations_telemetry import (
            capture_schema_snapshots_if_due,
            ensure_operations_schema,
            install_default_sql_telemetry,
        )

        # Deployment migrations own all DDL. Application workers only verify
        # that telemetry exists and install non-mutating SQL event listeners.
        ensure_operations_schema()
        install_default_sql_telemetry()
        capture_schema_snapshots_if_due()
    except Exception as exc:
        logger.warning(
            "Operations telemetry initialization failed",
            error_type=type(exc).__name__,
        )

    yield

    # Shutdown
    logger.info("BD Intelligence Platform shutting down")
    # Close graph connections
    try:
        from unified_api.services.graph_sync import get_graph_sync_service
        get_graph_sync_service().close()
    except Exception:
        pass


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="""
    **BD Intelligence Platform** - Unified pharmaceutical deals intelligence.

    Combines:
    - **Cortellis Deals Database**: 172K+ pharmaceutical deals with related entities
    - **SEC EDGAR Filings**: 330K+ SEC filing documents with material contracts
    - **Neo4j Graph**: Relationship queries and partnership network analysis

    ## Features
    - Natural language queries via LLM
    - Hybrid search (SQL + semantic RAG)
    - Entity resolution across data sources
    - Graph-based relationship queries
    - Deal extraction from SEC filings
    """,
    lifespan=lifespan,
)

# Configure CORS
origins = settings.allowed_origins.split(",") if settings.allowed_origins != "*" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add production middleware (Starlette makes the last user middleware outermost).
app.add_middleware(RequestTimingMiddleware)
app.add_middleware(ErrorHandlingMiddleware)
app.add_middleware(AuditLoggingMiddleware)
app.add_middleware(OwnerAccessPolicyMiddleware)
app.add_middleware(OperationsTelemetryMiddleware)

# Include routers
app.include_router(health.router, tags=["Health"])
app.include_router(mcp_http.router)
app.include_router(auth.router, prefix="/api", tags=["Auth"])
app.include_router(admin.router, prefix="/api", tags=["Admin"])
app.include_router(operations.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api", tags=["Dashboard"])
app.include_router(chat.router, prefix="/api", tags=["Chat"])
app.include_router(agentic_rag.router, prefix="/api", tags=["Agentic RAG"])
app.include_router(search.router, prefix="/api", tags=["Search"])
app.include_router(entities.router, prefix="/api", tags=["Entities"])
app.include_router(graph.router, prefix="/api", tags=["Graph"])
app.include_router(analytics.router, prefix="/api", tags=["Analytics"])
app.include_router(export.router, prefix="/api", tags=["Export"])
app.include_router(export_docs.router, prefix="/api", tags=["Export Docs"])
app.include_router(xref.router, prefix="/api", tags=["Entity Resolution"])
app.include_router(edgar.router, prefix="/api", tags=["Edgar SEC Filings"])
app.include_router(
    clinical_trials.router,
    prefix="/api",
    tags=["ClinicalTrials.gov"],
)
app.include_router(watchlist.router, prefix="/api", tags=["Watchlist"])
app.include_router(competitors.router, prefix="/api", tags=["Competitors"])
app.include_router(conversations.router, prefix="/api", tags=["Conversations"])
app.include_router(collaboration.router, prefix="/api", tags=["Collaboration"])
app.include_router(data_access.router, prefix="/api", tags=["Governed Data API"])
app.include_router(contracts.router, prefix="/api", tags=["Contract Intelligence"])
app.include_router(comps.router, prefix="/api", tags=["Comps"])
app.include_router(dd.router, prefix="/api", tags=["Due Diligence"])
app.include_router(territory.router, prefix="/api", tags=["Territory Rights"])
app.include_router(briefings.router, prefix="/api", tags=["Briefings"])
app.include_router(enrichment.router, tags=["Enrichment"])
app.include_router(public_biology.router, prefix="/api", tags=["Public Biology"])
app.include_router(recommendations.router, prefix="/api", tags=["Recommendations"])
app.include_router(settings_router.router, prefix="/api", tags=["Settings"])


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs_url": "/docs",
        "health_url": "/health",
    }
