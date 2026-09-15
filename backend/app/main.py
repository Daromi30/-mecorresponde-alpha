import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text

from .config import settings
from .db import Base, engine, SessionLocal
from .models import LegalSource
from .routers.cases_v2 import router as cases_router
from .services_v2 import seed_legal

logger = logging.getLogger("mecorresponde.startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(settings.storage_dir).mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    backend = engine.url.get_backend_name()
    with SessionLocal() as db:
        existing_sources = db.scalar(select(func.count()).select_from(LegalSource)) or 0
        logger.info(
            "database_backend=%s persistent=%s existing_legal_sources=%s",
            backend,
            backend == "postgresql",
            existing_sources,
        )
        seed_legal(db)
        db.commit()
    yield


app = FastAPI(title=settings.app_name, version="0.3.2-alpha", lifespan=lifespan)
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
    return {"status": "ok", "service": "mecorresponde-alpha", "version": "0.3.2-alpha"}


@app.get("/health/db")
def database_health():
    """Verify that the configured relational database is reachable without exposing credentials."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    backend = engine.url.get_backend_name()
    return {"status": "ok", "database": backend, "persistent": backend == "postgresql"}
