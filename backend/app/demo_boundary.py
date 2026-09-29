"""Single public write boundary for the temporary closed synthetic demo.

Internal Motor services stay flexible. Only the HTTP `/api/cases` surface is
restricted; real-beta admission uses its separate, still-closed lane.
"""

from __future__ import annotations

import json

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .demo_scenarios import SCENARIOS
from .models import Case
from .services_v2 import audit


def reject(db: Session, case_id: str | None, endpoint: str, reason: str) -> None:
    audit(db, case_id, "SYNTHETIC_INPUT_REJECTED", {
        "endpoint": endpoint, "reason_code": reason,
    })
    db.commit()
    raise HTTPException(422, "This public demo accepts only predefined fictional scenarios")


async def enforce_demo_boundary(request: Request, db: Session = Depends(get_db)) -> None:
    if request.method.upper() not in {"POST", "PUT", "PATCH"}:
        return
    path = request.url.path.rstrip("/")
    if path == "/api/cases":
        raw = await request.body()
        if len(raw) > 512:
            reject(db, None, "case_create", "invalid_shape")
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            reject(db, None, "case_create", "invalid_json")
        if not isinstance(body, dict) or set(body) != {"scenario_id"}:
            reject(db, None, "case_create", "scenario_id_required")
        scenario_id = body["scenario_id"]
        if not isinstance(scenario_id, str) or scenario_id not in SCENARIOS:
            reject(db, None, "case_create", "unknown_scenario")
        request.state.demo_scenario_id = scenario_id
        return

    case_id = request.path_params.get("case_id")
    if not case_id:
        # Future write route without a case binding must be explicitly reviewed.
        reject(db, None, "unbound_case_write", "route_not_allowed")
    case = db.get(Case, case_id)
    if case is None or case.mode != "SYNTHETIC":
        return  # case-access / private-real-beta guards handle these paths

    route = request.scope.get("route")
    endpoint = getattr(route, "path", "/api/cases/{case_id}/unknown")
    if case.demo_scenario_id is None:
        reject(db, case.id, endpoint, "historical_synthetic_read_only")
    if case.demo_scenario_id not in SCENARIOS:
        reject(db, case.id, endpoint, "scenario_unavailable")
    if endpoint not in {
        "/api/cases/{case_id}/diagnose",
        "/api/cases/{case_id}/prepare-claim",
    }:
        reject(db, case.id, endpoint, "route_not_allowed")
    if await request.body():
        reject(db, case.id, endpoint, "body_not_allowed")
