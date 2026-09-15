from __future__ import annotations

from datetime import date
from typing import Any

from .common import EngineResult, FactValue, raw, verified

RULE_START = date(2014, 3, 29)
TRLGDCU_URL = "https://www.boe.es/buscar/act.php?id=BOE-A-2007-20555"


def evaluate_e04a(facts: dict[str, FactValue]) -> EngineResult:
    sources = [
        {"title": "TRLGDCU, art. 66 quáter", "url": TRLGDCU_URL},
        {"title": "TRLGDCU, art. 60 bis", "url": TRLGDCU_URL},
    ]
    missing: list[str] = []
    counterarguments: list[dict[str, Any]] = []

    service = raw(facts, "electricity.addon.identity")
    if not service:
        missing.append("electricity.addon.identity")

    ever = raw(facts, "electricity.addon.ever_contracted")
    if ever is None:
        missing.append("electricity.addon.ever_contracted")
    elif ever is True:
        return EngineResult(
            viability="RECLASSIFY", scope_status="REDIRECT_CONTRACTED_ADDON", claimable_amount=None,
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary="El usuario reconoce haber contratado el servicio. E04-A deja de ser el árbol correcto y hay que analizar las condiciones de ese contrato.",
            counterarguments=[], missing_facts=[], next_action="RECLASSIFY_CONTRACTED_ADDON",
            rule_result="NOT_APPLICABLE", failed_conditions=["ever_contracted=true"], calculation=None, sources=sources,
        )

    consent_proven = raw(facts, "electricity.addon.consent_proven")
    if consent_proven is True:
        return EngineResult(
            viability="LOW", scope_status="SUPPORTED", claimable_amount=0.0,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="Existe evidencia confirmada de consentimiento expreso para el servicio adicional; el supuesto de servicio no solicitado no queda sustentado.",
            counterarguments=[{"type":"CONSENT_EVIDENCE","status":"confirmed","impact":"critical"}],
            missing_facts=[], next_action="EXPLAIN_CONSENT_EVIDENCE", rule_result="FAILED",
            failed_conditions=["consent_proven=true"], calculation=None, sources=sources,
        )

    if raw(facts, "company.asserts_consent", False):
        counterarguments.append({"type":"CONSENT_EVIDENCE","status":"open","impact":"critical","origin":"company_response"})

    charges = raw(facts, "electricity.addon.charges")
    if not charges:
        missing.append("electricity.addon.charges")
        charges = []

    verified_charges = [c for c in charges if c.get("evidence_verified", False)]
    amount = round(sum(float(c.get("amount", 0)) for c in verified_charges), 2)
    calculation = {
        "type": "sum_verified_unauthorized_addon_charges",
        "included": verified_charges,
        "result": amount,
    }

    first_charge_date = raw(facts, "electricity.addon.first_charge_date")
    if first_charge_date:
        if isinstance(first_charge_date, str):
            first_charge_date = date.fromisoformat(first_charge_date)
        if first_charge_date < RULE_START:
            return EngineResult(
                viability="PROFESSIONAL_REVIEW", scope_status="LEGACY_REVIEW", claimable_amount=None,
                worth_pursuing="PROFESSIONAL_REVIEW",
                reasoning_summary="El cargo es anterior al ruleset automatizado E04-A soportado en esta versión.",
                counterarguments=counterarguments, missing_facts=missing, next_action="HUMAN_REVIEW_LEGACY",
                rule_result="OUT_OF_VALIDITY", failed_conditions=["event_before_rule_start"], calculation=None, sources=sources,
            )

    if missing:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION", scope_status="SUPPORTED", claimable_amount=amount or None,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Faltan hechos materiales para determinar si el servicio fue realmente no solicitado y qué importe está acreditado.",
            counterarguments=counterarguments, missing_facts=sorted(set(missing)), next_action="REQUEST_MATERIAL_FACT",
            rule_result="PENDING", failed_conditions=[], calculation=calculation, sources=sources,
        )

    if amount <= 0:
        return EngineResult(
            viability="MEDIUM" if ever is False else "INSUFFICIENT_INFORMATION", scope_status="SUPPORTED", claimable_amount=0.0,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="El servicio puede ser no solicitado, pero todavía no hay cargos acreditados que cuantificar.",
            counterarguments=counterarguments, missing_facts=[], next_action="REQUEST_CHARGE_EVIDENCE",
            rule_result="APPLIES_NO_AMOUNT", failed_conditions=[], calculation=calculation, sources=sources,
        )

    open_critical = any(c["impact"] == "critical" and c["status"] == "open" for c in counterarguments)
    high = verified(facts, "electricity.addon.ever_contracted") and ever is False and not open_critical
    return EngineResult(
        viability="HIGH" if high else "MEDIUM", scope_status="SUPPORTED", claimable_amount=amount,
        worth_pursuing="YES_IF_LOW_COST" if amount < 30 else "YES",
        reasoning_summary=(
            f"Se han identificado {amount:.2f} € en cargos acreditados por un servicio que el usuario afirma no haber solicitado. "
            "La normativa de consumo exige consentimiento expreso para pagos adicionales y prohíbe pretender el pago por servicios no solicitados."
        ),
        counterarguments=counterarguments, missing_facts=[], next_action="PREPARE_INITIAL_CLAIM",
        rule_result="APPLIES", failed_conditions=[], calculation=calculation, sources=sources,
    )
