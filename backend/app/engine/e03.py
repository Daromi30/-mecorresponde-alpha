from __future__ import annotations

from datetime import date
from typing import Any

from .common import EngineResult, FactValue, raw

RD88_URL = "https://www.boe.es/eli/es/rd/2026/02/11/88/con"
CURRENT_REGIME_START = date(2026, 2, 12)


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _worth(value: float | None) -> str:
    if value is None:
        return "YES_IF_LOW_COST"
    return "YES_IF_LOW_COST" if value < 30 else "YES"


def evaluate_e03(facts: dict[str, FactValue]) -> EngineResult:
    """E03 — supplier switch without express consent / wrong CUPS.

    Current rule: RD 88/2026 arts. 18.5-18.7 and 51.3. The incoming
    supplier must assure express consent, keep it on a durable medium for at
    least five years, and an erroneous/unauthorised switch must be restored.
    Identity-theft allegations are intentionally escalated.
    """
    sources = [{
        "title": "RD 88/2026, arts. 18.5-18.7 y 51.3",
        "url": RD88_URL,
    }]
    missing: list[str] = []
    counterarguments: list[dict[str, Any]] = []

    switch_date = _parse_date(raw(facts, "electricity.switch_effective_date"))
    if switch_date is None:
        missing.append("electricity.switch_effective_date")
    elif switch_date < CURRENT_REGIME_START:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW", scope_status="LEGACY_REVIEW",
            claimable_amount=None, economic_value=None, worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="El cambio es anterior al régimen automatizado de RD 88/2026. Debe aplicarse la normativa vigente en la fecha del cambio.",
            counterarguments=[], missing_facts=[], next_action="HUMAN_REVIEW_LEGACY",
            rule_result="OUT_OF_VALIDITY", failed_conditions=["switch_before_2026-02-12"],
            calculation=None, sources=sources, remedies=[], burden_of_proof=[],
        )

    previous_supplier = raw(facts, "electricity.previous_supplier")
    incoming_supplier = raw(facts, "electricity.incoming_supplier")
    if not previous_supplier:
        missing.append("electricity.previous_supplier")
    if not incoming_supplier:
        missing.append("electricity.incoming_supplier")

    identity_theft = raw(facts, "electricity.possible_identity_theft")
    if identity_theft is None:
        missing.append("electricity.possible_identity_theft")
    elif identity_theft is True:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW", scope_status="FRAUD_OR_IDENTITY_RISK",
            claimable_amount=None, economic_value=None, worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="El caso incluye una posible suplantación de identidad. La restitución del suministro puede seguir siendo relevante, pero la dimensión probatoria y de fraude no debe resolverse automáticamente.",
            counterarguments=[], missing_facts=[], next_action="HUMAN_REVIEW_IDENTITY_THEFT",
            rule_result="MANUAL_REVIEW", failed_conditions=[], calculation=None,
            sources=sources, remedies=["RESTORE_PREVIOUS_SUPPLIER"], burden_of_proof=[],
        )

    cups_correct = raw(facts, "electricity.switch_cups_correct")
    consent = raw(facts, "electricity.express_consent_given")
    if cups_correct is None:
        missing.append("electricity.switch_cups_correct")
    if consent is None:
        missing.append("electricity.express_consent_given")

    amount_raw = raw(facts, "electricity.unsolicited_supply_amount_paid")
    amount = round(float(amount_raw), 2) if amount_raw is not None else 0.0

    proof_status = raw(facts, "electricity.consent_evidence_status")
    if proof_status is None:
        missing.append("electricity.consent_evidence_status")

    if raw(facts, "company.asserts_consent", False):
        counterarguments.append({
            "type": "SUPPLIER_ASSERTS_EXPRESS_CONSENT", "status": "open",
            "impact": "critical", "origin": "company_response",
        })
    if raw(facts, "company.asserts_correct_cups", False):
        counterarguments.append({
            "type": "SUPPLIER_ASSERTS_CUPS_CORRECT", "status": "open",
            "impact": "material", "origin": "company_response",
        })

    burden = [{
        "issue": "express_consent_for_supplier_switch",
        "on": "incoming_supplier",
        "basis": "RD88_2026_18_5",
        "note": "El comercializador entrante debe asegurar el consentimiento expreso, reflejarlo en soporte duradero y conservarlo al menos cinco años.",
    }]

    if missing:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION", scope_status="SUPPORTED",
            claimable_amount=None, economic_value=amount or None, worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Faltan hechos materiales para distinguir un cambio no consentido, un CUPS incorrecto y un cambio válidamente consentido.",
            counterarguments=counterarguments, missing_facts=sorted(set(missing)),
            next_action="REQUEST_MATERIAL_FACT", rule_result="PENDING", failed_conditions=[],
            calculation=None, sources=sources, remedies=[], burden_of_proof=burden,
        )

    # A verified durable record of express consent defeats this specific branch.
    if consent is True and proof_status == "valid_durable_proof":
        return EngineResult(
            viability="LOW", scope_status="SUPPORTED", claimable_amount=0.0,
            economic_value=amount or None, worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="Consta consentimiento expreso respaldado por una prueba duradera válida. Con esos hechos, E03 no sustenta que el cambio de comercializador fuera no consentido.",
            counterarguments=counterarguments, missing_facts=[], next_action="EXPLAIN_VALID_CONSENT",
            rule_result="FAILED", failed_conditions=["express_consent_proven"],
            calculation=None, sources=sources, remedies=[], burden_of_proof=burden,
        )

    wrong_cups = cups_correct is False
    no_consent = consent is False
    if not wrong_cups and not no_consent:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION", scope_status="SUPPORTED",
            claimable_amount=None, economic_value=amount or None, worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="El usuario reconoce consentimiento pero no consta una prueba duradera válida. Antes de concluir, debe revisarse la evidencia concreta del consentimiento y del CUPS.",
            counterarguments=counterarguments, missing_facts=["electricity.consent_evidence_status"],
            next_action="REQUEST_CONSENT_EVIDENCE", rule_result="PENDING", failed_conditions=[],
            calculation=None, sources=sources, remedies=[], burden_of_proof=burden,
        )

    if proof_status == "valid_durable_proof" and no_consent:
        counterarguments.append({
            "type": "DURABLE_CONSENT_PROOF_CONFLICTS_WITH_USER_ACCOUNT", "status": "open",
            "impact": "critical", "origin": "evidence",
        })

    open_critical = any(c.get("status") == "open" and c.get("impact") == "critical" for c in counterarguments)
    viability = "MEDIUM" if open_critical else "HIGH"
    reason = "CUPS incorrecto" if wrong_cups else "ausencia de consentimiento expreso"
    reasoning = (
        f"El cambio presenta {reason}. El artículo 18 exige consentimiento expreso y el artículo 51.3 prevé la restitución del punto de suministro al comercializador saliente y al contrato previo cuando el cambio se produjo sin consentimiento o por CUPS incorrecto."
    )
    if amount > 0:
        reasoning += " Además, el artículo 18.7 impide reclamar pago por suministro no solicitado; el importe ya pagado queda identificado para su devolución/restitución en la reclamación."

    calculation = None
    if amount > 0:
        calculation = {
            "type": "unsolicited_supply_paid_amount",
            "verified_amount_paid": amount,
            "note": "No incluye daños y perjuicios adicionales, que requieren acreditación separada.",
        }

    return EngineResult(
        viability=viability, scope_status="SUPPORTED", claimable_amount=amount,
        economic_value=amount or None, worth_pursuing=_worth(amount),
        reasoning_summary=reasoning, counterarguments=counterarguments,
        missing_facts=[], next_action="PREPARE_UNAUTHORIZED_SWITCH_RESTORATION",
        rule_result="APPLIES", failed_conditions=[], calculation=calculation,
        sources=sources,
        remedies=["RESTORE_PREVIOUS_SUPPLIER", "RESTORE_PREVIOUS_CONTRACT", "CEASE_UNSOLICITED_CHARGES", "REFUND_UNSOLICITED_PAYMENTS_IF_ANY"],
        burden_of_proof=burden,
    )
