from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import services_v2 as svc
from .models import Action, Case, Document, Evidence, Fact


_INSTALLED = False
_COMPANY_RESPONSE_BATCH = ContextVar("mcr_company_response_batch", default=False)


def install_fact_write_policy() -> None:
    """Keep fact provenance and workflow lifecycle aligned.

    Claimant answers and claimant-confirmed document facts legitimately reopen the
    intake/diagnosis phase. Any decision or action produced from the previous fact snapshot
    is therefore superseded and must stop being current. Facts derived from a company
    response or protected human review are evidence inside an already-advanced phase and
    must not turn the case back into INTAKE.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    # Install workflow-wide invariants before family_bootstrap captures diagnosis for its
    # post-response wrapper. The shared fact snapshot receives Spain's civil analysis date;
    # claimant questions are suppressed while protected phases own the next transition;
    # external real-world steps get an explicit guided follow-up; reclassification stays
    # inside the anti-loop guard; terminal resolution sees the final routed diagnosis;
    # unsupported automated scope is handed to protected review; lifecycle timestamps are
    # enforced at the persistence boundary.
    from .analysis_clock_policy import install_analysis_clock_policy
    from .case_state_policy import install_case_state_policy
    from .external_action_followup_policy import install_external_action_followup_policy
    from .question_phase_policy import install_question_phase_policy
    from .reclassification_policy import install_reclassification_policy
    from .terminal_resolution_policy import install_terminal_resolution_policy
    from .unsupported_scope_policy import install_unsupported_scope_policy

    install_analysis_clock_policy()
    install_question_phase_policy()
    install_external_action_followup_policy()
    install_case_state_policy()
    install_reclassification_policy()
    install_terminal_resolution_policy()
    install_unsupported_scope_policy()

    previous_upsert_fact = svc.upsert_fact
    previous_confirm_document_fact = svc.confirm_document_fact
    previous_analyze_company_response = svc.analyze_company_response

    def supersede_current_analysis(db: Session, case: Case, *, fact_key: str, source: str) -> None:
        previous_action_id = case.current_action_id
        previous_decision_id = case.current_decision_id
        current = db.get(Action, previous_action_id) if previous_action_id else None
        if current is not None and current.case_id == case.id and current.status != "COMPLETED":
            current.status = "SUPERSEDED"
            current.completed_at = datetime.now(timezone.utc)
        if previous_action_id or previous_decision_id:
            svc.audit(
                db,
                case.id,
                "CURRENT_ANALYSIS_SUPERSEDED",
                {
                    "fact_key": fact_key,
                    "source": source,
                    "previous_action_id": previous_action_id,
                    "previous_decision_id": previous_decision_id,
                },
            )
        case.current_action_id = None
        case.current_decision_id = None
        case.status = "INTAKE"

    def upsert_fact_with_source_aware_lifecycle(
        db: Session,
        case: Case,
        key: str,
        value: Any,
        state: str = "asserted",
        materiality: str = "critical",
        confidence: float | None = None,
        user_confirmed: bool = True,
        created_by: str = "user",
    ) -> Fact:
        if created_by == "user":
            supersede_current_analysis(db, case, fact_key=key, source="user")
            return previous_upsert_fact(
                db,
                case,
                key,
                value,
                state=state,
                materiality=materiality,
                confidence=confidence,
                user_confirmed=user_confirmed,
                created_by=created_by,
            )

        previous = db.scalars(
            select(Fact)
            .where(Fact.case_id == case.id, Fact.key == key)
            .order_by(Fact.created_at.desc())
        ).first()
        fact = Fact(
            case_id=case.id,
            key=key,
            value_json={"value": value},
            state=state,
            materiality=materiality,
            confidence=confidence,
            user_confirmed=user_confirmed,
            created_by=created_by,
            supersedes_fact_id=previous.id if previous else None,
        )
        db.add(fact)
        db.flush()
        if created_by in {"company", "human"}:
            db.add(
                Evidence(
                    case_id=case.id,
                    fact_id=fact.id,
                    source_type=created_by,
                    strength="strong" if user_confirmed or created_by == "human" else "medium",
                )
            )
        svc.audit(
            db,
            case.id,
            "FACT_RECORDED",
            {
                "fact_id": fact.id,
                "key": key,
                "state": state,
                "source": created_by,
                "supersedes": previous.id if previous else None,
            },
        )

        # Only company facts produced while parsing one company communication are batched.
        # Direct company writes outside that response transaction keep their established
        # immediate-durability contract. ContextVar keeps this request/task local.
        if created_by == "company" and _COMPANY_RESPONSE_BATCH.get():
            return fact

        db.commit()
        db.refresh(fact)
        return fact

    def analyze_company_response_atomically(db: Session, case: Case, text: str):
        token = _COMPANY_RESPONSE_BATCH.set(True)
        try:
            return previous_analyze_company_response(db, case, text)
        except Exception:
            # Batched company facts, evidence, communication and response audit must either
            # all reach the analyzer's final commit or none of them become durable.
            db.rollback()
            raise
        finally:
            _COMPANY_RESPONSE_BATCH.reset(token)

    def confirm_document_fact_with_invalidation(
        db: Session,
        case: Case,
        document: Document,
        *,
        key: str,
        value: Any,
        locator: str | None = None,
        excerpt: str | None = None,
        materiality: str = "critical",
    ) -> Fact:
        supersede_current_analysis(db, case, fact_key=key, source="document")
        return previous_confirm_document_fact(
            db,
            case,
            document,
            key=key,
            value=value,
            locator=locator,
            excerpt=excerpt,
            materiality=materiality,
        )

    svc.upsert_fact = upsert_fact_with_source_aware_lifecycle
    svc.analyze_company_response = analyze_company_response_atomically
    svc.confirm_document_fact = confirm_document_fact_with_invalidation
    _INSTALLED = True
