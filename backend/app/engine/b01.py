from __future__ import annotations

from datetime import date
from typing import Any

from .common import EngineResult, FactValue, raw

BOE_RDL19_URL = "https://www.boe.es/eli/es/rdl/2018/11/23/19/con"


def _money(value: Any) -> float | None:
    try:
        return round(float(value), 2) if value is not None else None
    except (TypeError, ValueError):
        return None


def evaluate_b01(facts: dict[str, FactValue]) -> EngineResult:
    """B01: narrow fail-closed route for an unauthorized payment under RDL 19/2018 arts. 34, 43-46."""
    sources = [{"title": "Real Decreto-ley 19/2018, arts. 34 y 43 a 46", "url": BOE_RDL19_URL}]
    def result(viability, scope, summary, action, *, amount=None, rule="MANUAL_REVIEW", missing=None, calc=None, failed=None):
        return EngineResult(viability=viability, scope_status=scope, claimable_amount=amount,
            economic_value=_money(raw(facts, "banking.transaction_amount")), worth_pursuing=("YES" if amount and amount >= 50 else "YES_IF_LOW_COST" if amount else "PROFESSIONAL_REVIEW"),
            reasoning_summary=summary, counterarguments=[], missing_facts=missing or [], next_action=action,
            rule_result=rule, failed_conditions=failed or [], calculation=calc, sources=sources,
            remedies=["UNAUTHORIZED_PAYMENT_REFUND"] if rule == "APPLIES" else [], burden_of_proof=[])

    user_type = raw(facts, "banking.user_type")
    if user_type is None:
        return result("INSUFFICIENT_INFORMATION", "SUPPORTED", "Falta confirmar si el usuario es consumidor o microempresa.", "REQUEST_MATERIAL_FACT", rule="PENDING", missing=["banking.user_type"])
    if user_type not in {"consumer", "microenterprise"}:
        return result("PROFESSIONAL_REVIEW", "LIMITED_SCOPE", "Fuera del alcance automático: para otros usuarios el artículo 34 permite pactos que deben revisarse.", "HUMAN_REVIEW_B01_USER_SCOPE")

    unauthorized = raw(facts, "banking.transaction_authorized")
    if unauthorized is None:
        return result("INSUFFICIENT_INFORMATION", "SUPPORTED", "Falta confirmar si la operación fue autorizada.", "REQUEST_MATERIAL_FACT", rule="PENDING", missing=["banking.transaction_authorized"])
    if unauthorized is True:
        return result("OUT_OF_SCOPE", "UNSUPPORTED", "B01 solo trata operaciones que el ordenante niega haber autorizado.", "EXPLAIN_B01_AUTHORIZED", rule="NOT_APPLICABLE")

    for key in ("banking.months_since_debit", "banking.provider_information_was_supplied", "banking.possible_user_fraud_or_gross_negligence", "banking.authentication_evidence_disputed", "banking.provider_suspects_fraud", "banking.payment_initiation_provider_involved", "banking.instrument_lost_stolen_or_misappropriated", "banking.transaction_amount", "banking.refund_received"):
        if raw(facts, key) is None:
            return result("INSUFFICIENT_INFORMATION", "SUPPORTED", "Faltan hechos materiales para aplicar con seguridad los artículos 43 a 46.", "REQUEST_MATERIAL_FACT", rule="PENDING", missing=[key])

    if raw(facts, "banking.possible_user_fraud_or_gross_negligence") is True:
        return result("PROFESSIONAL_REVIEW", "LIMITED_SCOPE", "La posible actuación fraudulenta o negligencia grave exige valoración humana conforme al artículo 46.", "HUMAN_REVIEW_B01_FRAUD_OR_GROSS_NEGLIGENCE")
    if raw(facts, "banking.authentication_evidence_disputed") is True:
        return result("PROFESSIONAL_REVIEW", "LIMITED_SCOPE", "La controversia sobre autenticación o SCA requiere valorar la prueba del artículo 44; el mero registro no decide por sí solo la autorización.", "HUMAN_REVIEW_B01_AUTHENTICATION_EVIDENCE")
    if raw(facts, "banking.provider_suspects_fraud") is True:
        return result("PROFESSIONAL_REVIEW", "LIMITED_SCOPE", "La excepción por sospecha razonable de fraude del artículo 45 requiere comprobar su comunicación escrita al Banco de España.", "HUMAN_REVIEW_B01_PROVIDER_FRAUD_SUSPICION")
    if raw(facts, "banking.payment_initiation_provider_involved") is True:
        return result("PROFESSIONAL_REVIEW", "LIMITED_SCOPE", "La intervención de un proveedor de iniciación de pagos introduce responsabilidades adicionales que B01 no automatiza.", "HUMAN_REVIEW_B01_PISP")

    try:
        months = float(raw(facts, "banking.months_since_debit"))
    except (TypeError, ValueError):
        return result("PROFESSIONAL_REVIEW", "LIMITED_SCOPE", "El plazo desde el adeudo no es verificable.", "HUMAN_REVIEW_B01_TIME_DATA")
    informed = raw(facts, "banking.provider_information_was_supplied")
    if months > 13:
        if informed is False:
            return result("PROFESSIONAL_REVIEW", "LIMITED_SCOPE", "Han pasado más de 13 meses y se discute si el proveedor facilitó la información exigible; debe revisarse la excepción del artículo 43.", "HUMAN_REVIEW_B01_OVER_13_MONTHS_INFORMATION")
        return result("OUT_OF_SCOPE", "UNSUPPORTED", "La comunicación supera el máximo general de 13 meses del artículo 43 y no consta la excepción por falta de información.", "EXPLAIN_B01_OVER_13_MONTHS", rule="NOT_APPLICABLE", failed=["article_43_time_limit"])

    amount = _money(raw(facts, "banking.transaction_amount"))
    if amount is None or amount <= 0:
        return result("PROFESSIONAL_REVIEW", "LIMITED_SCOPE", "El importe documentado no permite cuantificar el reembolso.", "HUMAN_REVIEW_B01_AMOUNT")

    user_share = 0.0
    if raw(facts, "banking.instrument_lost_stolen_or_misappropriated") is True:
        detectable = raw(facts, "banking.loss_detectable_before_payment")
        if detectable is None:
            return result("INSUFFICIENT_INFORMATION", "SUPPORTED", "Falta saber si la pérdida, sustracción o apropiación podía detectarse antes del pago.", "REQUEST_MATERIAL_FACT", rule="PENDING", missing=["banking.loss_detectable_before_payment"])
        if detectable is True:
            user_share = min(50.0, amount)

    refund_received = raw(facts, "banking.refund_received")
    already = 0.0
    if refund_received is True:
        already = _money(raw(facts, "banking.refund_received_amount"))
        if already is None:
            return result("INSUFFICIENT_INFORMATION", "SUPPORTED", "Falta cuantificar el reembolso ya recibido.", "REQUEST_MATERIAL_FACT", rule="PENDING", missing=["banking.refund_received_amount"])
    outstanding = round(max(amount - user_share - already, 0.0), 2)
    calc = {"transaction_amount": amount, "possible_payer_share_article_46": user_share, "already_refunded": already, "outstanding_refund": outstanding, "article_43_months_since_debit": months}
    if outstanding <= 0:
        return result("LOW", "SUPPORTED", "No queda saldo automático pendiente con los importes confirmados.", "EXPLAIN_B01_ALREADY_RESTORED", amount=0.0, rule="APPLIES", calc=calc)
    return result("HIGH", "SUPPORTED", "Con los hechos confirmados, la ruta estrecha B01 solicita el saldo de una operación no autorizada conforme a los artículos 43 a 46, sin convertir la autenticación técnica en prueba automática de autorización.", "PREPARE_B01_UNAUTHORIZED_PAYMENT_REFUND", amount=outstanding, rule="APPLIES", calc=calc)
