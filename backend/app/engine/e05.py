from __future__ import annotations

from datetime import date
from typing import Any

from .common import EngineResult, FactValue, raw

RD88_URL = "https://www.boe.es/eli/es/rd/2026/02/11/88/con"
CURRENT_REGIME_START = date(2026, 6, 12)


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _worth(value: float | None) -> str:
    if value is None:
        return "NEEDS_INFORMATION"
    return "YES_IF_LOW_COST" if value < 30 else "YES"


def evaluate_e05(facts: dict[str, FactValue]) -> EngineResult:
    """E05 — early termination/permanence charge for electricity supply.

    Current automated scope is the post-12-Jun-2026 regime of RD 88/2026
    art. 28.3 for a natural person in 2.0TD. We do not fabricate the monetary
    5% cap: the regulation delegates the estimation method and puts proof of
    direct economic loss on the supplier.
    """
    sources = [{"title": "RD 88/2026, art. 28.3 y DT 8.ª", "url": RD88_URL}]
    missing: list[str] = []
    counterarguments: list[dict[str, Any]] = []

    termination_date = _parse_date(raw(facts, "electricity.termination_date"))
    if termination_date is None:
        missing.append("electricity.termination_date")
    elif termination_date < CURRENT_REGIME_START:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW", scope_status="LEGACY_REVIEW",
            claimable_amount=None, economic_value=raw(facts, "electricity.termination_penalty_charged"),
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="La rescisión es anterior al 12/06/2026, fecha en la que empezó a surtir efectos el artículo 28 del RD 88/2026. Debe aplicarse el régimen histórico correspondiente.",
            counterarguments=[], missing_facts=[], next_action="HUMAN_REVIEW_LEGACY",
            rule_result="OUT_OF_VALIDITY", failed_conditions=["termination_before_2026-06-12"],
            calculation=None, sources=sources, remedies=[], burden_of_proof=[],
        )

    natural_person = raw(facts, "electricity.contract_holder_is_natural_person")
    tariff_20td = raw(facts, "electricity.tariff_is_2_0td")
    if natural_person is None:
        missing.append("electricity.contract_holder_is_natural_person")
    if tariff_20td is None:
        missing.append("electricity.tariff_is_2_0td")
    if natural_person is False or tariff_20td is False:
        return EngineResult(
            viability="OUT_OF_SCOPE", scope_status="UNSUPPORTED",
            claimable_amount=None, economic_value=raw(facts, "electricity.termination_penalty_charged"),
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary="La automatización E05 actual está limitada al régimen específico del artículo 28.3 para una persona física acogida a 2.0TD. Otros consumidores dependen de sus condiciones contractuales y requieren otra rama.",
            counterarguments=[], missing_facts=[], next_action="HUMAN_REVIEW_OTHER_CONTRACT_SCOPE",
            rule_result="NOT_APPLICABLE", failed_conditions=["not_natural_person_2_0td"],
            calculation=None, sources=sources, remedies=[], burden_of_proof=[],
        )

    penalty_raw = raw(facts, "electricity.termination_penalty_charged")
    penalty = round(float(penalty_raw), 2) if penalty_raw is not None else None
    if penalty is None:
        missing.append("electricity.termination_penalty_charged")

    fixed_price = raw(facts, "electricity.contract_is_fixed_price")
    first_annual_renewal = raw(facts, "electricity.first_annual_renewal_already_occurred")
    if fixed_price is None:
        missing.append("electricity.contract_is_fixed_price")
    if first_annual_renewal is None:
        missing.append("electricity.first_annual_renewal_already_occurred")

    if raw(facts, "company.asserts_fixed_price_pre_first_renewal", False):
        counterarguments.append({
            "type": "SUPPLIER_ASSERTS_FIXED_PRICE_PRE_FIRST_RENEWAL",
            "status": "open", "impact": "material", "origin": "company_response",
        })

    burden = [{
        "issue": "direct_economic_loss_from_early_termination",
        "on": "supplier",
        "basis": "RD88_2026_28_3",
        "note": "La carga de probar la pérdida económica directa del comercializador recae siempre sobre el propio comercializador.",
    }]

    if missing:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION", scope_status="SUPPORTED",
            claimable_amount=None, economic_value=penalty, worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Faltan hechos materiales para saber si la penalización entra en la única excepción automatizada del artículo 28.3.",
            counterarguments=counterarguments, missing_facts=sorted(set(missing)),
            next_action="REQUEST_MATERIAL_FACT", rule_result="PENDING", failed_conditions=[],
            calculation=None, sources=sources, remedies=[], burden_of_proof=burden,
        )

    # Outside the sole exception, a natural person in 2.0TD can terminate
    # without a penalty under the current rule.
    if fixed_price is False or first_annual_renewal is True:
        return EngineResult(
            viability="HIGH", scope_status="SUPPORTED", claimable_amount=penalty,
            economic_value=penalty, worth_pursuing=_worth(penalty),
            reasoning_summary="Para una persona física en 2.0TD, el artículo 28.3 permite rescindir el contrato y sus prórrogas en cualquier momento sin penalización, salvo exclusivamente un contrato a precio fijo antes de su primera prórroga anual. Con los hechos confirmados, esa excepción no concurre.",
            counterarguments=counterarguments, missing_facts=[],
            next_action="PREPARE_INVALID_TERMINATION_PENALTY_CLAIM", rule_result="APPLIES_NO_PENALTY",
            failed_conditions=[],
            calculation={"type": "penalty_refund", "penalty_charged": penalty},
            sources=sources, remedies=["CANCEL_PENALTY", "REFUND_PENALTY_IF_PAID"],
            burden_of_proof=burden,
        )

    # Fixed-price + before first annual renewal: a penalty may be possible only
    # when termination causes loss, with supplier burden and statutory cap.
    direct_loss_proof = raw(facts, "electricity.supplier_direct_loss_proof_status")
    if direct_loss_proof is None:
        return EngineResult(
            viability="MEDIUM", scope_status="SUPPORTED", claimable_amount=None,
            economic_value=penalty, worth_pursuing=_worth(penalty),
            reasoning_summary="El contrato está dentro de la excepción potencial —precio fijo antes de la primera prórroga anual—, pero la penalización no es automática. El comercializador debe probar una pérdida económica directa y respetar el límite legal. Debe requerirse la justificación antes de concluir que el cargo es válido.",
            counterarguments=counterarguments, missing_facts=["electricity.supplier_direct_loss_proof_status"],
            next_action="REQUEST_PENALTY_JUSTIFICATION", rule_result="PENDING_SUPPLIER_PROOF",
            failed_conditions=[], calculation=None, sources=sources,
            remedies=["REQUEST_DIRECT_LOSS_PROOF", "REQUEST_PENALTY_CALCULATION"],
            burden_of_proof=burden,
        )

    if direct_loss_proof == "none_or_not_provided":
        return EngineResult(
            viability="HIGH", scope_status="SUPPORTED", claimable_amount=penalty,
            economic_value=penalty, worth_pursuing=_worth(penalty),
            reasoning_summary="Aunque el contrato puede entrar en la excepción de precio fijo antes de la primera prórroga anual, el comercializador no ha acreditado la pérdida económica directa cuya prueba le corresponde. Con la evidencia actual, procede impugnar la penalización.",
            counterarguments=counterarguments, missing_facts=[],
            next_action="PREPARE_UNPROVEN_TERMINATION_PENALTY_CLAIM",
            rule_result="APPLIES_BURDEN_NOT_MET", failed_conditions=["direct_loss_not_proven"],
            calculation={"type": "penalty_refund", "penalty_charged": penalty},
            sources=sources, remedies=["CANCEL_PENALTY", "REFUND_PENALTY_IF_PAID"],
            burden_of_proof=burden,
        )

    if direct_loss_proof == "provided_needs_validation":
        return EngineResult(
            viability="PROFESSIONAL_REVIEW", scope_status="CALCULATION_REVIEW",
            claimable_amount=None, economic_value=penalty, worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="El comercializador ha aportado una justificación de pérdida económica directa. La norma fija un límite máximo vinculado a la energía estimada pendiente y remite el método de estimación a desarrollo reglamentario, con una regla transitoria. Esta alpha no inventa una fórmula monetaria: la prueba y el cálculo deben revisarse.",
            counterarguments=counterarguments, missing_facts=[], next_action="HUMAN_REVIEW_PENALTY_CAP",
            rule_result="MANUAL_REVIEW", failed_conditions=[], calculation=None,
            sources=sources, remedies=["VALIDATE_DIRECT_LOSS", "VALIDATE_STATUTORY_CAP"],
            burden_of_proof=burden,
        )

    return EngineResult(
        viability="INSUFFICIENT_INFORMATION", scope_status="SUPPORTED",
        claimable_amount=None, economic_value=penalty, worth_pursuing="NEEDS_INFORMATION",
        reasoning_summary="El estado de la prueba de pérdida directa no es reconocible. Debe revisarse la documentación antes de validar o rechazar la penalización.",
        counterarguments=counterarguments, missing_facts=["electricity.supplier_direct_loss_proof_status"],
        next_action="REQUEST_PENALTY_JUSTIFICATION", rule_result="PENDING",
        failed_conditions=[], calculation=None, sources=sources,
        remedies=[], burden_of_proof=burden,
    )
