from __future__ import annotations

from datetime import date
from typing import Any

from .common import EngineResult, FactValue, raw

RD88_URL = "https://www.boe.es/eli/es/rd/2026/02/11/88"
CURRENT_RULE_EFFECTIVE = date(2026, 6, 12)


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _supported_refund(
    penalty: float,
    sources: list[dict[str, str]],
    counterarguments: list[dict[str, Any]],
    reason: str,
) -> EngineResult:
    open_critical = any(
        item.get("status") == "open" and item.get("impact") == "critical"
        for item in counterarguments
    )
    return EngineResult(
        viability="MEDIUM" if open_critical else "HIGH",
        scope_status="SUPPORTED",
        claimable_amount=penalty,
        economic_value=penalty,
        worth_pursuing="YES_IF_LOW_COST" if penalty < 30 else "YES",
        reasoning_summary=reason,
        counterarguments=counterarguments,
        missing_facts=[],
        next_action="PREPARE_E05_PENALTY_REFUND",
        rule_result="APPLIES",
        failed_conditions=[],
        calculation={"type": "termination_penalty_refund", "charged_penalty": penalty},
        sources=sources,
        remedies=["REFUND_TERMINATION_PENALTY", "CEASE_PENALTY_COLLECTION"],
        burden_of_proof=[],
    )


