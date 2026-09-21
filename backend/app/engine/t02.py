from __future__ import annotations

import calendar
from datetime import date
from typing import Any

from .common import EngineResult, FactValue, raw

LGT_URL = "https://www.boe.es/eli/es/l/2022/06/28/11"


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _plus_one_calendar_month(value: date) -> date:
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def evaluate_t02(facts: dict[str, FactValue]) -> EngineResult:
    """T02 — announced unilateral change to telecom contract terms.

    Automated scope is deliberately narrow: a final user received a clear durable
    notice of an adverse/non-exempt change, is still within the one-month exercise
    window, wants to terminate, and is not retaining a subsidized terminal.
    Defective notices and terminal-compensation cases fail closed to human review.
    """
    sources = [{"title": "Ley 11/2022, art. 67.8 y 67.10", "url": LGT_URL}]
    missing: list[str] = []

    final_user = raw(facts, "telecom.final_user_contract")
    notice_received = raw(facts, "telecom.change_notice_received")
    exception_type = raw(facts, "telecom.change_exception_type")

    if final_user is None:
        missing.append("telecom.final_user_contract")
    if final_user is False:
        return EngineResult(
            viability="OUT_OF_SCOPE",
            scope_status="UNSUPPORTED",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary="T02 automatiza el derecho del usuario final de un servicio de comunicaciones electrónicas disponible al público.",
            counterarguments=[],
            missing_facts=[],
            next_action="REDIRECT_NON_FINAL_USER_TELECOM_CASE",
            rule_result="NOT_APPLICABLE",
            failed_conditions=["final_user_scope_required"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if notice_received is None:
        missing.append("telecom.change_notice_received")
    if exception_type is None:
        missing.append("telecom.change_exception_type")

    if exception_type == "unknown":
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="No está claro si el cambio entra en una de las excepciones del artículo 67.8; T02 no presume que el derecho de resolución sea aplicable.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_T02_CHANGE_EXCEPTION",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if exception_type in {"benefit_only", "administrative_no_negative", "legally_required"}:
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=None,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary=(
                "El artículo 67.8 exceptúa del derecho específico de resolución sin coste por cambio contractual "
                "los cambios exclusivamente beneficiosos, los estrictamente administrativos sin efectos negativos "
                "y los impuestos normativamente."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_T02_EXCLUDED_CHANGE",
            rule_result="FAILED",
            failed_conditions=["article_67_8_exception"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if notice_received is False:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "El artículo 67.8 exige comunicación previa del cambio. Si el operador ha aplicado o pretende aplicar "
                "un cambio sin comunicación verificable, T02 no presume automáticamente su ineficacia ni un remedio concreto."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_T02_NO_NOTICE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    notice_date = _parse_date(raw(facts, "telecom.change_notice_date"))
    effective_date = _parse_date(raw(facts, "telecom.change_effective_date"))
    analysis_date = _parse_date(raw(facts, "system.analysis_date")) or date.today()
    rights_info = raw(facts, "telecom.notice_informed_free_termination_right")
    durable = raw(facts, "telecom.notice_clear_and_durable")
    valid_reason = raw(facts, "telecom.contract_contains_valid_change_reason")
    wants_terminate = raw(facts, "telecom.user_wants_to_terminate")
    retained_terminal = raw(facts, "telecom.retains_subsidized_terminal")

    for key, value in [
        ("telecom.change_notice_date", notice_date),
        ("telecom.change_effective_date", effective_date),
        ("telecom.notice_informed_free_termination_right", rights_info),
        ("telecom.notice_clear_and_durable", durable),
        ("telecom.contract_contains_valid_change_reason", valid_reason),
        ("telecom.user_wants_to_terminate", wants_terminate),
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
            reasoning_summary="Faltan hechos necesarios para comprobar de forma segura el alcance del artículo 67.8.",
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

    assert notice_date is not None
    assert effective_date is not None

    if notice_date > analysis_date or effective_date < notice_date:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="Las fechas confirmadas no permiten reconstruir de forma coherente la comunicación y el cambio contractual.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_T02_DATE_INCONSISTENCY",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    exercise_until = _plus_one_calendar_month(notice_date)
    advance_until = _plus_one_calendar_month(notice_date)
    lead_time_compliant = effective_date >= advance_until

    if rights_info is not True or durable is not True or valid_reason is not True:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "La comunicación o la base contractual del cambio no cumple de forma confirmada todos los elementos "
                "que T02 necesita para automatizar una resolución sin coste. El sistema no inventa las consecuencias "
                "jurídicas de una notificación defectuosa."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_T02_DEFECTIVE_NOTICE_OR_REASON",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation={
                "type": "telecom_contract_change_notice_check",
                "exercise_until": exercise_until.isoformat(),
                "minimum_effective_date_for_one_month_notice": advance_until.isoformat(),
                "lead_time_compliant": lead_time_compliant,
            },
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if analysis_date > exercise_until:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "La fecha de análisis queda fuera del mes contado desde la comunicación. T02 no concluye que no exista "
                "ninguna otra vía, pero no genera automáticamente el aviso de resolución del artículo 67.8."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_T02_EXERCISE_WINDOW",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation={
                "type": "telecom_contract_change_notice_check",
                "exercise_until": exercise_until.isoformat(),
                "lead_time_compliant": lead_time_compliant,
            },
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if wants_terminate is False:
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=None,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary=(
                "Con los hechos actuales el artículo 67.8 reconoce una opción de resolución sin coste por el cambio "
                "anunciado, pero el usuario no desea ejercerla. T02 no sustituye ese objetivo por otro remedio."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_T02_FREE_TERMINATION_OPTION",
            rule_result="APPLIES",
            failed_conditions=[],
            calculation={
                "type": "telecom_contract_change_notice_check",
                "exercise_until": exercise_until.isoformat(),
                "lead_time_compliant": lead_time_compliant,
            },
            sources=sources,
            remedies=["FREE_TERMINATION_OPTION"],
            burden_of_proof=[],
        )

    if retained_terminal is None:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Falta confirmar si existe un terminal subvencionado que el usuario vaya a conservar al resolver el contrato.",
            counterarguments=[],
            missing_facts=["telecom.retains_subsidized_terminal"],
            next_action="REQUEST_MATERIAL_FACT",
            rule_result="PENDING",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if retained_terminal is True:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "El artículo 67.10 contempla una posible compensación vinculada al equipo terminal subvencionado que "
                "el usuario conserve. T02 no calcula esa cantidad sin datos verificables del terminal y del contrato."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_T02_SUBSIDIZED_TERMINAL",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
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
            "El cambio anunciado no encaja en las excepciones confirmadas del artículo 67.8; la comunicación informa "
            "del derecho de resolución, consta en soporte duradero y el usuario está dentro del mes para ejercerlo. "
            "No se atribuye automáticamente ningún derecho a conservar las condiciones anteriores."
        ),
        counterarguments=[],
        missing_facts=[],
        next_action="PREPARE_T02_FREE_TERMINATION_NOTICE",
        rule_result="APPLIES",
        failed_conditions=[],
        calculation={
            "type": "telecom_contract_change_notice_check",
            "exercise_until": exercise_until.isoformat(),
            "minimum_effective_date_for_one_month_notice": advance_until.isoformat(),
            "lead_time_compliant": lead_time_compliant,
        },
        sources=sources,
        remedies=["TERMINATE_WITHOUT_ADDITIONAL_COST"],
        burden_of_proof=[],
    )
