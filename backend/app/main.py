import logging
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text

from .config import settings
from .db import engine, SessionLocal
from .engine.model_contracts import ModelOutputRejected
from .family_bootstrap import install_all_families
from .migrations import upgrade_database
from .models import LegalSource
from .seo_pages import SEO_PROBLEM_PAGES

SUPPORTED_FAMILIES = install_all_families()
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SEO_TITLE = "MECORRESPONDE | Comprueba si te corresponde reclamar"
SEO_DESCRIPTION = (
    "Comprueba si tienes base para reclamar, cuánto hay en juego, si te compensa "
    "y cuál es el siguiente paso."
)

from .routers.account_cases import router as account_cases_router
from .routers.admin import router as admin_router
from .routers.admin_review_resolution import router as admin_review_resolution_router
from .routers.auth import router as auth_router
from .routers.case_deletion import router as case_deletion_router
from .routers.cases_v2 import router as cases_router
from .routers.handoff import router as handoff_router
from .routers.quality import router as quality_router
from .routers.readiness import beta_readiness as compute_beta_readiness, router as readiness_router
from .routers.seo import router as seo_router
from .routers.sources import router as sources_router
from .routers.wait_resume import router as wait_resume_router
from .atomic_case_creation_policy import install_atomic_case_creation_policy
from .evidenced_recovery_policy import install_evidenced_recovery_policy
from .services_v2 import seed_legal
from .storage import StorageConfigurationError, get_document_storage, storage_status

# Runtime consistency wrappers install only after their router modules have captured the
# fully installed Motor workflow. Installing them earlier would make cases_v2 capture stale
# service wrappers during startup.
install_atomic_case_creation_policy()
install_evidenced_recovery_policy()

logger = logging.getLogger("uvicorn.error")
static_dir = Path(__file__).parent / "static"
admin_static_dir = Path(__file__).parent / "admin_static"


def _normalized_origin(value: str) -> str:
    return value.rstrip("/").casefold()


def _origin_is_trusted(request: Request, origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False

    request_host = request.headers.get("host", "").casefold()
    if request_host and parsed.netloc.casefold() == request_host:
        return True

    allowed = {_normalized_origin(value) for value in settings.cors_origin_list}
    return _normalized_origin(origin) in allowed


def _cross_site_block_response() -> JSONResponse:
    response = JSONResponse(
        status_code=403,
        content={"detail": "Cross-site state-changing request blocked"},
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _public_base_url() -> str:
    return settings.public_base_url.strip().rstrip("/")


def _problem_library_html() -> str:
    electricity = [page for page in SEO_PROBLEM_PAGES if page.vertical == "electricity"]
    purchases = [page for page in SEO_PROBLEM_PAGES if page.vertical == "purchases"]
    telecom = [page for page in SEO_PROBLEM_PAGES if page.vertical == "telecom"]
    travel = [page for page in SEO_PROBLEM_PAGES if page.vertical == "travel"]
    banking = [page for page in SEO_PROBLEM_PAGES if page.vertical == "banking"]
    rentals = [page for page in SEO_PROBLEM_PAGES if page.vertical == "rentals"]
    insurance = [page for page in SEO_PROBLEM_PAGES if page.vertical == "insurance"]

    def links(pages):
        return "".join(
            f'<li><a href="{escape(page.path, quote=True)}">{escape(page.title)}</a></li>'
            for page in pages
        )

    return (
        '<section id="problem-library" aria-label="Problemas que analiza MECORRESPONDE" '
        'style="max-width:1100px;margin:36px auto;padding:24px">'
        '<h2>Problemas que estamos estructurando</h2>'
        '<p>Guías de entrada al Motor de Resolución. Cada caso se analiza con sus hechos, pruebas y fuentes aplicables.</p>'
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px">'
        f'<div><h3>Luz</h3><ul>{links(electricity)}</ul></div>'
        f'<div><h3>Compras y garantías</h3><ul>{links(purchases)}</ul></div>'
        f'<div><h3>Telecomunicaciones</h3><ul>{links(telecom)}</ul></div>'
        f'<div><h3>Viajes</h3><ul>{links(travel)}</ul></div>'
        f'<div><h3>Banca</h3><ul>{links(banking)}</ul></div>'
        f'<div><h3>Alquiler</h3><ul>{links(rentals)}</ul></div>'
        f'<div><h3>Seguros</h3><ul>{links(insurance)}</ul></div>'
        '</div></section>'
    )


def _render_product_home() -> str:
    html = (static_dir / "index.html").read_text(encoding="utf-8")
    robots = "index,follow" if settings.public_indexing_ready else "noindex,nofollow"
    html = html.replace(
        '<meta name="robots" content="noindex,nofollow">',
        f'<meta name="robots" content="{robots}">',
        1,
    )
    html = html.replace("<title>MECORRESPONDE</title>", f"<title>{SEO_TITLE}</title>", 1)

    metadata = (
        f'<meta name="description" content="{escape(SEO_DESCRIPTION, quote=True)}">\n'
    )
    if settings.public_indexing_ready:
        canonical = escape(f"{_public_base_url()}/", quote=True)
        website_url = escape(f"{_public_base_url()}/", quote=True)
        metadata += (
            f'<link rel="canonical" href="{canonical}">\n'
            f'<meta property="og:title" content="{escape(SEO_TITLE, quote=True)}">\n'
            f'<meta property="og:description" content="{escape(SEO_DESCRIPTION, quote=True)}">\n'
            f'<meta property="og:type" content="website">\n'
            f'<meta property="og:url" content="{canonical}">\n'
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"WebSite",'
            f'"name":"MECORRESPONDE","url":"{website_url}"}}'
            "</script>\n"
        )
    html = html.replace(
        "</body>",
        f'{_problem_library_html()}\n<script src="/demo/dossier_quality.js"></script>\n</body>',
        1,
    )
    return html.replace("</head>", f"{metadata}</head>", 1)


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
            readiness = compute_beta_readiness(db)
        except Exception:
            logger.exception("MECORRESPONDE internal_beta_readiness: unavailable")
        else:
            logger.info(
                "MECORRESPONDE internal_beta_readiness: synthetic_internal_beta_ready=%s internal_beta_blockers=%s",
                readiness["synthetic_internal_beta_ready"],
                ",".join(readiness["internal_beta_blockers"]) or "none",
            )
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
    logger.info(
        "MECORRESPONDE public_indexing: ready=%s base_url_configured=%s seo_problem_pages=%s",
        settings.public_indexing_ready,
        bool(_public_base_url()),
        len(SEO_PROBLEM_PAGES),
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


@app.exception_handler(ModelOutputRejected)
async def rejected_model_output_handler(request: Request, exc: ModelOutputRejected):
    logger.error("MECORRESPONDE intelligence output rejected at %s", request.url.path)
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "No hemos podido interpretar este contenido de forma segura. "
                "No se ha generado ninguna conclusión jurídica a partir de esa salida."
            )
        },
        headers={"Cache-Control": "no-store"},
    )


