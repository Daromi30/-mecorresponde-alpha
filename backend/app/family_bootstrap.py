from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from . import services_v2 as svc
from .engine.guarded_gateway import GuardedModelGateway
from .family_manifest import FAMILY_MANIFEST, supported_family_codes
from .legal_source_registry import reconcile_legal_sources
from .models import LegalRuleVersion, LegalSource

_INSTALLED = False


def _verified_basis_for_preparable_decision(db, decision):
    """Resolve every exact reviewed rule version attached to a preparable decision.

    Some legitimate actions are deliberately emitted before a substantive rule result is
    labelled ``APPLIES``. Examples include giving the seller an additional delivery period
    and sending a withdrawal notice. Those actions still derive from the reviewed family
    rule and must carry its official provenance. The decision has already passed the
    evaluator/viability gate before this helper is used, so provenance follows the exact
    rule versions evaluated rather than a particular result label.
    """
    basis = []
    seen = set()
    for evaluation in decision.rule_evaluations_json or []:
        rule_id = str(evaluation.get("rule_id") or "")
        version = int(evaluation.get("version") or 0)
        key = (rule_id, version)
        if not rule_id or version <= 0 or key in seen:
            continue
        seen.add(key)
        rule = db.scalar(
            select(LegalRuleVersion).where(
                LegalRuleVersion.rule_id == rule_id,
                LegalRuleVersion.version == version,
                LegalRuleVersion.review_status == "approved",
            )
        )
        if rule is None:
            raise ValueError(f"Reviewed legal rule version missing for {rule_id} v{version}")
        source = db.get(LegalSource, rule.source_id)
        if (
            source is None
            or source.status != "active"
            or not source.official_url.startswith("https://www.boe.es/")
        ):
            raise ValueError(f"Verified official legal source missing for {rule_id} v{version}")
        basis.append(
            {
                "rule_id": rule.rule_id,
                "version": rule.version,
                "article": rule.article,
                "source_id": rule.source_id,
                "source": source.title,
                "official_url": source.official_url,
            }
        )
    if not basis:
        raise ValueError("No reviewed legal rule is attached to the current decision")
    return basis


def _would_repeat_initial_outbound_action(action_type: str) -> bool:
    """Identify actions that would send the user back into the initial-claim phase."""
    return action_type.startswith("PREPARE_") or action_type in {
        "GIVE_ADDITIONAL_DELIVERY_PERIOD",
        "SEND_WITHDRAWAL_NOTICE",
    }


