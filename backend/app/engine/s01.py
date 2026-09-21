from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .common import EngineResult, FactValue, raw

LCS_URL = "https://www.boe.es/eli/es/l/1980/10/08/50/con"


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _money(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def evaluate_s01(facts: dict[str, FactValue]) -> EngineResult:
    """S01 — narrow Article 18 minimum-payment route.

    S01 never decides coverage, causation, loss valuation or Article 20 default interest.
    It automates only a minimum amount the insurer itself has acknowledged in a durable
    communication, after an evidenced claim declaration has reached 40 calendar days.
    """
    sources = [{"title": "Ley 50/1980 de Contrato de Seguro, art. 18", "url": LCS_URL}]
    role = raw(facts, "insurance.claimant_role")
    counterparty = raw(facts, "insurance.counterparty_type")
    declaration_received = raw(facts, "insurance.claim_declaration_received_by_insurer")
    received_date = _parse_date(raw(facts, "insurance.claim_declaration_received_date"))
    receipt_evidence = raw(facts, "insurance.claim_declaration_receipt_evidence")
    minimum_acknowledged = raw(facts, "insurance.insurer_acknowledged_minimum_amount")
    analysis_date = _parse_date(raw(facts, "system.analysis_date")) or date.today()

    missing: list[str] = []
    for key, value in [
        ("insurance.claimant_role", role),
        ("insurance.counterparty_type", counterparty),
        ("insurance.claim_declaration_received_by_insurer", declaration_received),
        ("insurance.claim_declaration_received_date", received_date),
        ("insurance.claim_declaration_receipt_evidence", receipt_evidence),
        ("insurance.insurer_acknowledged_minimum_amount", minimum_acknowledged),
    ]:
        if value is None:
            missing.append(key)

    if missing:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Faltan hechos esenciales para comprobar la ruta estrecha de pago mínimo del artículo 18.",
            counterarguments=[],
            missing_facts=sorted(set(missing)),
            next_action="REQUEST_MATERIAL_FACT",
            rule_result="PENDING",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if role not in {"policyholder", "insured", "beneficiary"}:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="S01 automatiza únicamente al tomador, asegurado o beneficiario frente al asegurador del contrato.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_S01_CLAIMANT_SCOPE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if counterparty != "insurer":
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "S01 cubre la obligación del asegurador del artículo 18. Consorcio, mediadores, terceros responsables "
                "u otros obligados requieren una ruta distinta."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_S01_COUNTERPARTY_SCOPE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if declaration_received is not True:
        return EngineResult(
            viability="OUT_OF_SCOPE",
            scope_status="UNSUPPORTED",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary="El plazo del artículo 18 se cuenta desde que el asegurador recibe la declaración del siniestro.",
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_S01_CLAIM_NOT_RECEIVED",
            rule_result="NOT_APPLICABLE",
            failed_conditions=["claim_declaration_received_required"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    assert received_date is not None
    if received_date > analysis_date:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="La fecha de recepción de la declaración es posterior a la fecha de análisis y requiere revisión.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_S01_DATE_INCONSISTENCY",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if receipt_evidence is not True:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "Sin prueba suficiente de cuándo recibió el asegurador la declaración, S01 no fija automáticamente "
                "el vencimiento de los cuarenta días."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_S01_RECEIPT_EVIDENCE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if minimum_acknowledged is not True:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "El artículo 18 se refiere al importe mínimo de lo que el asegurador pueda deber según las circunstancias conocidas. "
                "Si ese mínimo no está ya cuantificado o reconocido de forma verificable, S01 no decide cobertura, causalidad ni valoración."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_S01_MINIMUM_AMOUNT_NOT_ACKNOWLEDGED",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    minimum = _money(raw(facts, "insurance.acknowledged_minimum_amount"))
    paid = raw(facts, "insurance.minimum_payment_received")
    missing_money: list[str] = []
    if minimum is None:
        missing_money.append("insurance.acknowledged_minimum_amount")
    if paid is None:
        missing_money.append("insurance.minimum_payment_received")
    received_amount = 0.0
    if paid is True:
        received_value = _money(raw(facts, "insurance.minimum_payment_received_amount"))
        if received_value is None:
            missing_money.append("insurance.minimum_payment_received_amount")
        else:
            received_amount = max(received_value, 0.0)

    if missing_money:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=minimum,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Falta la cuantía mínima reconocida o el importe ya abonado para calcular el saldo.",
            counterarguments=[],
            missing_facts=sorted(set(missing_money)),
            next_action="REQUEST_MATERIAL_FACT",
            rule_result="PENDING",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    assert minimum is not None
    if minimum <= 0:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=minimum,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="La cuantía mínima reconocida no permite una solicitud monetaria segura.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_S01_INVALID_MINIMUM_AMOUNT",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    deadline = received_date + timedelta(days=40)
    outstanding = round(max(minimum - received_amount, 0.0), 2)
    calculation = {
        "acknowledged_minimum_amount": minimum,
        "already_paid": round(received_amount, 2),
        "outstanding_minimum": outstanding,
        "claim_declaration_received_date": received_date.isoformat(),
        "article_18_forty_day_date": deadline.isoformat(),
        "forty_days_elapsed": analysis_date >= deadline,
        "article_20_default_interest_calculated": False,
    }

    if outstanding <= 0:
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=minimum,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="El pago acreditado ya cubre el importe mínimo reconocido por el asegurador.",
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_S01_MINIMUM_ALREADY_PAID",
            rule_result="APPLIES",
            failed_conditions=[],
            calculation=calculation,
            sources=sources,
            remedies=["VERIFY_INSURANCE_MINIMUM_ALREADY_PAID"],
            burden_of_proof=[],
        )

    if analysis_date < deadline:
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=outstanding,
            economic_value=minimum,
            worth_pursuing="WAIT",
            reasoning_summary=(
                "Existe un importe mínimo reconocido y pendiente, pero todavía no han transcurrido cuarenta días "
                "desde la recepción acreditada de la declaración del siniestro."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="WAIT_S01_ARTICLE_18_FORTY_DAYS",
            rule_result="PENDING",
            failed_conditions=[],
            calculation=calculation,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    return EngineResult(
        viability="HIGH",
        scope_status="SUPPORTED",
        claimable_amount=outstanding,
        economic_value=minimum,
        worth_pursuing="YES_IF_LOW_COST" if outstanding < 50 else "YES",
        reasoning_summary=(
            "Han transcurrido cuarenta días desde la recepción acreditada de la declaración del siniestro y existe un "
            "importe mínimo reconocido por el propio asegurador que permanece pendiente. S01 reclama únicamente ese saldo "
            "conforme al artículo 18 y no decide ni cuantifica la mora del artículo 20."
        ),
        counterarguments=[],
        missing_facts=[],
        next_action="PREPARE_S01_INSURANCE_MINIMUM_PAYMENT",
        rule_result="APPLIES",
        failed_conditions=[],
        calculation=calculation,
        sources=sources,
        remedies=["PAY_ACKNOWLEDGED_INSURANCE_MINIMUM"],
        burden_of_proof=[],
    )
