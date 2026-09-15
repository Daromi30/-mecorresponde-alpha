import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text

from .config import settings
from .db import Base, engine, SessionLocal
from .models import LegalSource
from .routers.cases_v2 import router as cases_router
from .services_v2 import seed_legal

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(settings.storage_dir).mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
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
    yield


app = FastAPI(title=settings.app_name, version="0.3.3-alpha", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(cases_router)
static_dir = Path(__file__).parent / "static"
app.mount("/demo", StaticFiles(directory=str(static_dir), html=True), name="demo")


@app.get("/health")
def health():
    return {"status": "ok", "service": "mecorresponde-alpha", "version": "0.3.3-alpha"}


@app.get("/health/db")
def database_health():
    """Report the configured relational backend without exposing credentials."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    backend = engine.url.get_backend_name()
    return {"status": "ok", "database": backend, "persistent": backend == "postgresql"}


@app.get("/health/persistence")
def persistence_health():
    """Render health gate: a persistent alpha must be backed by PostgreSQL."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    backend = engine.url.get_backend_name()
    if backend != "postgresql":
        raise HTTPException(
            status_code=503,
            detail={"status": "error", "database": backend, "persistent": False},
        )
    return {"status": "ok", "database": "postgresql", "persistent": True}
