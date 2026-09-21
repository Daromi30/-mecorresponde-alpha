from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .engine.c01 import evaluate_c01
from .engine.c04 import evaluate_c04
from .engine.c05 import evaluate_c05
from .engine.common import FactValue
from .engine.e02 import evaluate_e02a, evaluate_e02b
from .engine.e04a import evaluate_e04a
from .engine.e04b import evaluate_e04b
from .engine.gateway import DeterministicAlphaGateway
from .engine.questions import next_question
from .evidence_context import current_company_response_evidence
from .family_manifest import family_title
from .models import (
    AIRun,
    Action,
    AuditEvent,
    Calculation,
    Case,
    Communication,
    Counterargument,
    Decision,
    Document,
    Evidence,
    Fact,
    LegalRuleVersion,
    LegalSource,
    RuleEvaluation,
)
from .reviews import HumanReview


gateway = DeterministicAlphaGateway()


def audit(db: Session, case_id: str | None, event_type: str, payload: dict[str, Any] | None = None):
    db.add(AuditEvent(case_id=case_id, event_type=event_type, payload_json=payload or {}))


def create_human_review(
    db: Session,
    case: Case,
    reason: str,
    priority: str = "NORMAL",
    context: dict[str, Any] | None = None,
) -> HumanReview:
    existing = db.scalars(
        select(HumanReview).where(
            HumanReview.case_id == case.id,
            HumanReview.reason == reason,
            HumanReview.status == "OPEN",
        )
    ).first()
    if existing:
        return existing
    review = HumanReview(
        case_id=case.id,
        reason=reason,
        priority=priority,
        context_json=context or {},
    )
    db.add(review)
    case.status = "HUMAN_REVIEW"
    audit(db, case.id, "HUMAN_REVIEW_TRIGGERED", {"reason": reason, "priority": priority})
    return review


def create_case(db: Session, message: str) -> Case:
    classification = gateway.classify(message)
    case = Case(
        status="INTAKE",
        vertical=classification["vertical"],
        family=classification["family"],
        title=family_title(classification["family"]),
        raw_intake=message,
    )
    db.add(case)
    db.flush()
    db.add(AIRun(case_id=case.id, task="classify", structured_output=classification))
    audit(db, case.id, "CASE_STARTED", {"classification": classification})
    if classification["family"] is None:
        case.status = "CLOSED_UNSUPPORTED"
    db.commit()
    db.refresh(case)
    return case


def latest_facts(db: Session, case_id: str) -> dict[str, FactValue]:
    rows = db.scalars(
        select(Fact).where(Fact.case_id == case_id).order_by(Fact.created_at.asc())
    ).all()
    latest: dict[str, Fact] = {}
    for row in rows:
        latest[row.key] = row
    return {
        key: FactValue(
            value=row.value_json.get("value"),
            state=row.state,
            user_confirmed=row.user_confirmed,
        )
        for key, row in latest.items()
    }


def upsert_fact(
    db: Session,
    case: Case,
    key: str,
    value: Any,
    state: str = "asserted",
    materiality: str = "critical",
    confidence: float | None = None,
    user_confirmed: bool = True,
    created_by: str = "user",
) -> Fact:
    prev = db.scalars(
        select(Fact)
        .where(Fact.case_id == case.id, Fact.key == key)
        .order_by(Fact.created_at.desc())
    ).first()
    fact = Fact(
        case_id=case.id,
        key=key,
        value_json={"value": value},
        state=state,
        materiality=materiality,
        confidence=confidence,
        user_confirmed=user_confirmed,
        created_by=created_by,
        supersedes_fact_id=prev.id if prev else None,
    )
    db.add(fact)
    db.flush()
    if created_by in {"user", "company", "human"}:
        db.add(
            Evidence(
                case_id=case.id,
                fact_id=fact.id,
                source_type=created_by,
                strength="strong" if user_confirmed or created_by == "human" else "medium",
            )
        )
    audit(
        db,
        case.id,
        "FACT_RECORDED",
        {
            "fact_id": fact.id,
            "key": key,
            "state": state,
            "source": created_by,
            "supersedes": prev.id if prev else None,
        },
    )
    case.status = "INTAKE"
    db.commit()
    db.refresh(fact)
    return fact


