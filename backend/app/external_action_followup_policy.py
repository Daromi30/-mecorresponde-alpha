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
}


def known_external_followup_actions() -> tuple[str, ...]:
    """Return external Motor actions that have an explicit resumable follow-up."""
    return tuple(sorted(_REGISTERED_EXTERNAL_FOLLOWUPS))


def install_external_action_followup_policy() -> None:
    """Turn real-world external steps into resumable guided case transitions.

    A claimant may need to do something outside MECORRESPONDE (for example return goods) or
    wait to observe whether a repaired product fails again. If the relevant fact was already
    answered negatively, the ordinary question engine would otherwise treat it as complete
    forever. While a registered external action is current, expose that factual follow-up
    again. Writing the changed fact uses the normal fact-ingress policy, supersedes the stale
    diagnosis and resumes the ordinary family question flow.
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
