from __future__ import annotations

from sqlalchemy.orm import Session

from . import services_v2 as svc
from .models import Action, Case


_INSTALLED = False


def install_external_action_followup_policy() -> None:
    """Turn real-world external steps into resumable guided case transitions.

    C05 can correctly require the claimant to return goods before the refund can progress.
    The ordinary question engine treats a previously answered ``return_sent=false`` as a
    completed field, so after the claimant later performs the return there would otherwise
    be no UI path to update that fact. While the current diagnosed action is exactly
    RETURN_GOODS_WITH_PROOF, expose the same factual question again. Writing ``true`` uses
    the normal fact-ingress policy, supersedes the stale diagnosis and resumes the ordinary
    C05 question flow, which then asks for return proof.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    previous_get_next_question = svc.get_next_question

    def get_next_question_with_external_followup(db: Session, case: Case):
        if case.family == "C05" and case.status == "DIAGNOSED" and case.current_action_id:
            current = db.get(Action, case.current_action_id)
            if (
                current is not None
                and current.case_id == case.id
                and current.type == "RETURN_GOODS_WITH_PROOF"
                and current.status == "OPEN"
            ):
                facts = svc.latest_facts(db, case.id)
                return_sent = facts.get("purchase.return_sent")
                if (
                    return_sent is not None
                    and return_sent.user_confirmed
                    and return_sent.value is False
                ):
                    return {
                        "done": False,
                        "question": "¿Ya has devuelto o enviado de vuelta el producto?",
                        "field": "purchase.return_sent",
                        "input_type": "boolean",
                    }
        return previous_get_next_question(db, case)

    svc.get_next_question = get_next_question_with_external_followup
    _INSTALLED = True
