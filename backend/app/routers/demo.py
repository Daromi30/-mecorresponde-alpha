"""Read-only public catalog of fictional scenarios."""

from fastapi import APIRouter

from ..demo_scenarios import public_catalog

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.get("/scenarios")
def scenarios() -> dict[str, object]:
    return {"scenarios": public_catalog()}
