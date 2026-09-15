from __future__ import annotations

from datetime import date
from typing import Any

from .common import EngineResult, FactValue, raw

RD88_URL = "https://www.boe.es/eli/es/rd/2026/02/11/88/con"
CURRENT_RULE_EFFECTIVE = date(2026, 6, 12)


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


def _supported_non_monetary(
    *,
    economic_value: float | None,
    reasoning: str,
    next_action: str,
    counterarguments: list[dict[str, Any]],
    sources: list[dict[str, str]],
    remedies: list[str],
    calculation: dict[str, Any] | None = None,
) -> EngineResult:
    open_material = any(
        c.get("status") == "open" and c.get("impact") in {"material", "critical"}
        for c in counterarguments
    )
    return EngineResult(
        viability="MEDIUM" if open_material else "HIGH",
        scope_status="SUPPORTED",
        claimable_amount=0.0,
        economic_value=economic_value,
        worth_pursuing=_worth(economic_value),
        reasoning_summary=reasoning,
        counterarguments=counterarguments,
        missing_facts=[],
        next_action=next_action,
        rule_result="APPLIES",
        failed_conditions=[],
        calculation=calculation,
        sources=sources,
        remedies=remedies,
        burden_of_proof=[{
            "issue": "reading_and_billing_basis",
            "on": "case_evidence",
            "basis": "RD88_2026_43_45",
            "note": "Deben conservarse factura, periodo regularizado y evidencia de lectura/aviso para distinguir una estimación permitida de una facturación incorrecta.",
        }],
    )


