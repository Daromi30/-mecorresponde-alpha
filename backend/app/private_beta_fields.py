"""Minimal server-side field contract for the first private-beta families."""

from __future__ import annotations

from datetime import date
from math import isfinite

from fastapi import HTTPException

from .models import Case


# (type, technically required by the corresponding evaluator). Free text is bounded.
FIELD_SCHEMA: dict[str, dict[str, tuple[str, bool]]] = {
    "E02-A": {
        "electricity.billing.invoice_date": ("date", True),
        "electricity.billing.billed_amount": ("money", True),
        "electricity.billing.correct_amount": ("money", True),
    },
    "C01": {
        "purchase.buyer_is_consumer": ("boolean", True),
        "purchase.seller_is_business": ("boolean", True),
        "purchase.second_hand": ("boolean", True),
        "purchase.product_name": ("short_text", True),
        "purchase.delivery_date": ("date", True),
        "purchase.defect_manifested_date": ("date", True),
        "purchase.defect_description": ("description", True),
        "purchase.accidental_damage_or_misuse": ("boolean", True),
        "purchase.price": ("money", False),
        "purchase.seller_denied_conformity": ("boolean", False),
    },
}


def validate_private_fact(case: Case, key: str, value: object, *, state: str = "asserted") -> None:
    if case.mode != "PRIVATE_REAL_BETA":
        return
    spec = FIELD_SCHEMA.get(case.family or "", {}).get(key)
    if spec is None:
        raise HTTPException(422, "Fact field is unavailable for this private family")
    if state == "unknown":
        if value is not None:
            raise HTTPException(422, "Unknown private facts cannot carry a value")
        return
    kind, _required = spec
    valid = False
    if kind == "boolean":
        valid = type(value) is bool
    elif kind == "date":
        try:
            valid = isinstance(value, str) and date.fromisoformat(value).isoformat() == value
        except ValueError:
            valid = False
    elif kind == "money":
        valid = type(value) in (int, float) and isfinite(value) and 0 <= value <= 1_000_000_000
    elif kind in {"short_text", "description"}:
        limit = 120 if kind == "short_text" else 500
        valid = isinstance(value, str) and 1 <= len(value.strip()) <= limit
    if not valid:
        raise HTTPException(422, "Invalid value for this private fact field")