@app.middleware("http")
async def safety_headers_and_storage_guard(request: Request, call_next):
    path = request.url.path
    method = request.method.upper()

    if method in UNSAFE_METHODS:
        origin = request.headers.get("origin")
        origin_allowed = bool(origin and _origin_is_trusted(request, origin))
        fetch_site = request.headers.get("sec-fetch-site", "").casefold()
        if (origin and not origin_allowed) or (fetch_site == "cross-site" and not origin_allowed):
            return _cross_site_block_response()

    is_document_upload = (
        method == "POST"
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

    always_noindex = (
        path.startswith("/api/")
        or path.startswith("/health")
        or path.startswith("/demo")
        or path.startswith("/backoffice")
    )
    public_indexable_surface = path == "/" or path.startswith("/reclamar")
    if always_noindex or (public_indexable_surface and not settings.public_indexing_ready):
        response.headers["X-Robots-Tag"] = "noindex, nofollow"

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    if (
        path == "/"
        or path.startswith("/reclamar")
        or path.startswith("/demo")
        or path.startswith("/backoffice")
    ):
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
app.include_router(wait_resume_router)
app.include_router(handoff_router)
app.include_router(case_deletion_router)
app.include_router(quality_router)
app.include_router(account_cases_router)
app.include_router(auth_router)
app.include_router(sources_router)
app.include_router(admin_router)
app.include_router(admin_review_resolution_router)
app.include_router(readiness_router)
app.include_router(seo_router)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def product_home():
    return HTMLResponse(_render_product_home())


@app.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
def robots_txt():
    lines = ["User-agent: *", "Allow: /"]
    if settings.public_indexing_ready:
        lines.append(f"Sitemap: {_public_base_url()}/sitemap.xml")
    return PlainTextResponse("\n".join(lines) + "\n")


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap_xml():
    if not settings.public_indexing_ready:
        return Response(status_code=404)
    base = _public_base_url()
    locations = [f"{base}/", *(f"{base}{page.path}" for page in SEO_PROBLEM_PAGES)]
    urls = "".join(f"<url><loc>{escape(location)}</loc></url>" for location in locations)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}"
        "</urlset>"
    )
    return Response(content=xml, media_type="application/xml")


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
