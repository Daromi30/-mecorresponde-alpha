import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text

from .config import settings
from .db import engine, SessionLocal
from .family_bootstrap import install_all_families
from .migrations import upgrade_database
from .models import LegalSource

SUPPORTED_FAMILIES = install_all_families()

from .routers.account_cases import router as account_cases_router
from .routers.admin import router as admin_router
from .routers.auth import router as auth_router
from .routers.cases_v2 import router as cases_router
from .routers.sources import router as sources_router
from .services_v2 import seed_legal
from .storage import StorageConfigurationError, get_document_storage, storage_status

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(settings.storage_dir).mkdir(parents=True, exist_ok=True)
    upgrade_database()
    backend = engine.url.get_backend_name()
    with SessionLocal() as db:
        existing_sources = db.scalar(select(func.count()).select_from(LegalSource)) or 0
        logger.info(
            "MECORRESPONDE persistence: database_backend=%s persistent=%s existing_legal_sources=%s",
            backend,
            backend == "postgresql",
            existing_sources,
        )
        seed_legal(db)
        db.commit()
    try:
        storage = storage_status()
        logger.info(
            "MECORRESPONDE document_storage: backend=%s persistent=%s uploads_allowed=%s",
            storage.backend,
            storage.persistent,
            storage.uploads_allowed,
        )
    except StorageConfigurationError as exc:
        logger.error("MECORRESPONDE document storage misconfigured: %s", exc)
    logger.info(
        "MECORRESPONDE backoffice: configured=%s",
        bool(settings.admin_api_token.strip()),
    )
    logger.info(
        "MECORRESPONDE resolution_families: count=%s codes=%s",
        len(SUPPORTED_FAMILIES),
        ",".join(SUPPORTED_FAMILIES),
    )
    yield


app = FastAPI(title=settings.app_name, version="0.5.0-alpha", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def safety_headers_and_storage_guard(request: Request, call_next):
    path = request.url.path
    is_document_upload = (
        request.method.upper() == "POST"
        and path.startswith("/api/cases/")
        and path.endswith("/documents")
    )
    if is_document_upload:
        try:
            status = storage_status()
        except StorageConfigurationError as exc:
            return JSONResponse(
                status_code=503,
                content={"detail": f"Document storage is not configured: {exc}"},
            )
        if not status.uploads_allowed:
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Document upload is disabled until persistent object storage is configured."
                },
            )

    response = await call_next(request)
    sensitive_api = (
        path == "/api/cases"
        or path.startswith("/api/cases/")
        or path.startswith("/api/admin")
        or path.startswith("/api/auth")
        or path.startswith("/backoffice")
    )
    if sensitive_api:
        response.headers["Cache-Control"] = "no-store"
    if path.startswith("/api/admin") or path.startswith("/backoffice"):
        response.headers["X-Robots-Tag"] = "noindex, nofollow"

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    if path.startswith("/demo") or path.startswith("/backoffice"):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'",
        )
    if settings.render:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


app.include_router(cases_router)
app.include_router(account_cases_router)
app.include_router(auth_router)
app.include_router(sources_router)
app.include_router(admin_router)
static_dir = Path(__file__).parent / "static"
admin_static_dir = Path(__file__).parent / "admin_static"
app.mount("/demo", StaticFiles(directory=str(static_dir), html=True), name="demo")
app.mount("/backoffice", StaticFiles(directory=str(admin_static_dir), html=True), name="backoffice")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "mecorresponde-alpha",
        "version": "0.5.0-alpha",
        "families": len(SUPPORTED_FAMILIES),
    }


@app.get("/health/db")
def database_health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    backend = engine.url.get_backend_name()
    return {"status": "ok", "database": backend, "persistent": backend == "postgresql"}


@app.get("/health/persistence")
def persistence_health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    backend = engine.url.get_backend_name()
    if backend != "postgresql":
        raise HTTPException(
            status_code=503,
            detail={"status": "error", "database": backend, "persistent": False},
        )
    return {"status": "ok", "database": "postgresql", "persistent": True}


@app.get("/health/storage")
def document_storage_health():
    try:
        status = storage_status(get_document_storage())
    except StorageConfigurationError as exc:
        raise HTTPException(status_code=503, detail={"status": "error", "reason": str(exc)})
    return {
        "status": "ok" if status.uploads_allowed else "blocked",
        "backend": status.backend,
        "persistent": status.persistent,
        "uploads_allowed": status.uploads_allowed,
    }