def install_all_families() -> tuple[str, ...]:
    """Install every supported resolution family and fail fast on registry drift.

    Imports are deliberately lazy and sequential. The current extension modules wrap
    functions from ``services_v2`` at import time, so importing every extension before
    installing the previous one would make them all capture the same base functions and
    break the wrapper chain. This boundary preserves the current behaviour while giving
    startup a single multivertical entry point. New families should ultimately register
    directly here instead of adding another wrapper layer.
    """
    global _INSTALLED
    if not _INSTALLED:
        from .communication_date_policy import install_communication_date_policy
        from .fact_write_policy import install_fact_write_policy
        from .review_policy import install_review_policy

        install_fact_write_policy()
        install_review_policy()
        install_communication_date_policy()

        if not isinstance(svc.gateway, GuardedModelGateway):
            svc.gateway = GuardedModelGateway(svc.gateway)

        from .purchase_extensions import install_purchase_extensions

        install_purchase_extensions()

        from .energy_extensions import install_energy_extensions

        install_energy_extensions()

        from .energy_billing_contract_extensions import install_energy_billing_contract_extensions

        install_energy_billing_contract_extensions()

        from .energy_pricing_extensions import install_energy_pricing_extensions

        install_energy_pricing_extensions()

        previous_seed = svc.seed_legal

        def seed_with_reviewed_provenance(db):
            rules = previous_seed(db)
            reconcile_legal_sources(db)
            return rules

        svc.seed_legal = seed_with_reviewed_provenance

        from .claim_packages import (
            REGISTERED_EXTENSION_FAMILIES,
            prepare_registered_claim_package,
        )
        from .models import Action, Decision

        previous_prepare_claim = svc.prepare_claim_package

        def prepare_claim_for_all_families(db, case):
            current = db.get(Action, case.current_action_id) if case.current_action_id else None
            if (
                case.status == "READY_TO_SUBMIT"
                and current is not None
                and current.case_id == case.id
                and current.type == "SUBMIT_INITIAL_CLAIM"
                and current.status == "READY"
            ):
                return {"action_id": current.id, **(current.payload_json or {})}

            if case.status != "DIAGNOSED" or not case.current_decision_id:
                raise ValueError("Diagnose the current fact snapshot before preparing a claim")

            decision = db.get(Decision, case.current_decision_id)
            if decision is None or decision.case_id != case.id:
                raise ValueError("The current diagnosis could not be verified")
            latest_decision = db.scalars(
                select(Decision)
                .where(Decision.case_id == case.id)
                .order_by(Decision.created_at.desc())
            ).first()
            if latest_decision is None or latest_decision.id != decision.id:
                raise ValueError("The current diagnosis is stale; diagnose the case again before preparing a claim")

            if (case.family or "") in REGISTERED_EXTENSION_FAMILIES:
                return prepare_registered_claim_package(db, case)

            verified_basis = _verified_basis_for_preparable_decision(db, decision)

            preceding = current
            result = previous_prepare_claim(db, case)
            action = db.get(Action, result.get("action_id")) if result.get("action_id") else None
            if action is None or action.case_id != case.id:
                raise ValueError("Prepared claim action could not be verified")

            payload = dict(action.payload_json or {})
            payload["legal_basis"] = verified_basis
            action.payload_json = payload
            result = {**result, "legal_basis": verified_basis}

            if (
                preceding is not None
                and preceding.id != action.id
                and preceding.status != "COMPLETED"
            ):
                preceding.status = "COMPLETED"
                preceding.completed_at = datetime.now(timezone.utc)
            db.commit()
            return result

        svc.prepare_claim_package = prepare_claim_for_all_families

        previous_create_case = svc.create_case

        def create_case_with_assisted_fallback(db, message):
            case = previous_create_case(db, message)
            if case.family is not None:
                return case
            case.title = "Caso para revisión asistida"
            svc.create_human_review(
                db,
                case,
                reason="UNSUPPORTED_CLASSIFICATION",
                priority="NORMAL",
                context={
                    "phase": "INTAKE_CLASSIFICATION",
                    "vertical": case.vertical,
                    "family": case.family,
                },
            )
            db.commit()
            db.refresh(case)
            return case

        svc.create_case = create_case_with_assisted_fallback

        previous_analyze_response = svc.analyze_company_response

        def analyze_company_response_in_resolution_phase(db, case, text):
            result = previous_analyze_response(db, case, text)
            case.status = "RESPONSE_RECEIVED"
            db.commit()
            return result

        svc.analyze_company_response = analyze_company_response_in_resolution_phase

        previous_diagnose = svc.diagnose
        diagnosable_phases = {"INTAKE", "REANALYZING", "RESPONSE_RECEIVED"}

        def diagnose_with_post_response_escalation(db, case):
            if case.status not in diagnosable_phases:
                raise ValueError("The case is not in a phase that permits a new diagnosis")
            if case.status == "REANALYZING":
                current = db.get(Action, case.current_action_id) if case.current_action_id else None
                if (
                    current is not None
                    and current.case_id == case.id
                    and current.status in {"OPEN", "READY"}
                ):
                    raise ValueError("Complete the current action before reanalyzing the case")
            was_response_received = case.status == "RESPONSE_RECEIVED"
            result, decision, generated_action = previous_diagnose(db, case)
            if not (
                was_response_received
                and result.viability in {"HIGH", "MEDIUM"}
                and _would_repeat_initial_outbound_action(generated_action.type)
            ):
                return result, decision, generated_action

            generated_action.status = "COMPLETED"
            generated_action.completed_at = datetime.now(timezone.utc)
            reason = "POST_DENIAL_ESCALATION_REVIEW"
            review = svc.create_human_review(
                db,
                case,
                reason=reason,
                priority="HIGH",
                context={
                    "family": case.family,
                    "decision_id": decision.id,
                    "blocked_repeated_action": generated_action.type,
                    "phase": "POST_RESPONSE_ESCALATION",
                },
            )
            escalation_action = Action(
                case_id=case.id,
                type="HUMAN_REVIEW",
                status="OPEN",
                payload_json={
                    "reason": reason,
                    "review_id": review.id,
                    "phase": "POST_RESPONSE_ESCALATION",
                    "decision_id": decision.id,
                },
            )
            db.add(escalation_action)
            db.flush()
            case.current_action_id = escalation_action.id
            case.status = "HUMAN_REVIEW"
            svc.audit(
                db,
                case.id,
                "ESCALATION_REVIEW_REQUIRED",
                {
                    "decision_id": decision.id,
                    "review_id": review.id,
                    "blocked_repeated_action": generated_action.type,
                    "family": case.family,
                },
            )
            db.commit()
            return result, decision, escalation_action

        svc.diagnose = diagnose_with_post_response_escalation
        _INSTALLED = True

    expected = set(supported_family_codes())
    evaluators = set(svc.EVALUATORS)
    rule_families = set(svc.FAMILY_RULES)

    missing_evaluators = sorted(expected - evaluators)
    missing_rule_maps = sorted(expected - rule_families)
    unexpected = sorted((evaluators | rule_families) - expected)

    if missing_evaluators or missing_rule_maps or unexpected:
        raise RuntimeError(
            "Family registry drift: "
            f"missing_evaluators={missing_evaluators}, "
            f"missing_rule_maps={missing_rule_maps}, "
            f"unexpected={unexpected}"
        )

    for code, entry in FAMILY_MANIFEST.items():
        actual_rules = tuple(svc.FAMILY_RULES.get(code, []))
        if actual_rules != entry.rule_ids:
            raise RuntimeError(
                f"Family rule drift for {code}: manifest={entry.rule_ids}, runtime={actual_rules}"
            )

    return tuple(sorted(expected))
