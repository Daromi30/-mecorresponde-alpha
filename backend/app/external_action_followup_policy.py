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
    """Route the factual E06 comparison without rewriting the persisted diagnosis.

    The E06 evaluator deliberately stops at ``CHECK_BILL_AGAINST_REAL_READING`` once a real
    reading exists. The resulting Decision and DIAGNOSIS_GENERATED event are historical
    snapshots and must stay immutable. A later user-confirmed comparison therefore changes
    only the executable action: a mismatch uses the already registered E06 -> E02-A routing
    edge, while a match turns the check into a terminal explanation. Reclassification policy
    intentionally recognizes RECLASSIFY_* action contracts even when source viability is LOW.
    """
    if case.family != "E06" or result.next_action != "CHECK_BILL_AGAINST_REAL_READING":
        return

    facts = svc.latest_facts(db, case.id)
    comparison = facts.get("electricity.bill_matches_real_reading")
    if comparison is None or not comparison.user_confirmed:
        return

    if comparison.value is False:
        result.next_action = "RECLASSIFY_E02_A"
        action.type = "RECLASSIFY_E02_A"
        route = "E02-A"
    else:
        result.next_action = "EXPLAIN_BILL_MATCHES_REAL_READING"
        action.type = "EXPLAIN_BILL_MATCHES_REAL_READING"
        route = "E06_CLOSED"

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
            "decision_viability": decision.viability,
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