def evaluate_e06(facts: dict[str, FactValue]) -> EngineResult:
    """E06 — readings, estimated consumption and billing regularisations.

    Narrow automation only. Fraud/tampering and technically complex meter
    disputes are never decided automatically.
    """
    sources = [{
        "title": "RD 88/2026, arts. 43-45 y DF 9.4",
        "url": RD88_URL,
    }]
    missing: list[str] = []
    counterarguments: list[dict[str, Any]] = []

    invoice_date = _parse_date(raw(facts, "electricity.reading_issue_invoice_date"))
    issue_type = raw(facts, "electricity.reading_issue_type")
    technical = raw(facts, "electricity.meter_fraud_tampering_or_complex_technical_issue")
    amount_raw = raw(facts, "electricity.regularization_amount")
    amount = round(float(amount_raw), 2) if amount_raw is not None else None

    if invoice_date is None:
        missing.append("electricity.reading_issue_invoice_date")
    elif invoice_date < CURRENT_RULE_EFFECTIVE:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LEGACY_REVIEW",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="La factura o regularización es anterior al 12/06/2026, fecha desde la que surten efectos los artículos 43 a 45 del RD 88/2026. Debe aplicarse el régimen temporal anterior.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_LEGACY",
            rule_result="OUT_OF_VALIDITY",
            failed_conditions=["invoice_before_2026-06-12"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if technical is None:
        missing.append("electricity.meter_fraud_tampering_or_complex_technical_issue")
    elif technical is True:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="TECHNICAL_OR_FRAUD_REVIEW",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="El expediente incluye fraude, manipulación del contador o una controversia técnica compleja de medida. E06 no debe resolverla automáticamente.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_METER_TECHNICAL",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if issue_type is None:
        missing.append("electricity.reading_issue_type")

    if missing:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Faltan datos para distinguir una lectura estimada de una regularización por facturación inferior o superior a la debida.",
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

    if raw(facts, "company.asserts_estimate_allowed", False):
        counterarguments.append({
            "type": "DISTRIBUTOR_ASSERTS_ESTIMATE_ALLOWED",
            "status": "open",
            "impact": "material",
            "origin": "company_response",
        })

    if issue_type == "overbilling_regularization":
        return EngineResult(
            viability="RECLASSIFY",
            scope_status="REDIRECT_E02_A",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary="Si la cuestión es que se facturaron cantidades superiores a las debidas, el tratamiento monetario corresponde a E02-A, que aplica la devolución e intereses del artículo 45.2.",
            counterarguments=counterarguments,
            missing_facts=[],
            next_action="RECLASSIFY_E02_A",
            rule_result="NOT_APPLICABLE",
            failed_conditions=["better_family_e02a"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if issue_type == "underbilling_regularization":
        months_raw = raw(facts, "electricity.regularization_period_months")
        if months_raw is None:
            return EngineResult(
                viability="INSUFFICIENT_INFORMATION",
                scope_status="SUPPORTED",
                claimable_amount=None,
                economic_value=amount,
                worth_pursuing="NEEDS_INFORMATION",
                reasoning_summary="Para analizar una regularización por cantidades facturadas de menos es imprescindible conocer cuántos meses pretende rectificar la comercializadora.",
                counterarguments=counterarguments,
                missing_facts=["electricity.regularization_period_months"],
                next_action="REQUEST_MATERIAL_FACT",
                rule_result="PENDING",
                failed_conditions=[],
                calculation=None,
                sources=sources,
                remedies=[],
                burden_of_proof=[],
            )
        months = int(months_raw)
        if months > 12:
            return _supported_non_monetary(
                economic_value=amount,
                reasoning=(
                    f"La regularización pretende rectificar {months} meses. El artículo 45.2 limita a un año el periodo a rectificar cuando se habían facturado cantidades inferiores a las debidas. "
                    "La alpha no inventa qué parte exacta del importe queda fuera: para cuantificarla hace falta el desglose temporal de consumos y facturas."
                ),
                next_action="PREPARE_E06_LIMIT_REGULARIZATION",
                counterarguments=counterarguments,
                sources=sources,
                remedies=["LIMIT_CORRECTION_PERIOD_TO_ONE_YEAR", "REQUEST_RECALCULATION_AND_BREAKDOWN"],
                calculation={
                    "type": "underbilling_regularization_period_check",
                    "months_claimed": months,
                    "maximum_months_under_current_rule": 12,
                    "amount_not_auto_calculated": True,
                },
            )
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=amount,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary=(
                f"La regularización indicada abarca {months} meses, dentro del máximo de un año del artículo 45.2. "
                "Eso no demuestra por sí solo que el importe sea correcto: si se discuten lecturas, consumos o el cálculo concreto, deben aportarse esos datos para otra evaluación."
            ),
            counterarguments=counterarguments,
            missing_facts=[],
            next_action="EXPLAIN_REGULARIZATION_PERIOD_WITHIN_LIMIT",
            rule_result="FAILED",
            failed_conditions=["regularization_period_not_over_12_months"],
            calculation={"type": "underbilling_regularization_period_check", "months_claimed": months},
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if issue_type != "estimated_reading":
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="El tipo de controversia de lectura no entra en los supuestos estructurados de E06.",
            counterarguments=counterarguments,
            missing_facts=[],
            next_action="HUMAN_REVIEW_READING_DISPUTE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    reason = raw(facts, "electricity.estimated_reading_reason")
    if reason is None:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Para saber si una lectura estimada era admisible hay que conocer por qué no se obtuvo lectura real.",
            counterarguments=counterarguments,
            missing_facts=["electricity.estimated_reading_reason"],
            next_action="REQUEST_MATERIAL_FACT",
            rule_result="PENDING",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if reason == "remote_reading_failure":
        real_bimonthly = raw(facts, "electricity.real_reading_obtained_within_bimonthly_cycle")
        if real_bimonthly is None:
            return EngineResult(
                viability="INSUFFICIENT_INFORMATION",
                scope_status="SUPPORTED",
                claimable_amount=None,
                economic_value=amount,
                worth_pursuing="NEEDS_INFORMATION",
                reasoning_summary="Ante un fallo de lectura remota, el artículo 43.4 exige lectura presencial de modo que exista medida real al menos bimestralmente. Falta saber si esa lectura real se obtuvo.",
                counterarguments=counterarguments,
                missing_facts=["electricity.real_reading_obtained_within_bimonthly_cycle"],
                next_action="REQUEST_MATERIAL_FACT",
                rule_result="PENDING",
                failed_conditions=[],
                calculation=None,
                sources=sources,
                remedies=[],
                burden_of_proof=[],
            )
        if real_bimonthly is False:
            return _supported_non_monetary(
                economic_value=amount,
                reasoning="Consta fallo de lectura remota y no se obtuvo una lectura real dentro del ciclo bimestral. El artículo 43.4 exige efectuar lectura presencial para disponer de medida real al menos bimestralmente.",
                next_action="PREPARE_E06_READING_CORRECTION",
                counterarguments=counterarguments,
                sources=sources,
                remedies=["REQUEST_REAL_READING", "REQUEST_REBILLING_FROM_VERIFIED_READING"],
            )
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=amount,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="Hubo fallo de lectura remota, pero consta una lectura real dentro del ciclo bimestral exigido. La mera existencia de una estimación intermedia no acredita por sí sola una infracción.",
            counterarguments=counterarguments,
            missing_facts=[],
            next_action="CHECK_BILL_AGAINST_REAL_READING",
            rule_result="FAILED",
            failed_conditions=["real_reading_obtained_bimonthly"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if reason == "no_meter_access":
        notice = raw(facts, "electricity.impossible_reading_notice_received")
        if notice is None:
            return EngineResult(
                viability="INSUFFICIENT_INFORMATION",
                scope_status="SUPPORTED",
                claimable_amount=None,
                economic_value=amount,
                worth_pursuing="NEEDS_INFORMATION",
                reasoning_summary="Cuando no puede accederse al equipo, la estimación del artículo 43.5 depende de que se deje un aviso y se dé al usuario la posibilidad de facilitar su lectura.",
                counterarguments=counterarguments,
                missing_facts=["electricity.impossible_reading_notice_received"],
                next_action="REQUEST_MATERIAL_FACT",
                rule_result="PENDING",
                failed_conditions=[],
                calculation=None,
                sources=sources,
                remedies=[],
                burden_of_proof=[],
            )
        if notice is False:
            return _supported_non_monetary(
                economic_value=amount,
                reasoning="La estimación se atribuye a falta de acceso al contador, pero no consta el aviso de imposible lectura exigido por el artículo 43.5 antes de acudir a la estimación.",
                next_action="PREPARE_E06_READING_CORRECTION",
                counterarguments=counterarguments,
                sources=sources,
                remedies=["REQUEST_REAL_READING", "REQUEST_REBILLING_FROM_VERIFIED_READING"],
            )
        supplied = raw(facts, "electricity.user_supplied_reading_within_10_business_days")
        if supplied is None:
            return EngineResult(
                viability="INSUFFICIENT_INFORMATION",
                scope_status="SUPPORTED",
                claimable_amount=None,
                economic_value=amount,
                worth_pursuing="NEEDS_INFORMATION",
                reasoning_summary="Tras el aviso de imposible lectura, el artículo 43.5 permite estimar solo si el usuario no facilita su lectura dentro de los diez días hábiles indicados.",
                counterarguments=counterarguments,
                missing_facts=["electricity.user_supplied_reading_within_10_business_days"],
                next_action="REQUEST_MATERIAL_FACT",
                rule_result="PENDING",
                failed_conditions=[],
                calculation=None,
                sources=sources,
                remedies=[],
                burden_of_proof=[],
            )
        if supplied is True:
            return _supported_non_monetary(
                economic_value=amount,
                reasoning="El usuario facilitó la lectura dentro de los diez días hábiles posteriores al aviso. Con ese hecho confirmado, no encaja la condición del artículo 43.5 que permite estimar por falta de aportación de lectura.",
                next_action="PREPARE_E06_READING_CORRECTION",
                counterarguments=counterarguments,
                sources=sources,
                remedies=["USE_USER_PROVIDED_READING", "REQUEST_REBILLING_FROM_VERIFIED_READING"],
            )
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=amount,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="Consta aviso de imposible lectura y no se facilitó una lectura dentro de los diez días hábiles. En ese supuesto el artículo 43.5 permite estimar el consumo conforme al procedimiento vigente.",
            counterarguments=counterarguments,
            missing_facts=[],
            next_action="EXPLAIN_ESTIMATION_ALLOWED",
            rule_result="FAILED",
            failed_conditions=["estimate_allowed_after_notice_and_no_user_reading"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    return EngineResult(
        viability="PROFESSIONAL_REVIEW",
        scope_status="LIMITED_SCOPE",
        claimable_amount=None,
        economic_value=amount,
        worth_pursuing="PROFESSIONAL_REVIEW",
        reasoning_summary="La causa de la lectura estimada no coincide con los supuestos claros automatizados. Debe revisarse la documentación y el procedimiento de medida aplicable.",
        counterarguments=counterarguments,
        missing_facts=[],
        next_action="HUMAN_REVIEW_READING_DISPUTE",
        rule_result="MANUAL_REVIEW",
        failed_conditions=[],
        calculation=None,
        sources=sources,
        remedies=[],
        burden_of_proof=[],
    )
