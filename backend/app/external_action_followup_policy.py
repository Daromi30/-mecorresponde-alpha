from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from . import services_v2 as svc
from .models import Action, Case


_INSTALLED = False

# External actions are only safe when the product declares how the claimant can return to
# the Motor after performing the real-world step. The registry is intentionally explicit:
# adding an ``external_step`` action to an evaluator without adding its follow-up contract
# fails CI.
_REGISTERED_EXTERNAL_FOLLOWUPS: dict[str, dict[str, Any]] = {
    "RETURN_GOODS_WITH_PROOF": {
        "family": "C05",
        "field": "purchase.return_sent",
        "previous_value": False,
        "question": "¿Ya has devuelto o enviado de vuelta el producto?",
        "input_type": "boolean",
    },
}


def known_external_followup_actions() -> tuple[str, ...]:
    """Return external Motor actions that have an explicit resumable follow-up."""
    return tuple(sorted(_REGISTERED_EXTERNAL_FOLLOWUPS))


def install_external_action_followup_policy() -> None:
    """Turn real-world external steps into resumable guided case transitions.

    C05 can correctly require the claimant to return goods before the refund can progress.
    The ordinary question engine treats a previously answered ``return_sent=false`` as a
    completed field, so after the claimant later performs the return there would otherwise
    be no UI path to update that fact. While a registered external action is current, expose
    its factual follow-up again. Writing the new fact uses the normal fact-ingress policy,
    supersedes the stale diagnosis and resumes the ordinary family question flow.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    previous_get_next_question = svc.get_next_question

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
                if (
                    previous is not None
                    and previous.user_confirmed
                    and previous.value == spec["previous_value"]
                ):
                    return {
                        "done": False,
                        "question": spec["question"],
                        "field": spec["field"],
                        "input_type": spec["input_type"],
                    }
        return previous_get_next_question(db, case)

    svc.get_next_question = get_next_question_with_external_followup
    _INSTALLED = True