def get_next_question(db: Session, case: Case) -> dict[str, Any]:
    return next_question(latest_facts(db, case.id), case.family)


def _ensure_source(
    db: Session,
    source_id: str,
    authority: str,
    title: str,
    official_url: str,
    publication_date: date | None,
) -> LegalSource:
    source = db.get(LegalSource, source_id)
    if not source:
        source = LegalSource(
            id=source_id,
            authority=authority,
            title=title,
            official_url=official_url,
            publication_date=publication_date,
            jurisdiction="ES",
            status="active",
        )
        db.add(source)
        db.flush()
    return source


def _ensure_rule(
    db: Session,
    rule_id: str,
    version: int,
    valid_from: date,
    source_id: str,
    article: str,
    conditions: dict[str, Any],
    consequence: dict[str, Any],
    interpretation: str,
) -> LegalRuleVersion:
    rule = db.scalars(
        select(LegalRuleVersion).where(
            LegalRuleVersion.rule_id == rule_id,
            LegalRuleVersion.version == version,
        )
    ).first()
    if not rule:
        rule = LegalRuleVersion(
            rule_id=rule_id,
            version=version,
            valid_from=valid_from,
            source_id=source_id,
            article=article,
            conditions_json=conditions,
            consequence_json=consequence,
            interpretation=interpretation,
        )
        db.add(rule)
        db.flush()
    return rule


def seed_legal(db: Session) -> dict[str, LegalRuleVersion]:
    _ensure_source(
        db,
        "RD88_2026",
        "BOE / Ministerio para la Transición Ecológica",
        "Real Decreto 88/2026, de 11 de febrero",
        "https://www.boe.es/eli/es/rd/2026/02/11/88",
        date(2026, 2, 11),
    )
    _ensure_source(
        db,
        "TRLGDCU",
        "BOE",
        "Real Decreto Legislativo 1/2007, texto refundido de la Ley General para la Defensa de los Consumidores y Usuarios",
        "https://www.boe.es/buscar/act.php?id=BOE-A-2007-20555",
        date(2007, 11, 16),
    )
    _ensure_source(
        db,
        "CODIGO_CIVIL",
        "BOE",
        "Código Civil",
        "https://www.boe.es/buscar/act.php?id=BOE-A-1889-4763",
        date(1889, 7, 25),
    )
    return {
        "ELEC_ADDON_END_WITH_SUPPLY": _ensure_rule(
            db,
            "ELEC_ADDON_END_WITH_SUPPLY",
            1,
            date(2026, 2, 12),
            "RD88_2026",
            "32.4",
            {"contracted_with_supply": True, "supply_ended": True, "express_keep_request": False},
            {"additional_service_should_end_with_supply": True},
            "Los servicios adicionales contratados junto con el suministro se extinguen con éste salvo indicación expresa del consumidor.",
        ),
        "UNSOLICITED_SERVICE_NO_PAYMENT": _ensure_rule(
            db,
            "UNSOLICITED_SERVICE_NO_PAYMENT",
            1,
            date(2014, 3, 29),
            "TRLGDCU",
            "66 quáter",
            {"service_not_requested": True, "payment_claimed": True},
            {"consumer_not_obliged_to_pay": True},
            "No puede exigirse pago por servicios no solicitados; la falta de respuesta no equivale a consentimiento.",
        ),
        "ADDITIONAL_PAYMENT_EXPRESS_CONSENT": _ensure_rule(
            db,
            "ADDITIONAL_PAYMENT_EXPRESS_CONSENT",
            1,
            date(2014, 3, 29),
            "TRLGDCU",
            "60 bis",
            {"additional_payment": True},
            {"express_consent_required": True, "burden_on_business": True},
            "Los pagos adicionales requieren consentimiento expreso y el empresario debe probar su obtención.",
        ),
        "ELEC_OVERBILL_REFUND": _ensure_rule(
            db,
            "ELEC_OVERBILL_REFUND",
            1,
            date(2026, 6, 12),
            "RD88_2026",
            "45.2",
            {"billed_above_due": True},
            {"refund_in_next_bill": True, "interest": "legal_interest_plus_150bp"},
            "Las cantidades facturadas por encima de las debidas deben devolverse conforme al artículo dentro de su ámbito temporal.",
        ),
        "UNDUE_PAYMENT_RESTITUTION": _ensure_rule(
            db,
            "UNDUE_PAYMENT_RESTITUTION",
            1,
            date(1889, 8, 16),
            "CODIGO_CIVIL",
            "1895",
            {"payment_not_due": True, "delivered_by_error": True},
            {"restitution_required": True},
            "El cobro de lo que no había derecho a cobrar y fue entregado por error genera obligación de restitución.",
        ),
        "GOODS_CONFORMITY_CURRENT": _ensure_rule(
            db,
            "GOODS_CONFORMITY_CURRENT",
            1,
            date(2022, 1, 1),
            "TRLGDCU",
            "117-121",
            {"consumer_purchase": True, "seller_is_business": True, "lack_of_conformity": True},
            {"primary_remedies": ["repair", "replacement"], "manifestation_period_years": 3, "presumption_years": 2},
            "Régimen vigente de conformidad de bienes: responsabilidad del empresario, puesta en conformidad, remedios y reglas temporales.",
        ),
        "GOODS_DELIVERY_CURRENT": _ensure_rule(
            db,
            "GOODS_DELIVERY_CURRENT",
            1,
            date(2022, 1, 1),
            "TRLGDCU",
            "66 bis",
            {"consumer_purchase": True, "seller_is_business": True, "goods_not_delivered": True},
            {
                "default_delivery_limit_days": 30,
                "additional_period_normally_required_before_termination": True,
                "immediate_termination_exceptions": ["seller_refusal", "essential_delivery_date"],
                "business_bears_proof_of_compliance": True,
            },
            "La falta de entrega no genera automáticamente resolución inmediata en todos los casos: como regla se requiere un plazo adicional adecuado, salvo negativa del empresario o fecha esencial; el empresario soporta la carga de probar el cumplimiento del artículo.",
        ),
        "DISTANCE_WITHDRAWAL_CURRENT": _ensure_rule(
            db,
            "DISTANCE_WITHDRAWAL_CURRENT",
            1,
            date(2022, 5, 28),
            "TRLGDCU",
            "102-108",
            {"consumer_distance_contract": True, "article_103_exception": False},
            {
                "ordinary_withdrawal_days": 14,
                "missing_information_extension_months": 12,
                "refund_days_after_notification": 14,
                "seller_may_withhold_pending_return_or_proof": True,
            },
            "En contratos a distancia, salvo las excepciones del artículo 103, existe derecho de desistimiento; el plazo ordinario es de catorce días, puede ampliarse por omisión de información y el reembolso está sujeto a las reglas de los artículos 107 y 108.",
        ),
    }


