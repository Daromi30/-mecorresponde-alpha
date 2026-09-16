from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .case_lifecycle import complete_current_action, set_current_action
from .models import Action, AuditEvent, Case, Decision, Fact, LegalRuleVersion, LegalSource


EXTENDED_CLAIM_FAMILIES = frozenset({"E01", "E03", "E05", "E06", "E07", "C02", "C03"})


@dataclass(frozen=True)
class ClaimContext:
    case: Case
    decision: Decision
    facts: dict[str, Any]
    next_action: str
    remedies: list[str]


Renderer = Callable[[ClaimContext], dict[str, Any]]


def _latest_facts(db: Session, case_id: str) -> dict[str, Any]:
    rows = db.scalars(
        select(Fact).where(Fact.case_id == case_id).order_by(Fact.created_at.asc())
    ).all()
    latest: dict[str, Any] = {}
    for row in rows:
        latest[row.key] = row.value_json.get("value")
    return latest


def _latest_decision(db: Session, case_id: str) -> Decision | None:
    return db.scalars(
        select(Decision).where(Decision.case_id == case_id).order_by(Decision.created_at.desc())
    ).first()


def _decision_remedies(decision: Decision) -> list[str]:
    result: list[str] = []
    for evaluation in decision.rule_evaluations_json or []:
        for remedy in evaluation.get("remedies") or []:
            if remedy not in result:
                result.append(remedy)
    return result


def _verified_legal_basis(db: Session, decision: Decision) -> list[dict[str, Any]]:
    """Resolve citations from the exact reviewed rule versions used by the decision."""
    basis: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for evaluation in decision.rule_evaluations_json or []:
        if evaluation.get("result") != "APPLIES":
            continue
        rule_id = str(evaluation.get("rule_id") or "")
        version = int(evaluation.get("version") or 0)
        key = (rule_id, version)
        if not rule_id or version <= 0 or key in seen:
            continue
        seen.add(key)
        rule = db.scalar(
            select(LegalRuleVersion).where(
                LegalRuleVersion.rule_id == rule_id,
                LegalRuleVersion.version == version,
                LegalRuleVersion.review_status == "approved",
            )
        )
        if rule is None:
            raise ValueError(f"Reviewed legal rule version missing for {rule_id} v{version}")
        source = db.get(LegalSource, rule.source_id)
        if source is None or source.status != "active" or not source.official_url.startswith("https://www.boe.es/"):
            raise ValueError(f"Verified official legal source missing for {rule_id} v{version}")
        basis.append(
            {
                "rule_id": rule.rule_id,
                "version": rule.version,
                "article": rule.article,
                "source_id": rule.source_id,
                "source": source.title,
                "official_url": source.official_url,
            }
        )
    if not basis:
        raise ValueError("No applicable reviewed legal rule is attached to the current decision")
    return basis


def _render_e01(ctx: ClaimContext) -> dict[str, Any]:
    if ctx.next_action == "PREPARE_E01_PRICING_CORRECTION":
        promised = ctx.facts.get("electricity.pricing_promised_terms") or "las condiciones económicas contratadas"
        applied = ctx.facts.get("electricity.pricing_applied_terms") or "las condiciones aplicadas en factura"
        text = (
            f"Solicito que se apliquen las condiciones económicas contratadas u ofertadas y se refacture el periodo afectado. "
            f"En el expediente consta como condición documentada: {promised}; y como condición aplicada: {applied}. "
            "Si de la refacturación verificable resulta una cantidad a mi favor, solicito su devolución. "
            "No fijo una cuantía monetaria hasta disponer del cálculo sustentado por facturas y magnitudes comprobables."
        )
        claim_type = "E01_PRICING_CORRECTION"
    elif ctx.next_action == "PREPARE_E01_DISCOUNT_CORRECTION":
        text = (
            "Solicito que se respete el descuento promocional documentado y se refacture el periodo afectado conforme a las condiciones ofertadas. "
            "Si la refacturación verificable arroja un cobro superior al debido, solicito la devolución que corresponda. "
            "No se fija una cantidad concreta mientras no exista un cálculo respaldado por la oferta y las facturas."
        )
        claim_type = "E01_DISCOUNT_CORRECTION"
    else:
        raise ValueError("Current E01 action is not ready for a claim package")
    return {"claim_type": claim_type, "amount": 0.0, "text": text}


