from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import services_v2 as svc
from .models import Action, Case, Outcome


_INSTALLED = False


def _confirmed_user_fact(facts, key: str):
    fact = facts.get(key)
    if fact is None or not fact.user_confirmed or fact.state != "confirmed":
        return None
    return fact.value


def install_terminal_resolution_policy() -> None:
    """Resolve only terminal outcomes already proved by the current fact snapshot.

    This is deliberately a registry-by-contract rather than a generic LOW-viability rule.
    C05 can prove that withdrawal has already ended successfully when the claimant has
    explicitly confirmed both receipt of the refund and its amount and the evaluator has
    produced VERIFY_AND_CLOSE_WITHDRAWAL with a satisfied rule result. No calendar date or
    payment channel is inferred when the claimant did not provide one.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    previous_diagnose = svc.diagnose

    def diagnose_with_terminal_resolution(db: Session, case: Case):
        result, decision, action = previous_diagnose(db, case)
        if not (
            case.family == "C05"
            and action.type == "VERIFY_AND_CLOSE_WITHDRAWAL"
            and result.rule_result == "SATISFIED"
        ):
            return result, decision, action

        facts = svc.latest_facts(db, case.id)
        refund_received = _confirmed_user_fact(facts, "purchase.refund_received")
        refund_amount = _confirmed_user_fact(facts, "purchase.refund_received_amount")
        if refund_received is not True or refund_amount is None:
            return result, decision, action

        try:
            recovered = round(float(refund_amount), 2)
        except (TypeError, ValueError):
            return result, decision, action
        if recovered < 0:
            return result, decision, action

        calculation = result.calculation or {}
        if round(float(calculation.get("outstanding", 1.0)), 2) != 0.0:
            return result, decision, action

        existing = db.scalar(select(Outcome).where(Outcome.case_id == case.id))
        outcome = existing if existing is not None else Outcome(
            case_id=case.id,
            result_type="FAVORABLE",
        )
        if existing is None:
            db.add(outcome)

        action.status = "COMPLETED"
        action.completed_at = datetime.now(timezone.utc)
        case.current_action_id = None
        case.status = "RESOLVED"

        outcome.result_type = "FAVORABLE"
        outcome.amount_recovered = recovered
        outcome.verified_by_user = True
        outcome.resolved_at = datetime.now(timezone.utc)
        # resolved_on and resolution_channel intentionally remain untouched/unknown.

        svc.audit(
            db,
            case.id,
            "OUTCOME_RECORDED",
            {
                "result": "FAVORABLE",
                "verified": True,
                "source": "confirmed_terminal_facts",
            },
        )
        svc.audit(
            db,
            case.id,
            "TERMINAL_FACT_RESOLUTION_RECORDED",
            {
                "family": case.family,
                "decision_id": decision.id,
                "action_id": action.id,
                "terminal_action": action.type,
                "amount_recovered": recovered,
                "resolved_on": None,
                "resolution_channel": None,
            },
        )
        db.commit()
        db.refresh(case)
        db.refresh(outcome)
        return result, decision, action

    svc.diagnose = diagnose_with_terminal_resolution
    _INSTALLED = True