EVALUATORS = {
    "E04-B": evaluate_e04b,
    "E04-A": evaluate_e04a,
    "E02-A": evaluate_e02a,
    "E02-B": evaluate_e02b,
    "C01": evaluate_c01,
    "C04": evaluate_c04,
    "C05": evaluate_c05,
}


FAMILY_RULES = {
    "E04-B": ["ELEC_ADDON_END_WITH_SUPPLY"],
    "E04-A": ["UNSOLICITED_SERVICE_NO_PAYMENT", "ADDITIONAL_PAYMENT_EXPRESS_CONSENT"],
    "E02-A": ["ELEC_OVERBILL_REFUND"],
    "E02-B": ["UNDUE_PAYMENT_RESTITUTION"],
    "C01": ["GOODS_CONFORMITY_CURRENT"],
    "C04": ["GOODS_DELIVERY_CURRENT"],
    "C05": ["DISTANCE_WITHDRAWAL_CURRENT"],
}


def diagnose(db: Session, case: Case):
    evaluator = EVALUATORS.get(case.family or "")
    if not evaluator:
        raise ValueError("This case family is not automated in the current alpha")

    rules = seed_legal(db)
    facts = latest_facts(db, case.id)
    facts.setdefault(
        "system.analysis_date",
        FactValue(value=date.today().isoformat(), state="confirmed", user_confirmed=False),
    )
    result = evaluator(facts)
    snapshot = {
        key: {"value": value.value, "state": value.state, "user_confirmed": value.user_confirmed}
        for key, value in facts.items()
    }

    economic_value = getattr(result, "economic_value", None)
    if economic_value is None:
        economic_value = result.claimable_amount
    remedies = list(getattr(result, "remedies", []) or [])
    burden = list(getattr(result, "burden_of_proof", []) or [])

    evaluated_rules: list[dict[str, Any]] = []
    for rule_id in FAMILY_RULES.get(case.family or "", []):
        rule = rules[rule_id]
        db.add(
            RuleEvaluation(
                case_id=case.id,
                rule_version_id=rule.id,
                facts_snapshot=snapshot,
                result=result.rule_result,
                missing_conditions=result.missing_facts,
                failed_conditions=result.failed_conditions,
                engine_version=f"{(case.family or 'unknown').lower()}-1",
            )
        )
        evaluated_rules.append(
            {
                "rule_id": rule.rule_id,
                "version": rule.version,
                "result": result.rule_result,
                "remedies": remedies,
                "burden_of_proof": burden,
            }
        )

    for counterargument in result.counterarguments:
        db.add(
            Counterargument(
                case_id=case.id,
                type=counterargument["type"],
                origin=counterargument.get("origin", "known_rule"),
                description=counterargument["type"].replace("_", " ").title(),
                status=counterargument.get("status", "open"),
                impact=str(counterargument.get("impact", "material"))[:20],
            )
        )

    if result.calculation is not None:
        db.add(
            Calculation(
                case_id=case.id,
                type=result.calculation.get("type", "case_calculation"),
                inputs_json=result.calculation,
                formula_version=f"{case.family}-CALC-1",
                result=float(result.claimable_amount or 0.0),
                explanation="Cálculo determinista reproducible a partir de los hechos confirmados del expediente.",
            )
        )

    decision = Decision(
        case_id=case.id,
        viability=result.viability,
        scope_status=result.scope_status,
        claimable_amount=result.claimable_amount,
        economic_value=economic_value,
        worth_pursuing=result.worth_pursuing,
        professional_review_required=result.viability == "PROFESSIONAL_REVIEW",
        reasoning_summary=result.reasoning_summary,
        counterarguments_snapshot=result.counterarguments,
        rule_evaluations_json=evaluated_rules,
    )
    db.add(decision)
    db.flush()

    action = Action(
        case_id=case.id,
        type=result.next_action,
        payload_json={
            "claimable_amount": result.claimable_amount,
            "economic_value": economic_value,
            "remedies": remedies,
            "burden_of_proof": burden,
        },
    )
    db.add(action)
    db.flush()
    case.current_decision_id = decision.id
    case.current_action_id = action.id

    if result.missing_facts:
        case.status = "NEEDS_INFORMATION"
    elif result.viability == "RECLASSIFY":
        case.status = "REANALYZING"
    elif (
        result.viability == "PROFESSIONAL_REVIEW"
        or result.scope_status in {"LEGACY_REVIEW", "LIMITED_SCOPE"}
        or result.next_action.startswith("HUMAN_REVIEW")
    ):
        create_human_review(
            db,
            case,
            result.next_action or result.scope_status,
            "HIGH",
            {"family": case.family, "scope_status": result.scope_status},
        )
    else:
        case.status = "DIAGNOSED"

    audit(
        db,
        case.id,
        "DIAGNOSIS_GENERATED",
        {
            "decision_id": decision.id,
            "viability": result.viability,
            "family": case.family,
            "economic_value": economic_value,
            "claimable_amount": result.claimable_amount,
        },
    )
    db.commit()
    return result, decision, action