def _render_e03(ctx: ClaimContext) -> dict[str, Any]:
    if ctx.next_action != "PREPARE_UNAUTHORIZED_SWITCH_RESTORATION":
        raise ValueError("Current E03 action is not ready for a claim package")
    previous = ctx.facts.get("electricity.previous_supplier") or "el comercializador saliente"
    incoming = ctx.facts.get("electricity.incoming_supplier") or "el comercializador entrante"
    wrong_cups = ctx.facts.get("electricity.switch_cups_correct") is False
    no_consent = ctx.facts.get("electricity.express_consent_given") is False
    reason_parts = []
    if no_consent:
        reason_parts.append("sin mi consentimiento expreso")
    if wrong_cups:
        reason_parts.append("con identificación incorrecta del CUPS")
    reason = " y ".join(reason_parts) or "de forma no validada en el expediente"
    amount = round(float(ctx.decision.claimable_amount or 0.0), 2)
    refund = (
        f" Solicito además la devolución de {amount:.2f} € que constan como pagos efectuados por el suministro no solicitado."
        if amount > 0
        else ""
    )
    text = (
        f"Comunico que el cambio hacia {incoming} se produjo {reason}. "
        f"Solicito restituir el punto de suministro a {previous} y al contrato previo al cambio, así como cesar los cargos vinculados al cambio no consentido o erróneo."
        f"{refund}"
    )
    return {"claim_type": "E03_UNAUTHORIZED_SWITCH_RESTORATION", "amount": amount, "text": text}


def _render_e05(ctx: ClaimContext) -> dict[str, Any]:
    if ctx.next_action != "PREPARE_E05_PENALTY_REFUND":
        raise ValueError("Current E05 action is not ready for a claim package")
    amount = round(float(ctx.decision.claimable_amount or 0.0), 2)
    if amount <= 0:
        raise ValueError("No verified termination penalty amount is available")
    text = (
        f"Solicito dejar sin efecto la penalización por rescisión y devolver {amount:.2f} €, importe identificado en el expediente como penalización cobrada o exigida. "
        "La evaluación actual concluye que, con los hechos confirmados, no concurre una excepción que permita automatizar esa penalización."
    )
    return {"claim_type": "E05_TERMINATION_PENALTY_REFUND", "amount": amount, "text": text}


def _render_e06(ctx: ClaimContext) -> dict[str, Any]:
    if ctx.next_action == "PREPARE_E06_LIMIT_REGULARIZATION":
        months = ctx.facts.get("electricity.regularization_period_months")
        text = (
            f"Solicito revisar y recalcular la regularización, que en el expediente figura referida a {months} meses, "
            "limitando el periodo rectificable al máximo legal aplicable y facilitando el desglose de lecturas, consumos, periodos e importes utilizado. "
            "No atribuyo una cantidad concreta como indebida hasta disponer del desglose temporal necesario para calcularla."
        )
        return {"claim_type": "E06_LIMIT_REGULARIZATION", "amount": 0.0, "text": text}
    if ctx.next_action == "PREPARE_E06_READING_CORRECTION":
        text = (
            "Solicito revisar la facturación basada en la lectura controvertida, obtener o utilizar una lectura real o aportada válidamente según corresponda y refacturar a partir de una medida verificable. "
            "Solicito también el detalle de las lecturas y del cálculo aplicado. No se fija una devolución concreta sin reconstruir primero la facturación correcta."
        )
        return {"claim_type": "E06_READING_CORRECTION", "amount": 0.0, "text": text}
    raise ValueError("Current E06 action is not ready for a claim package")


def _render_e07(ctx: ClaimContext) -> dict[str, Any]:
    variants = {
        "PREPARE_E07_CHANGE_CHALLENGE": (
            "E07_CONTRACT_CHANGE_CHALLENGE",
            "Solicito revisar la modificación de condiciones contractuales porque la comunicación registrada en el expediente no cumple todos los requisitos aplicables. "
            "Solicito que se respete la situación contractual previa mientras se revisa la modificación y que se reconozca, cuando proceda, el derecho a resolver el contrato sin coste.",
        ),
        "PREPARE_E07_FIXED_PRICE_CHALLENGE": (
            "E07_FIXED_PRICE_REVIEW_CHALLENGE",
            "Solicito dejar sin efecto la revisión de precio aplicada dentro del periodo que consta como precio fijo y mantener las condiciones contractuales pactadas mientras se revisa la incidencia. "
            "Si existiera un exceso facturado, su cuantificación debe hacerse con las facturas verificadas y no mediante una estimación automática.",
        ),
        "PREPARE_E07_PRICE_REVIEW_CHALLENGE": (
            "E07_PRICE_REVIEW_NOTICE_CHALLENGE",
            "Solicito revisar la aplicación de la revisión de precios porque la comunicación registrada no cumple todos los requisitos de antelación, separación, explicación o contenido comparativo aplicables. "
            "Solicito una comunicación completa y la revisión de los importes aplicados; cualquier devolución monetaria se cuantificará únicamente con facturación verificable.",
        ),
    }
    variant = variants.get(ctx.next_action)
    if variant is None:
        raise ValueError("Current E07 action is not ready for a claim package")
    claim_type, text = variant
    return {"claim_type": claim_type, "amount": 0.0, "text": text}


