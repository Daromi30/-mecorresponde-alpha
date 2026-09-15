from __future__ import annotations

from datetime import date
from typing import Any

from .common import EngineResult, FactValue, raw, verified

BILLING_RULE_START = date(2026, 6, 12)
RD88_URL = "https://www.boe.es/eli/es/rd/2026/02/11/88"
CC_URL = "https://www.boe.es/buscar/act.php?id=BOE-A-1889-4763"


def evaluate_e02a(facts: dict[str, FactValue]) -> EngineResult:
    sources = [{"title":"Real Decreto 88/2026, art. 45.2", "url":RD88_URL}]
    missing: list[str] = []
    invoice_date = raw(facts, "electricity.billing.invoice_date")
    if not invoice_date:
        missing.append("electricity.billing.invoice_date")
    elif isinstance(invoice_date, str):
        invoice_date = date.fromisoformat(invoice_date)
    billed = raw(facts, "electricity.billing.billed_amount")
    due = raw(facts, "electricity.billing.correct_amount")
    if billed is None: missing.append("electricity.billing.billed_amount")
    if due is None: missing.append("electricity.billing.correct_amount")
    if invoice_date and invoice_date < BILLING_RULE_START:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW", scope_status="LEGACY_REVIEW", claimable_amount=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="La factura es anterior a la eficacia del artículo 45 del RD 88/2026 en este ruleset. Debe aplicarse normativa histórica.",
            counterarguments=[], missing_facts=missing, next_action="HUMAN_REVIEW_LEGACY",
            rule_result="OUT_OF_VALIDITY", failed_conditions=["invoice_before_2026-06-12"], calculation=None, sources=sources,
        )
    if missing:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION", scope_status="SUPPORTED", claimable_amount=None,
            worth_pursuing="NEEDS_INFORMATION", reasoning_summary="Faltan los importes o la fecha necesarios para comprobar la sobrefacturación.",
            counterarguments=[], missing_facts=missing, next_action="REQUEST_MATERIAL_FACT", rule_result="PENDING",
            failed_conditions=[], calculation=None, sources=sources,
        )
    over = round(max(float(billed) - float(due), 0), 2)
    calc = {"type":"billed_minus_correct", "billed":float(billed), "correct":float(due), "result":over}
    if over <= 0:
        return EngineResult(
            viability="LOW", scope_status="SUPPORTED", claimable_amount=0.0, worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="Con los importes confirmados no resulta una cantidad facturada por encima de la debida.",
            counterarguments=[], missing_facts=[], next_action="EXPLAIN_NO_OVERBILLING", rule_result="FAILED",
            failed_conditions=["billed_amount_not_above_correct_amount"], calculation=calc, sources=sources,
        )
    confidence_high = verified(facts, "electricity.billing.billed_amount") and verified(facts, "electricity.billing.correct_amount")
    return EngineResult(
        viability="HIGH" if confidence_high else "MEDIUM", scope_status="SUPPORTED", claimable_amount=over,
        worth_pursuing="YES_IF_LOW_COST" if over < 30 else "YES",
        reasoning_summary=(
            f"La factura supera en {over:.2f} € el importe que consta como debido. El artículo 45.2 del RD 88/2026 prevé la devolución de las cantidades indebidamente facturadas en la primera facturación siguiente y, en su ámbito, intereses."
        ),
        counterarguments=[{"type":"CORRECT_AMOUNT_MAY_BE_DISPUTED","status":"open" if not confidence_high else "rebutted","impact":"critical"}],
        missing_facts=[], next_action="PREPARE_INITIAL_CLAIM", rule_result="APPLIES", failed_conditions=[], calculation=calc, sources=sources,
    )


def evaluate_e02b(facts: dict[str, FactValue]) -> EngineResult:
    sources = [{"title":"Código Civil, art. 1895", "url":CC_URL}]
    charges = raw(facts, "electricity.billing.duplicate_charges")
    if not charges:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION", scope_status="SUPPORTED", claimable_amount=None,
            worth_pursuing="NEEDS_INFORMATION", reasoning_summary="Necesitamos identificar los dos cargos y confirmar que corresponden a la misma deuda.",
            counterarguments=[], missing_facts=["electricity.billing.duplicate_charges"], next_action="REQUEST_DUPLICATE_CHARGE_EVIDENCE",
            rule_result="PENDING", failed_conditions=[], calculation=None, sources=sources,
        )
    same_debt = raw(facts, "electricity.billing.same_debt")
    if same_debt is None:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION", scope_status="SUPPORTED", claimable_amount=None,
            worth_pursuing="NEEDS_INFORMATION", reasoning_summary="Dos cargos de importe similar no bastan: hay que confirmar que ambos pagan la misma factura o deuda.",
            counterarguments=[{"type":"CHARGES_MAY_REFER_TO_DIFFERENT_DEBTS","status":"open","impact":"critical"}],
            missing_facts=["electricity.billing.same_debt"], next_action="CONFIRM_SAME_DEBT", rule_result="PENDING",
            failed_conditions=[], calculation=None, sources=sources,
        )
    if same_debt is False:
        return EngineResult(
            viability="LOW", scope_status="SUPPORTED", claimable_amount=0.0, worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="Los cargos corresponden a deudas distintas, por lo que no hay duplicidad acreditada.",
            counterarguments=[{"type":"DIFFERENT_DEBTS","status":"confirmed","impact":"critical"}], missing_facts=[],
            next_action="EXPLAIN_NO_DUPLICATE", rule_result="FAILED", failed_conditions=["same_debt=false"], calculation=None, sources=sources,
        )
    verified_charges = [c for c in charges if c.get("evidence_verified", False)]
    if len(verified_charges) < 2:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION", scope_status="SUPPORTED", claimable_amount=None,
            worth_pursuing="NEEDS_INFORMATION", reasoning_summary="La duplicidad necesita al menos dos cargos acreditados de la misma deuda.",
            counterarguments=[], missing_facts=["second_verified_charge"], next_action="REQUEST_DUPLICATE_CHARGE_EVIDENCE",
            rule_result="PENDING", failed_conditions=[], calculation=None, sources=sources,
        )
    amounts = sorted(float(c.get("amount", 0)) for c in verified_charges)
    duplicate_amount = round(min(amounts[-2:]), 2)
    calc = {"type":"one_duplicate_payment", "charges":verified_charges, "result":duplicate_amount}
    return EngineResult(
        viability="HIGH" if verified(facts, "electricity.billing.same_debt") else "MEDIUM",
        scope_status="SUPPORTED", claimable_amount=duplicate_amount,
        worth_pursuing="YES_IF_LOW_COST" if duplicate_amount < 30 else "YES",
        reasoning_summary=(
            f"Hay dos cargos acreditados vinculados a la misma deuda; se identifica {duplicate_amount:.2f} € como pago duplicado a restituir. Este supuesto se trata como cobro indebido y no se equipara automáticamente a la regla sectorial de sobrefacturación del artículo 45."
        ),
        counterarguments=[], missing_facts=[], next_action="PREPARE_INITIAL_CLAIM", rule_result="APPLIES",
        failed_conditions=[], calculation=calc, sources=sources,
    )
