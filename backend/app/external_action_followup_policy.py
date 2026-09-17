from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from . import services_v2 as svc
from .models import Action, Case


_INSTALLED = False

# External actions are only safe when the product declares how the claimant can return to
# the Motor after performing or observing the real-world step. The registry is intentionally
# explicit: adding an ``external_step`` action to an evaluator without adding its follow-up
# contract fails CI.
_REGISTERED_EXTERNAL_FOLLOWUPS: dict[str, dict[str, Any]] = {
    "RETURN_GOODS_WITH_PROOF": {
        "family": "C05",
        "field": "purchase.return_sent",
        "previous_value": False,
        "question": "¿Ya has devuelto o enviado de vuelta el producto?",
        "input_type": "boolean",
    },
    "MONITOR_CONFORMITY": {
        "family": "C02",
        "field": "purchase.lack_after_conformity_attempt",
        "previous_value": False,
        "question": "¿Ha vuelto a aparecer una falta o problema después de la reparación o sustitución?",
        "input_type": "boolean",
    },
    "CHECK_BILL_AGAINST_REAL_READING": {
        "family": "E06",
        "field": "electricity.bill_matches_real_reading",
        "ask_when_missing": True,
        "question": "Al comparar la factura con la lectura real, ¿el consumo facturado coincide con esa lectura?",
        "input_type": "boolean",
    },
}


def known_external_followup_actions() -> tuple[str, ...]:
    """Return external Motor actions that have an explicit resumable follow-up."""
    return tuple(sorted(_REGISTERED_EXTERNAL_FOLLOWUPS))


def _apply_e06_bill_comparison_followup(db: Session, case: Case, result, decision, action) -> None:
    """Convert the factual E06 comparison into the already registered billing route.

    The E06 evaluator deliberately stops at ``CHECK_BILL_AGAINST_REAL_READING`` once a real
    reading exists. The comparison itself is not a new legal rule: if the final bill matches
    that reading, the E06 hypothesis ends; if it does not, the existing deterministic
    E06 -> E02-A transition owns the monetary billing analysis. This hook runs inside the
    diagnosis chain before the reclassification policy sees the result.
    """
    if case.family != "E06" or result.next_action != "CHECK_BILL_AGAINST_REAL_READING":
        return

    facts = svc.latest_facts(db, case.id)
    comparison = facts.get("electricity.bill_matches_real_reading")
    if comparison is None or not comparison.user_confirmed:
        return

    if comparison.value is False:
        result.viability = "RECLASSIFY"
        result.scope_status = "REDIRECT_E02_A"
        result.claimable_amount = None
        result.worth_pursuing = "NEEDS_REANALYSIS"
        result.reasoning_summary = (
            "Existe una lectura real, pero el usuario confirma que la factura no coincide con ella. "
            "E06 no inventa una diferencia monetaria: el expediente pasa a E02-A para comparar "
            "el importe facturado con el importe correcto a partir de datos verificables."
        )
        result.next_action = "RECLASSIFY_E02_A"
        case.status = "REANALYZING"
        route = "E02-A"
    else:
        result.viability = "LOW"
        result.scope_status = "SUPPORTED"
        result.claimable_amount = 0.0
        result.worth_pursuing = "NO_PAID_MANAGEMENT"
        result.reasoning_summary = (
            "Existe una lectura real dentro del ciclo revisado y el usuario confirma que la factura "
            "coincide con esa lectura. Con esos hechos no queda identificada una diferencia de "
            "facturación que E06 deba escalar."
        )
        result.next_action = "EXPLAIN_BILL_MATCHES_REAL_READING"
        case.status = "DIAGNOSED"
        route = "E06_CLOSED"

    economic_value = getattr(result, "economic_value", None)
    if economic_value is None:
        economic_value = result.claimable_amount
    remedies = list(getattr(result, "remedies", []) or [])
    burden = list(getattr(result, "burden_of_proof", []) or [])

    decision.viability = result.viability
    decision.scope_status = result.scope_status
    decision.claimable_amount = result.claimable_amount
    decision.economic_value = economic_value
    decision.worth_pursuing = result.worth_pursuing
    decision.professional_review_required = False
    decision.reasoning_summary = result.reasoning_summary
    decision.counterarguments_snapshot = list(result.counterarguments)

    action.type = result.next_action
    action.payload_json = {
        "claimable_amount": result.claimable_amount,
        "economic_value": economic_value,
        "remedies": remedies,
        "burden_of_proof": burden,
    }
    svc.audit(
        db,
        case.id,
        "EXTERNAL_FOLLOWUP_ROUTED",
        {
            "source_action": "CHECK_BILL_AGAINST_REAL_READING",
            "fact": "electricity.bill_matches_real_reading",
            "value": bool(comparison.value),
            "route": route,
            "decision_id": decision.id,
            "action_id": action.id,
        },
    )
    db.commit()


def install_external_action_followup_policy() -> None:
    """Turn real-world external steps into resumable guided case transitions.

    A claimant may need to do something outside MECORRESPONDE (for example return goods),
    observe whether a repaired product fails again, or perform a factual comparison against
    a document/reading. The ordinary question engine would otherwise treat the diagnosis as
    complete forever. While a registered external action is current, expose its factual
    follow-up again. Writing the answer uses the normal fact-ingress policy, supersedes the
    stale diagnosis and resumes the ordinary family flow.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    previous_get_next_question = svc.get_next_question
    previous_diagnose = svc.diagnose

    def get_next_question_with_external_followup(db: Session, case: Case):
        if case.status == "DIAGNOSED" and case.current_action_id:
            current = db.get(Action, case.current_action_id)
            spec = (
                _REGISTERED_EXTERNAL_FOLLOWUPS.get(current.type)
                if current is not None and current.case_id == case.id and current.status == "OPEN"
                else None
            )
            if spec is not None and case.family == spec["family"]:
                facts = svc.latest_facts(db, case.id)
                previous = facts.get(spec["field"])
                if spec.get("ask_when_missing") is True:
                    should_ask = previous is None
                else:
                    should_ask = (
                        previous is not None
                        and previous.user_confirmed
                        and previous.value == spec["previous_value"]
                    )
                if should_ask:
                    return {
                        "done": False,
                        "question": spec["question"],
                        "field": spec["field"],
                        "input_type": spec["input_type"],
                    }
        return previous_get_next_question(db, case)

    def diagnose_with_external_followup_routing(db: Session, case: Case):
        result, decision, action = previous_diagnose(db, case)
        _apply_e06_bill_comparison_followup(db, case, result, decision, action)
        return result, decision, action

    svc.get_next_question = get_next_question_with_external_followup
    svc.diagnose = diagnose_with_external_followup_routing
    _INSTALLED = True