def confirm_document_fact(
    db: Session,
    case: Case,
    document: Document,
    *,
    key: str,
    value: Any,
    locator: str | None = None,
    excerpt: str | None = None,
    materiality: str = "critical",
) -> Fact:
    prev = db.scalars(
        select(Fact).where(Fact.case_id == case.id, Fact.key == key).order_by(Fact.created_at.desc())
    ).first()
    fact = Fact(
        case_id=case.id,
        key=key,
        value_json={"value": value},
        state="confirmed",
        materiality=materiality,
        confidence=1.0,
        user_confirmed=True,
        created_by="user",
        supersedes_fact_id=prev.id if prev else None,
    )
    db.add(fact)
    db.flush()
    db.add(
        Evidence(
            case_id=case.id,
            fact_id=fact.id,
            document_id=document.id,
            source_type="document",
            locator=locator,
            excerpt=excerpt,
            strength="strong",
        )
    )
    audit(
        db,
        case.id,
        "DOCUMENT_FACT_CONFIRMED",
        {"document_id": document.id, "fact_id": fact.id, "key": key},
    )
    db.commit()
    db.refresh(fact)
    return fact


def analyze_company_response(db: Session, case: Case, text: str):
    result = gateway.analyze_response(text)
    evidence = current_company_response_evidence()
    db.add(AIRun(case_id=case.id, task="analyze_response", structured_output=result))
    communication = Communication(
        case_id=case.id,
        direction="INBOUND",
        channel=evidence.channel if evidence is not None else "user_paste",
        body=text,
        occurred_on=evidence.received_on if evidence is not None else None,
        received_at=datetime.now(timezone.utc),
        reference_number=evidence.reference_number if evidence is not None else None,
    )
    db.add(communication)
    if evidence is not None:
        # Flush only to materialize the communication id; the transaction is still uncommitted.
        db.flush()
        audit(
            db,
            case.id,
            "COMPANY_RESPONSE_RECORDED",
            {
                "communication_id": communication.id,
                "received_on": evidence.received_on.isoformat() if evidence.received_on else None,
                "channel": evidence.channel,
                "reference": evidence.reference_number,
            },
        )
    argument_fact_map = {
        "INDEPENDENT_ADDON_CONTRACT": "company.asserts_independent_addon_contract",
        "EXPRESS_KEEP_REQUEST": "company.asserts_keep_request",
        "CONSENT_EVIDENCE": "company.asserts_consent",
        "CORRECT_AMOUNT_DISPUTED": "company.asserts_correct_amount",
        "DIFFERENT_DEBTS": "company.asserts_different_debts",
        "MISUSE_OR_ACCIDENTAL_DAMAGE": "company.asserts_misuse",
        "OUTSIDE_LEGAL_GUARANTEE": "company.asserts_outside_guarantee",
        "REFER_TO_MANUFACTURER": "company.redirects_to_manufacturer",
        "DELIVERY_PROOF_ASSERTED": "company.asserts_delivered",
        "WITHDRAWAL_LATE_ASSERTED": "company.asserts_withdrawal_late",
        "WITHDRAWAL_EXCEPTION_ASSERTED": "company.asserts_withdrawal_exception",
        "INTERNET_INTERRUPTION_COMPENSATION_APPLIED_ASSERTED": "company.asserts_internet_interruption_compensation_applied",
        "FLIGHT_REFUND_ALREADY_PAID_ASSERTED": "company.asserts_flight_refund_already_paid",
        "DENIED_BOARDING_COMPENSATION_PAID_ASSERTED": "company.asserts_denied_boarding_compensation_paid",
        "PAYMENT_AUTHENTICATED_ASSERTED": "company.asserts_payment_authenticated",
        "ARTICLE_48_4_EXCEPTION_ASSERTED": "company.asserts_article_48_4_exception",
        "BANK_FEE_REQUESTED_AND_PROVIDED_ASSERTED": "company.asserts_bank_fee_requested_and_provided",
        "RENT_DEPOSIT_DEDUCTIONS_ASSERTED": "company.asserts_rent_deposit_deductions",
    }
    for argument in result["arguments"]:
        key = argument_fact_map.get(argument)
        if key:
            upsert_fact(
                db,
                case,
                key,
                True,
                state="asserted",
                user_confirmed=False,
                created_by="company",
            )
    case.status = "RESPONSE_RECEIVED"
    audit(db, case.id, "RESPONSE_ANALYZED", result)
    db.commit()
    return result


