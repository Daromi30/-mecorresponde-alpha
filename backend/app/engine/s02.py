from __future__ import annotations

import calendar
from datetime import date
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


def _minus_one_calendar_month(value: date) -> date:
    year = value.year - (1 if value.month == 1 else 0)
    month = 12 if value.month == 1 else value.month - 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def evaluate_s02(facts: dict[str, FactValue]) -> EngineResult:
    """S02 — policyholder opposition to automatic renewal under Article 22.2.

    This route does not decide mid-term cancellation, life-insurance incompatibilities,
    premium refunds, insurer termination or whether a late notice can still be accepted.
    """
    sources = [{"title": "Ley 50/1980 de Contrato de Seguro, art. 22", "url": LCS_URL}]
    role = raw(facts, "insurance.contract_role")
    insurance_kind = raw(facts, "insurance.policy_kind")
    renewal = raw(facts, "insurance.automatic_renewal_provided")
    wants_nonrenewal = raw(facts, "insurance.policyholder_wants_nonrenewal")
    period_end = _parse_date(raw(facts, "insurance.current_period_end_date"))
    period_end_evidence = raw(facts, "insurance.current_period_end_date_evidence")
    analysis_date = _parse_date(raw(facts, "system.analysis_date")) or date.today()

    missing: list[str] = []
    for key, value in [
        ("insurance.contract_role", role),
        ("insurance.policy_kind", insurance_kind),
        ("insurance.automatic_renewal_provided", renewal),
        ("insurance.policyholder_wants_nonrenewal", wants_nonrenewal),
        ("insurance.current_period_end_date", period_end),
        ("insurance.current_period_end_date_evidence", period_end_evidence),
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
            reasoning_summary="Faltan hechos esenciales para comprobar una oposición a la prórroga conforme al artículo 22.",
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

    if role != "policyholder":
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="S02 automatiza únicamente la oposición a la prórroga ejercida por el tomador del seguro.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_S02_ROLE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if insurance_kind == "life":
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "El artículo 22.5 excluye la aplicación de los apartados anteriores cuando sean incompatibles "
                "con la regulación del seguro sobre la vida. S02 no automatiza seguros de vida."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_S02_LIFE_INSURANCE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if insurance_kind not in {"non_life"}:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="No está confirmado que la póliza encaje en el alcance no vida automatizado de S02.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_S02_POLICY_KIND",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if renewal is not True:
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=None,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="No consta una prórroga automática a la que sea necesario oponerse mediante S02.",
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_S02_NO_AUTOMATIC_RENEWAL",
            rule_result="NOT_APPLICABLE",
            failed_conditions=["automatic_renewal_required"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if wants_nonrenewal is not True:
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=None,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="El tomador no desea oponerse a la próxima prórroga, por lo que S02 no genera una comunicación.",
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_S02_NONRENEWAL_NOT_SELECTED",
            rule_result="NOT_APPLICABLE",
            failed_conditions=["policyholder_nonrenewal_intent_required"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    assert period_end is not None
    if period_end <= analysis_date:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "El período asegurado indicado ya ha concluido o concluye hoy. S02 no presume que una oposición tardía "
                "impida la prórroga ni sustituye el análisis de otras vías."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_S02_PERIOD_ALREADY_ENDING",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if period_end_evidence is not True:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "Sin una fecha de conclusión del período en curso acreditable, S02 no calcula el último día seguro "
                "para cumplir el mes de antelación del artículo 22.2."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_S02_PERIOD_END_EVIDENCE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    last_safe_notice_date = _minus_one_calendar_month(period_end)
    calculation = {
        "current_period_end_date": period_end.isoformat(),
        "last_safe_notice_date": last_safe_notice_date.isoformat(),
        "one_calendar_month_notice_required": True,
    }

    if analysis_date > last_safe_notice_date:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "La fecha de análisis queda dentro del último mes del período. S02 no concluye automáticamente que "
                "la póliza pueda darse de baja antes de la renovación; una comunicación tardía requiere revisión."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_S02_LATE_NONRENEWAL",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=calculation,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    return EngineResult(
        viability="HIGH",
        scope_status="SUPPORTED",
        claimable_amount=0.0,
        economic_value=None,
        worth_pursuing="YES_IF_LOW_COST",
        reasoning_summary=(
            "El tomador de una póliza no vida con prórroga automática quiere oponerse por escrito y la fecha acreditada "
            "permite hacerlo con al menos un mes de antelación a la conclusión del período en curso, conforme al artículo 22.2."
        ),
        counterarguments=[],
        missing_facts=[],
        next_action="PREPARE_S02_POLICY_NONRENEWAL_NOTICE",
        rule_result="APPLIES",
        failed_conditions=[],
        calculation=calculation,
        sources=sources,
        remedies=["OPPOSE_NEXT_POLICY_RENEWAL"],
        burden_of_proof=[],
    )
