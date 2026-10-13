"""Minimal server-side field contract for the first private-beta families."""

from __future__ import annotations

from datetime import date
from math import isfinite
import re

from fastapi import HTTPException

from .engine.c01 import evaluate_c01
from .engine.common import FactValue
from .models import Case


# (type, needed for the private-beta preliminary assessment). No participant prose.
FIELD_SCHEMA: dict[str, dict[str, tuple[str, bool]]] = {
    "E02-A": {
        "electricity.billing.billing_period": ("month", True),
        "electricity.billing.invoice_date": ("date", False),
        "electricity.billing.billed_amount": ("money", True),
        "electricity.billing.correct_amount": ("money", False),
    },
    "C01": {
        "purchase.buyer_is_consumer": ("boolean", True),
        "purchase.seller_is_business": ("boolean", True),
        "purchase.second_hand": ("boolean", True),
        "purchase.delivery_date": ("date", True),
        "purchase.defect_manifested_date": ("date", True),
        "purchase.nonconformity_reported": ("boolean", True),
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
    elif kind == "month":
        valid = isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{3}-(0[1-9]|1[0-2])", value) is not None
    elif kind == "money":
        valid = type(value) in (int, float) and isfinite(value) and 0 <= value <= 1_000_000_000
    if not valid:
        raise HTTPException(422, "Invalid value for this private fact field")


def next_private_question(facts: dict[str, FactValue], family: str) -> dict[str, object]:
    """Private-beta progression; the global 26-family question contract is untouched."""
    def ask(
        key: str, question: str, input_type: str, *, optional: bool = False,
        phase: str = "PRELIMINARY_FIT",
    ) -> dict[str, object]:
        return {
            "done": False, "question": question, "field": key, "input_type": input_type,
            "phase": phase, "optional": optional,
        }

    if family == "E02-A":
        if "electricity.billing.billing_period" not in facts:
            return ask("electricity.billing.billing_period", "¿A qué mes corresponde la factura?", "month")
        if "electricity.billing.billed_amount" not in facts:
            return ask("electricity.billing.billed_amount", "¿Qué importe te facturaron?", "money")
        if "electricity.billing.invoice_date" not in facts:
            return ask(
                "electricity.billing.invoice_date",
                "Si conoces el día exacto de emisión de la factura, indícalo; si no, responde «No lo sé». El periodo facturado no se convertirá en una fecha inventada.",
                "date_optional", optional=True,
            )
    elif family == "C01":
        questions = (
            ("purchase.buyer_is_consumer", "¿Compraste como particular?", "boolean"),
            ("purchase.seller_is_business", "¿Compraste a un vendedor profesional?", "boolean"),
            ("purchase.second_hand", "¿El producto era de segunda mano?", "boolean"),
            ("purchase.delivery_date", "¿Qué día recibiste el producto?", "date"),
            ("purchase.defect_manifested_date", "¿Cuándo se manifestó el problema?", "date"),
            ("purchase.nonconformity_reported", "¿Consideras que el producto no funciona o no se ajusta a lo contratado?", "boolean"),
            ("purchase.accidental_damage_or_misuse", "¿Hubo daño accidental o mal uso que pueda explicar el problema?", "boolean"),
            ("purchase.seller_denied_conformity", "¿El vendedor ya se negó a ponerlo en conformidad?", "boolean"),
        )
        for key, question, input_type in questions:
            if key not in facts:
                return ask(key, question, input_type)
        if ("purchase.price" not in facts
                and evaluate_c01(facts, private_beta=True).rule_result == "APPLIES"):
            return ask(
                "purchase.price", "Si conoces el precio, indícalo para valorar cuánto hay en juego; si no, responde «No lo sé».",
                "money", optional=True, phase="QUANTIFICATION",
            )
    return {"done": True, "question": None, "field": None}