def prepare_claim_package(db: Session, case: Case) -> dict[str, Any]:
    decision = db.scalars(
        select(Decision).where(Decision.case_id == case.id).order_by(Decision.created_at.desc())
    ).first()
    if not decision:
        raise ValueError("Diagnose the case before preparing a claim")
    if decision.viability not in {"HIGH", "MEDIUM"}:
        raise ValueError("Current diagnosis does not support preparing a claim")

    facts = latest_facts(db, case.id)
    facts.setdefault(
        "system.analysis_date",
        FactValue(value=date.today().isoformat(), state="confirmed", user_confirmed=False),
    )
    amount = round(float(decision.claimable_amount or 0.0), 2)

    if case.family == "E04-B":
        if amount <= 0:
            raise ValueError("Current diagnosis does not support preparing a monetary claim")
        addon = facts.get("electricity.addon.identity").value if facts.get("electricity.addon.identity") else "servicio adicional"
        end_date = facts.get("electricity.supply_end_date").value if facts.get("electricity.supply_end_date") else None
        remedies = [
            "CANCEL_ADDON",
            "REFUND_VERIFIED_POST_TERMINATION_CHARGES",
            "CEASE_FUTURE_CHARGES",
            "CONFIRM_CANCELLATION",
        ]
        legal_basis = [
            {"rule_id": "ELEC_ADDON_END_WITH_SUPPLY", "article": "32.4", "source": "RD 88/2026"}
        ]
        text = (
            f"Solicito la cancelación definitiva del servicio adicional {addon}, el cese de nuevos cargos y la devolución de {amount:.2f} €. "
            f"El suministro eléctrico con la antigua comercializadora finalizó el {end_date}. "
            "La reclamación se apoya en el artículo 32.4 del Real Decreto 88/2026."
        )
        claim_type = "E04-B_INITIAL_CLAIM"
    elif case.family == "E04-A":
        if amount <= 0:
            raise ValueError("Current diagnosis does not support preparing a monetary claim")
        addon = facts.get("electricity.addon.identity").value if facts.get("electricity.addon.identity") else "servicio adicional"
        remedies = ["CANCEL_ADDON", "REFUND_UNAUTHORIZED_CHARGES", "CEASE_FUTURE_CHARGES"]
        legal_basis = [
            {"rule_id": "UNSOLICITED_SERVICE_NO_PAYMENT", "article": "66 quáter", "source": "TRLGDCU"},
            {"rule_id": "ADDITIONAL_PAYMENT_EXPRESS_CONSENT", "article": "60 bis", "source": "TRLGDCU"},
        ]
        text = (
            f"Solicito la cancelación del servicio {addon}, el cese de cargos y la devolución de {amount:.2f} €. "
            "No reconozco haber solicitado ni consentido expresamente este servicio. Los artículos 66 quáter y 60 bis del TRLGDCU "
            "protegen frente a servicios no solicitados y pagos adicionales sin consentimiento expreso."
        )
        claim_type = "E04-A_INITIAL_CLAIM"
    elif case.family == "E02-A":
        if amount <= 0:
            raise ValueError("Current diagnosis does not support preparing a monetary claim")
        remedies = ["CORRECT_INVOICE", "REFUND_OVERBILLED_AMOUNT"]
        legal_basis = [
            {"rule_id": "ELEC_OVERBILL_REFUND", "article": "45.2", "source": "RD 88/2026"}
        ]
        text = (
            f"Solicito la corrección de la facturación y la devolución de {amount:.2f} € facturados por encima de lo debido, "
            "conforme al artículo 45.2 del Real Decreto 88/2026."
        )
        claim_type = "E02-A_INITIAL_CLAIM"
    elif case.family == "E02-B":
        if amount <= 0:
            raise ValueError("Current diagnosis does not support preparing a monetary claim")
        remedies = ["REFUND_DUPLICATE_PAYMENT"]
        legal_basis = [
            {"rule_id": "UNDUE_PAYMENT_RESTITUTION", "article": "1895", "source": "Código Civil"}
        ]
        text = (
            f"Solicito la devolución de {amount:.2f} € correspondientes a un segundo pago de la misma deuda, "
            "conforme al artículo 1895 del Código Civil sobre cobro de lo indebido."
        )
        claim_type = "E02-B_INITIAL_CLAIM"
    elif case.family == "C01":
        result = evaluate_c01(facts)
        product = facts.get("purchase.product_name").value if facts.get("purchase.product_name") else "producto"
        remedies = list(result.remedies)
        legal_basis = [
            {"rule_id": "GOODS_CONFORMITY_CURRENT", "article": "117-121", "source": "TRLGDCU"}
        ]
        text = (
            f"Solicito la puesta en conformidad del {product} sin coste, mediante reparación o sustitución según proceda legalmente. "
            "La falta de conformidad se analiza bajo los artículos 117 a 121 del TRLGDCU. "
            "Esta solicitud no convierte automáticamente el valor del producto en una devolución en efectivo: el remedio aplicable depende de la fase y de los hechos acreditados."
        )
        claim_type = "GOODS_CONFORMITY"
        amount = 0.0
    elif case.family == "C04":
        result = evaluate_c04(facts)
        product = facts.get("purchase.product_name").value if facts.get("purchase.product_name") else "pedido"
        legal_basis = [
            {"rule_id": "GOODS_DELIVERY_CURRENT", "article": "66 bis", "source": "TRLGDCU"}
        ]
        if result.next_action == "GIVE_ADDITIONAL_DELIVERY_PERIOD":
            remedies = ["DELIVERY"]
            amount = 0.0
            claim_type = "C04_ADDITIONAL_DELIVERY_DEMAND"
            text = (
                f"Requiero la entrega del {product} sin más demora y concedo un plazo adicional adecuado para el cumplimiento. "
                "El requerimiento se formula conforme al artículo 66 bis del TRLGDCU, reservándome la resolución del contrato si el plazo adicional vence sin entrega."
            )
        elif result.next_action == "PREPARE_NON_DELIVERY_TERMINATION":
            if amount <= 0:
                raise ValueError("The non-delivery termination has no verified paid amount to recover")
            remedies = ["TERMINATE_CONTRACT", "REFUND_AMOUNT_PAID"]
            claim_type = "C04_NON_DELIVERY_TERMINATION"
            text = (
                f"Ante la falta de entrega del {product}, comunico la resolución del contrato y solicito la devolución de {amount:.2f} €. "
                "La resolución se fundamenta en el artículo 66 bis del TRLGDCU y en el supuesto de resolución identificado en el expediente."
            )
        else:
            raise ValueError("Current C04 action does not require sending a claim yet")
    elif case.family == "C05":
        result = evaluate_c05(facts)
        product = facts.get("purchase.product_name").value if facts.get("purchase.product_name") else "producto"
        legal_basis = [
            {"rule_id": "DISTANCE_WITHDRAWAL_CURRENT", "article": "102-108", "source": "TRLGDCU"}
        ]
        if result.next_action == "SEND_WITHDRAWAL_NOTICE":
            remedies = ["WITHDRAWAL", "REFUND_AFTER_VALID_WITHDRAWAL"]
            amount = 0.0
            claim_type = "C05_WITHDRAWAL_NOTICE"
            text = (
                f"Comunico de forma inequívoca mi decisión de desistir de la compra a distancia del {product}. "
                "Solicito confirmación de la recepción de este desistimiento y las instrucciones necesarias para la devolución y el reembolso conforme a los artículos 102 a 108 del TRLGDCU."
            )
        elif result.next_action == "PREPARE_WITHDRAWAL_REFUND_CLAIM":
            if amount <= 0:
                raise ValueError("No outstanding withdrawal refund is currently calculated")
            remedies = ["REFUND"]
            claim_type = "C05_WITHDRAWAL_REFUND"
            text = (
                f"El desistimiento de la compra a distancia del {product} fue comunicado dentro del plazo aplicable. "
                f"Solicito el reembolso pendiente de {amount:.2f} € conforme a los artículos 102 a 108, y en particular al artículo 107, del TRLGDCU."
            )
        else:
            raise ValueError("Current C05 action does not require sending a claim yet")
    else:
        raise ValueError("Claim renderer not implemented for this family")

    payload = {
        "claim_type": claim_type,
        "remedies": remedies,
        "amount": amount,
        "economic_value": decision.economic_value,
        "currency": "EUR",
        "legal_basis": legal_basis,
        "text": text,
    }
    action = Action(
        case_id=case.id,
        type="SUBMIT_INITIAL_CLAIM",
        status="READY",
        payload_json=payload,
    )
    db.add(action)
    db.flush()
    case.current_action_id = action.id
    case.status = "READY_TO_SUBMIT"
    audit(
        db,
        case.id,
        "CLAIM_PACKAGE_PREPARED",
        {
            "action_id": action.id,
            "amount": amount,
            "economic_value": decision.economic_value,
            "family": case.family,
        },
    )
    db.commit()
    db.refresh(action)
    return {"action_id": action.id, **payload}