def _render_c02(ctx: ClaimContext) -> dict[str, Any]:
    product = ctx.facts.get("purchase.product_name") or "el producto"
    if ctx.next_action == "PREPARE_C02_TERMINATION":
        material = ctx.facts.get("purchase.defect_material")
        amount = round(float(ctx.decision.claimable_amount or 0.0), 2)
        if material is not True or amount <= 0:
            raise ValueError("C02 termination is not sufficiently supported for an automatic monetary claim")
        text = (
            f"Tras el intento previo de puesta en conformidad del {product}, comunico la resolución del contrato por la falta de conformidad que persiste y solicito la devolución de {amount:.2f} €. "
            "El expediente confirma que la falta no ha sido tratada como de escasa importancia para esta vía."
        )
        return {"claim_type": "C02_POST_REPAIR_TERMINATION", "amount": amount, "text": text}
    if ctx.next_action == "PREPARE_C02_PRICE_REDUCTION":
        text = (
            f"Tras el intento previo de puesta en conformidad del {product}, solicito una reducción proporcional del precio por la falta de conformidad que persiste. "
            "La cuantía debe corresponder a la diferencia de valor legalmente relevante; MECORRESPONDE no inventa ese valor sin evidencia suficiente para calcularlo."
        )
        return {"claim_type": "C02_PROPORTIONAL_PRICE_REDUCTION", "amount": 0.0, "text": text}
    raise ValueError("Current C02 action is not ready for a claim package")


def _render_c03(ctx: ClaimContext) -> dict[str, Any]:
    product = ctx.facts.get("purchase.product_name") or "el producto"
    ordered = ctx.facts.get("purchase.contract_description") or "lo contratado"
    received = ctx.facts.get("purchase.received_description") or "lo recibido"
    if ctx.next_action == "PREPARE_C03_CONFORMITY_CLAIM":
        text = (
            f"Solicito poner en conformidad sin coste {product}. Lo contratado se describe como: {ordered}; lo recibido se describe como: {received}. "
            "Solicito completar, sustituir o reparar el bien según resulte adecuado para que coincida con lo contratado, sin cargos para la persona consumidora."
        )
        return {"claim_type": "C03_CONTRACT_MISMATCH_CONFORMITY", "amount": 0.0, "text": text}
    if ctx.next_action == "PREPARE_C03_ESCALATED_REMEDY":
        text = (
            f"Reitero la falta de conformidad de {product}: lo contratado se describe como {ordered}, mientras que lo recibido se describe como {received}. "
            "Ante la negativa registrada a poner el bien en conformidad, solicito una medida correctora secundaria conforme a la normativa aplicable. "
            "La reducción del precio o la resolución del contrato, cuando proceda, deberán concretarse según la importancia de la falta y la valoración acreditada; no se fija una cuantía o remedio final sin esa base."
        )
        return {"claim_type": "C03_ESCALATED_CONFORMITY_REMEDY", "amount": 0.0, "text": text}
    raise ValueError("Current C03 action is not ready for a claim package")


RENDERERS: dict[str, Renderer] = {
    "E01": _render_e01,
    "E03": _render_e03,
    "E05": _render_e05,
    "E06": _render_e06,
    "E07": _render_e07,
    "C02": _render_c02,
    "C03": _render_c03,
}


def prepare_extended_claim_package(db: Session, case: Case) -> dict[str, Any]:
    renderer = RENDERERS.get(case.family or "")
    if renderer is None:
        raise ValueError("No extended claim renderer is registered for this family")

    decision = _latest_decision(db, case.id)
    if decision is None:
        raise ValueError("Diagnose the case before preparing a claim")
    if decision.viability not in {"HIGH", "MEDIUM"}:
        raise ValueError("Current diagnosis does not support preparing a claim")

    current = db.get(Action, case.current_action_id) if case.current_action_id else None
    if current is None or current.case_id != case.id:
        raise ValueError("The case has no current action to prepare")

    context = ClaimContext(
        case=case,
        decision=decision,
        facts=_latest_facts(db, case.id),
        next_action=current.type,
        remedies=_decision_remedies(decision),
    )
    rendered = renderer(context)
    legal_basis = _verified_legal_basis(db, decision)
    amount = round(float(rendered.get("amount") or 0.0), 2)
    payload = {
        "claim_type": rendered["claim_type"],
        "remedies": context.remedies,
        "amount": amount,
        "economic_value": decision.economic_value,
        "currency": "EUR",
        "legal_basis": legal_basis,
        "text": rendered["text"],
    }

    complete_current_action(db, case, only_types={current.type})
    action = set_current_action(
        db,
        case,
        "SUBMIT_INITIAL_CLAIM",
        payload=payload,
        status="READY",
    )
    case.status = "READY_TO_SUBMIT"
    db.add(
        AuditEvent(
            case_id=case.id,
            event_type="CLAIM_PACKAGE_PREPARED",
            payload_json={
                "action_id": action.id,
                "amount": amount,
                "economic_value": decision.economic_value,
                "family": case.family,
            },
        )
    )
    db.commit()
    db.refresh(action)
    return {"action_id": action.id, **payload}