def evaluate_e05(facts: dict[str, FactValue]) -> EngineResult:
    sources = [{
        "title": "Real Decreto 88/2026, art. 28.3, 28.9 y DT 8ª",
        "url": RD88_URL,
    }]
    missing: list[str] = []
    counterarguments: list[dict[str, Any]] = []

    natural_person = raw(facts, "electricity.consumer_natural_person")
    segment_2_0td = raw(facts, "electricity.segment_2_0td")
    termination_date = _parse_date(raw(facts, "electricity.termination_date"))
    penalty_raw = raw(facts, "electricity.termination_penalty_amount")
    penalty = round(float(penalty_raw), 2) if penalty_raw is not None else None

    if natural_person is None:
        missing.append("electricity.consumer_natural_person")
    if segment_2_0td is None:
        missing.append("electricity.segment_2_0td")
    if termination_date is None:
        missing.append("electricity.termination_date")
    if penalty is None:
        missing.append("electricity.termination_penalty_amount")

    if natural_person is False or segment_2_0td is False:
        return EngineResult(
            viability="OUT_OF_SCOPE", scope_status="LIMITED_SCOPE",
            claimable_amount=None, economic_value=penalty, worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="La automatización E05 se limita a personas físicas acogidas al segmento tarifario 2.0TD. Para los restantes consumidores el artículo 28.3 remite a lo pactado entre las partes.",
            counterarguments=[], missing_facts=[], next_action="HUMAN_REVIEW_CONTRACTUAL_PENALTY",
            rule_result="NOT_APPLICABLE", failed_conditions=["natural_person_2_0td_scope_failed"],
            calculation=None, sources=sources, remedies=[], burden_of_proof=[],
        )

    if termination_date and termination_date < CURRENT_RULE_EFFECTIVE:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW", scope_status="LEGACY_REVIEW",
            claimable_amount=None, economic_value=penalty, worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="La rescisión es anterior al 12/06/2026, fecha desde la que surte efectos el artículo 28 del RD 88/2026. Debe aplicarse el régimen temporal anterior.",
            counterarguments=[], missing_facts=missing, next_action="HUMAN_REVIEW_LEGACY",
            rule_result="OUT_OF_VALIDITY", failed_conditions=["termination_before_2026-06-12"],
            calculation=None, sources=sources, remedies=[], burden_of_proof=[],
        )

    if missing:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION", scope_status="SUPPORTED",
            claimable_amount=None, economic_value=penalty, worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Faltan hechos materiales para saber si la penalización entra en la regla general de prohibición o en la excepción de contrato a precio fijo antes de la primera prórroga anual.",
            counterarguments=[], missing_facts=sorted(set(missing)), next_action="REQUEST_MATERIAL_FACT",
            rule_result="PENDING", failed_conditions=[], calculation=None, sources=sources,
            remedies=[], burden_of_proof=[],
        )

    if penalty <= 0:
        return EngineResult(
            viability="LOW", scope_status="SUPPORTED", claimable_amount=0.0,
            economic_value=0.0, worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="No consta una penalización económica cobrada o exigida que deba recuperarse en E05.",
            counterarguments=[], missing_facts=[], next_action="NO_MONETARY_PENALTY_TO_CHALLENGE",
            rule_result="NO_CLAIM", failed_conditions=[], calculation=None, sources=sources,
            remedies=[], burden_of_proof=[],
        )

    vulnerable_pvpc = raw(facts, "electricity.switch_to_pvpc_as_vulnerable")
    if vulnerable_pvpc is None:
        vulnerable_pvpc = False
    if vulnerable_pvpc is True:
        return _supported_refund(
            penalty, sources, [],
            "El cambio a PVPC acreditando los requisitos de consumidor vulnerable debe realizarse sin penalización ni coste adicional en los términos del artículo 28.9 del Real Decreto 88/2026.",
        )

    fixed_price = raw(facts, "electricity.fixed_price_contract")
    if fixed_price is None:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION", scope_status="SUPPORTED",
            claimable_amount=None, economic_value=penalty, worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Para aplicar la excepción del artículo 28.3 hay que saber si el contrato era a precio fijo.",
            counterarguments=[], missing_facts=["electricity.fixed_price_contract"],
            next_action="REQUEST_MATERIAL_FACT", rule_result="PENDING", failed_conditions=[],
            calculation=None, sources=sources, remedies=[], burden_of_proof=[],
        )

    before_first_renewal = raw(facts, "electricity.before_first_annual_renewal")
    if fixed_price is True and before_first_renewal is None:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION", scope_status="SUPPORTED",
            claimable_amount=None, economic_value=penalty, worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Al tratarse de un contrato a precio fijo hay que comprobar si la rescisión se produjo antes de la primera prórroga anual.",
            counterarguments=[], missing_facts=["electricity.before_first_annual_renewal"],
            next_action="REQUEST_MATERIAL_FACT", rule_result="PENDING", failed_conditions=[],
            calculation=None, sources=sources, remedies=[], burden_of_proof=[],
        )

    if raw(facts, "company.asserts_fixed_price_first_year", False):
        counterarguments.append({
            "type": "SUPPLIER_ASSERTS_FIXED_PRICE_FIRST_YEAR_EXCEPTION",
            "status": "open", "impact": "critical", "origin": "company_response",
        })

    if fixed_price is True and before_first_renewal is True:
        proof = raw(facts, "electricity.supplier_provided_direct_loss_proof")
        calculation = raw(facts, "electricity.supplier_provided_penalty_calculation")
        missing_evidence = []
        if proof is None:
            missing_evidence.append("electricity.supplier_provided_direct_loss_proof")
        if calculation is None:
            missing_evidence.append("electricity.supplier_provided_penalty_calculation")
        return EngineResult(
            viability="PROFESSIONAL_REVIEW", scope_status="LIMITED_SCOPE",
            claimable_amount=None, economic_value=penalty, worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="Este caso entra en la excepción del artículo 28.3: contrato a precio fijo rescindido antes de la primera prórroga anual. La penalización solo puede operar cuando la rescisión cause daños al comercializador, no puede superar el límite legal y la carga de probar la pérdida económica directa recae en la comercializadora. La alpha no inventa esa pérdida ni la base de cálculo; debe revisarse la prueba y el método transitorio de estimación.",
            counterarguments=[{
                "type": "FIXED_PRICE_FIRST_YEAR_EXCEPTION", "status": "confirmed",
                "impact": "critical", "origin": "user_fact",
            }],
            missing_facts=missing_evidence, next_action="HUMAN_REVIEW_FIXED_PRICE_PENALTY",
            rule_result="MANUAL_REVIEW", failed_conditions=[], calculation=None, sources=sources,
            remedies=["VERIFY_DIRECT_LOSS", "VERIFY_5_PERCENT_CAP", "CHALLENGE_EXCESS_OR_UNPROVEN_PENALTY"],
            burden_of_proof=[{
                "issue": "direct_economic_loss_from_termination",
                "on": "supplier", "basis": "RD88_2026_28_3",
                "note": "La carga de la prueba de la pérdida económica directa recae siempre sobre la comercializadora.",
            }],
        )

    return _supported_refund(
        penalty, sources, counterarguments,
        "El artículo 28.3 permite a la persona física 2.0TD rescindir el contrato y sus prórrogas sin penalización. La excepción se limita al contrato a precio fijo antes de la primera prórroga anual. Con los hechos confirmados, esa excepción no concurre.",
    )
