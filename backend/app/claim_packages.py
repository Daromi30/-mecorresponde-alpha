from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .case_lifecycle import complete_current_action, set_current_action
from .legal_source_registry import is_trusted_official_legal_url
from .models import Action, AuditEvent, Case, Decision, Fact, LegalRuleVersion, LegalSource


# These families were historically installed as a chain of extension wrappers.
# The registry gives them one final dispatch boundary without changing their public
# claim-package contract.
REGISTERED_EXTENSION_FAMILIES = frozenset({"E01", "E03", "E05", "E06", "E07", "C02", "C03", "T01", "T02", "V01", "V02", "V03"})


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
        if source is None or source.status != "active" or not is_trusted_official_legal_url(source.official_url):
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
        text = (
            "Solicito que se aplique el precio o modalidad económica efectivamente ofertada/contratada y que se revisen las facturas del periodo afectado. "
            "El artículo 30 del RD 88/2026 exige condiciones económicas claras y transparentes y el artículo 61 del TRLGDCU hace exigible el contenido de la oferta o promoción. "
            "La cuantía concreta de cualquier devolución deberá calcularse con las facturas, consumos y precios verificables."
        )
        claim_type = "E01_CONTRACTED_PRICE_OR_TARIFF_CORRECTION"
    elif ctx.next_action == "PREPARE_E01_DISCOUNT_CORRECTION":
        text = (
            "Solicito que se respeten las condiciones del descuento/promoción ofertado y que se revisen las facturas afectadas. "
            "El artículo 30.1.k del RD 88/2026 exige indicar expresamente la duración de los descuentos promocionales y los términos o precios sobre los que se aplican, y el artículo 61 del TRLGDCU integra la oferta en el contrato. "
            "La devolución exacta, si procede, se calculará únicamente con documentación de facturación verificable."
        )
        claim_type = "E01_PROMOTIONAL_DISCOUNT_CORRECTION"
    else:
        raise ValueError("Current E01 action requires information, explanation or human review rather than a claim")
    return {
        "claim_type": claim_type,
        "amount": 0.0,
        "amount_status": "REQUIRES_VERIFIED_BILLING_CALCULATION",
        "text": text,
    }


def _render_e03(ctx: ClaimContext) -> dict[str, Any]:
    if ctx.next_action != "PREPARE_UNAUTHORIZED_SWITCH_RESTORATION":
        raise ValueError("Current E03 action requires more information or human review")
    previous = ctx.facts.get("electricity.previous_supplier") or "comercializadora anterior"
    incoming = ctx.facts.get("electricity.incoming_supplier") or "comercializadora entrante"
    amount = round(float(ctx.decision.claimable_amount or 0.0), 2)
    text = (
        f"Impugno el cambio de suministro desde {previous} a {incoming} por falta de consentimiento expreso o por error en la identificación del punto, según los hechos confirmados del expediente. "
        "Solicito la restitución al comercializador saliente y al contrato previo conforme a los artículos 18 y 51.3 del RD 88/2026, así como el cese de cargos por suministro no solicitado."
    )
    if amount > 0:
        text += f" Solicito además la devolución de {amount:.2f} € ya pagados por el suministro no solicitado identificado en el expediente."
    return {"claim_type": "E03_UNAUTHORIZED_SWITCH_RESTORATION", "amount": amount, "text": text}


def _render_e05(ctx: ClaimContext) -> dict[str, Any]:
    if ctx.next_action != "PREPARE_E05_PENALTY_REFUND":
        raise ValueError("Current E05 action requires review rather than an automated claim")
    amount = round(float(ctx.decision.claimable_amount or 0.0), 2)
    if amount <= 0:
        raise ValueError("No verified termination penalty amount to recover")
    text = (
        f"Solicito la anulación y devolución de la penalización por rescisión de {amount:.2f} €. "
        "Soy persona física acogida al segmento 2.0TD y, conforme al artículo 28.3 del Real Decreto 88/2026, el contrato y sus prórrogas pueden rescindirse sin penalización salvo el supuesto excepcional de contrato a precio fijo antes de la primera prórroga anual, que no concurre según los hechos confirmados del expediente."
    )
    return {"claim_type": "E05_TERMINATION_PENALTY_REFUND", "amount": amount, "text": text}


def _render_e06(ctx: ClaimContext) -> dict[str, Any]:
    if ctx.next_action == "PREPARE_E06_READING_CORRECTION":
        text = (
            "Solicito la revisión de la lectura utilizada, la obtención o utilización de una lectura real verificable y la refacturación que corresponda conforme a los artículos 43 a 45 del RD 88/2026. "
            "La reclamación se limita al procedimiento de lectura/facturación acreditado y no presupone una cuantía monetaria que no haya sido calculada con datos verificables."
        )
        return {
            "claim_type": "E06_READING_CORRECTION",
            "amount": 0.0,
            "amount_status": "PENDING_VERIFIED_REBILLING",
            "text": text,
        }
    if ctx.next_action == "PREPARE_E06_LIMIT_REGULARIZATION":
        months = ctx.facts.get("electricity.regularization_period_months")
        text = (
            f"La regularización pretende rectificar {months} meses. Solicito que se limite el periodo corregido al máximo de un año previsto en el artículo 45.2 del RD 88/2026 y que se facilite un desglose mensual reproducible del nuevo cálculo. "
            "No fijo automáticamente una cantidad a devolver o dejar de pagar sin ese desglose."
        )
        return {
            "claim_type": "E06_LIMIT_UNDERBILLING_REGULARIZATION",
            "amount": 0.0,
            "amount_status": "REQUIRES_MONTHLY_BREAKDOWN",
            "text": text,
        }
    raise ValueError("Current E06 action requires information or human review rather than a claim")


def _render_e07(ctx: ClaimContext) -> dict[str, Any]:
    variants = {
        "PREPARE_E07_CHANGE_CHALLENGE": (
            "E07_CONTRACT_CHANGE_NOTICE_CHALLENGE",
            "Impugno la aplicación de la modificación de condiciones por no constar una comunicación que cumpla íntegramente el artículo 6.1.m del RD 88/2026. "
            "Solicito una comunicación previa válida y confirmación de mi derecho a rescindir sin coste. Si existe una diferencia económica ya facturada, deberá cuantificarse con las facturas y precios verificables antes de reclamar un importe concreto.",
        ),
        "PREPARE_E07_PRICE_REVIEW_CHALLENGE": (
            "E07_PRICE_REVIEW_NOTICE_CHALLENGE",
            "Impugno la aplicación de la revisión de precio hasta que se acredite una comunicación conforme al artículo 6.1.n y a la disposición transitoria séptima del RD 88/2026, incluyendo antelación, razones y alcance, comparación de precios y estimación comparativa del coste anual. "
            "Cualquier devolución monetaria se calculará separadamente si las facturas prueban un exceso.",
        ),
        "PREPARE_E07_FIXED_PRICE_CHALLENGE": (
            "E07_FIXED_PRICE_REVIEW_CHALLENGE",
            "Impugno la revisión aplicada durante el periodo de precio fijo del contrato. Solicito que se respete el precio pactado o que se identifique la base contractual y normativa específica que permitiría el cambio, teniendo en cuenta que el artículo 30.1.i del RD 88/2026 excluye las cláusulas de revisión en contratos a precio fijo.",
        ),
    }
    variant = variants.get(ctx.next_action)
    if variant is None:
        raise ValueError("Current E07 action requires information, reclassification or explanation rather than a claim")
    claim_type, text = variant
    return {
        "claim_type": claim_type,
        "amount": 0.0,
        "amount_status": "MONETARY_EFFECT_REQUIRES_VERIFIED_INVOICES",
        "text": text,
    }


def _render_c02(ctx: ClaimContext) -> dict[str, Any]:
    product = ctx.facts.get("purchase.product_name") or "producto"
    if ctx.next_action == "PREPARE_C02_TERMINATION":
        amount = round(float(ctx.decision.claimable_amount or 0.0), 2)
        if amount <= 0:
            raise ValueError("Termination is not sufficiently supported to calculate a full-price refund")
        text = (
            f"Tras el intento previo de puesta en conformidad del {product}, persiste o ha aparecido una nueva falta de conformidad. "
            f"Comunico mi voluntad de resolver el contrato y solicito la restitución de {amount:.2f} €, con fundamento en los artículos 119 y 119 ter del TRLGDCU. "
            "La resolución queda sujeta a que la falta no sea de escasa importancia."
        )
        return {"claim_type": "C02_TERMINATION_AFTER_FAILED_CONFORMITY", "amount": amount, "text": text}
    if ctx.next_action == "PREPARE_C02_PRICE_REDUCTION":
        text = (
            f"Tras el intento previo de puesta en conformidad del {product}, persiste o ha aparecido una nueva falta de conformidad. "
            "Solicito una reducción proporcionada del precio conforme a los artículos 119 y 119 bis del TRLGDCU. "
            "El importe debe fijarse de forma proporcional a la diferencia de valor y no se inventa automáticamente en esta alpha."
        )
        return {"claim_type": "C02_PRICE_REDUCTION_AFTER_FAILED_CONFORMITY", "amount": 0.0, "text": text}
    raise ValueError("Choose the secondary remedy before preparing the C02 claim")


def _render_c03(ctx: ClaimContext) -> dict[str, Any]:
    product = ctx.facts.get("purchase.product_name") or "producto"
    if ctx.next_action == "PREPARE_C03_CONFORMITY_CLAIM":
        text = (
            f"El {product} recibido no se ajusta a lo contratado en descripción, tipo, cantidad, calidad o accesorios. "
            "Solicito su puesta en conformidad sin coste mediante sustitución, entrega de lo faltante o la medida correctora que corresponda, conforme a los artículos 115 bis, 117 y 118 del TRLGDCU."
        )
        return {"claim_type": "C03_CONTRACT_MISMATCH_CONFORMITY", "amount": 0.0, "text": text}
    if ctx.next_action == "PREPARE_C03_ESCALATED_REMEDY":
        text = (
            f"El {product} recibido no se ajusta a lo contratado y el vendedor ya ha rechazado ponerlo en conformidad. "
            "Solicito la medida correctora secundaria que corresponda —reducción proporcionada del precio o resolución si la falta no es de escasa importancia— conforme a los artículos 119 a 119 ter del TRLGDCU."
        )
        return {"claim_type": "C03_CONTRACT_MISMATCH_ESCALATED", "amount": 0.0, "text": text}
    raise ValueError("Current C03 action does not require sending a claim yet")


def _render_t01(ctx: ClaimContext) -> dict[str, Any]:
    if ctx.next_action != "PREPARE_T01_INTERNET_INTERRUPTION_COMPENSATION":
        raise ValueError("Current T01 action requires information or human review rather than a claim")
    amount = round(float(ctx.decision.claimable_amount or 0.0), 2)
    if amount <= 0:
        raise ValueError("No outstanding verified T01 compensation to request")
    daytime = float(ctx.facts.get("telecom.affected_hours_8_22") or 0.0)
    automatic = daytime > 6.0
    text = (
        f"Solicito la compensación pendiente de {amount:.2f} € por la interrupción temporal del servicio de acceso a internet, "
        "calculada mediante el prorrateo de la cuota fija atribuible a internet por el tiempo de interrupción, conforme al artículo 16 del Real Decreto 899/2009."
    )
    if automatic:
        text += (
            " La interrupción superó seis horas, continuas o discontinuas, entre las 8:00 y las 22:00, "
            "por lo que el artículo 16.1 prevé su abono automático en la factura del período inmediato."
        )
    text += " Esta reclamación no cuantifica daños adicionales, que el artículo 18 trata de forma separada."
    return {
        "claim_type": "T01_FIXED_INTERNET_INTERRUPTION_COMPENSATION",
        "amount": amount,
        "text": text,
    }


def _render_t02(ctx: ClaimContext) -> dict[str, Any]:
    if ctx.next_action != "PREPARE_T02_FREE_TERMINATION_NOTICE":
        raise ValueError("Current T02 action requires information or human review rather than a termination notice")
    notice_date = ctx.facts.get("telecom.change_notice_date")
    text = (
        "Comunico mi decisión de resolver el contrato sin coste adicional como consecuencia del cambio de condiciones anunciado"
        + (f" el {notice_date}" if notice_date else "")
        + ", en ejercicio del derecho previsto en el artículo 67.8 de la Ley 11/2022, General de Telecomunicaciones. "
        "Según los hechos confirmados del expediente, el cambio no se encuadra en las excepciones automatizadas del artículo 67.8 "
        "y no se conservará un terminal subvencionado que requiera calcular una compensación conforme al artículo 67.10. "
        "Esta comunicación no presupone un derecho a mantener indefinidamente las condiciones anteriores ni reclama una cuantía monetaria no verificada."
    )
    return {
        "claim_type": "T02_FREE_TERMINATION_AFTER_CONTRACT_CHANGE",
        "amount": 0.0,
        "text": text,
    }


def _render_v01(ctx: ClaimContext) -> dict[str, Any]:
    if ctx.next_action != "PREPARE_V01_CANCELLATION_REFUND":
        raise ValueError("Current V01 action requires information or human review rather than a refund claim")
    amount = round(float(ctx.decision.claimable_amount or 0.0), 2)
    if amount <= 0:
        raise ValueError("No outstanding verified V01 refund to request")
    text = (
        f"Solicito el reembolso pendiente de {amount:.2f} € correspondiente al vuelo cancelado, "
        "conforme al artículo 5.1.a), en relación con el artículo 8.1.a), del Reglamento (CE) n.º 261/2004. "
        "El expediente confirma una reserva de un único vuelo con salida desde la Unión Europea, la elección de reembolso "
        "y el precio documentado del billete. Esta solicitud se limita al reembolso del billete y no cuantifica ni reclama "
        "la compensación adicional del artículo 7."
    )
    return {
        "claim_type": "V01_CANCELLED_FLIGHT_TICKET_REFUND",
        "amount": amount,
        "text": text,
    }


def _render_v02(ctx: ClaimContext) -> dict[str, Any]:
    if ctx.next_action != "PREPARE_V02_FIVE_HOUR_DELAY_REFUND":
        raise ValueError("Current V02 action requires information or human review rather than a refund claim")
    amount = round(float(ctx.decision.claimable_amount or 0.0), 2)
    if amount <= 0:
        raise ValueError("No outstanding verified V02 refund to request")
    delay = ctx.facts.get("travel.departure_delay_hours")
    text = (
        f"Solicito el reembolso pendiente de {amount:.2f} € del billete del vuelo que no utilicé después de que "
        f"el retraso en la salida alcanzara {delay} horas. El artículo 6.1.iii) del Reglamento (CE) n.º 261/2004 "
        "remite en ese supuesto al reembolso del artículo 8.1.a). El expediente limita el cálculo a un único vuelo "
        "con precio documentado. Esta solicitud no cuantifica ni reclama una compensación adicional por retraso."
    )
    return {
        "claim_type": "V02_FIVE_HOUR_DELAY_TICKET_REFUND",
        "amount": amount,
        "text": text,
    }


def _render_v03(ctx: ClaimContext) -> dict[str, Any]:
    if ctx.next_action != "PREPARE_V03_DENIED_BOARDING_COMPENSATION":
        raise ValueError("Current V03 action requires information or human review rather than a compensation claim")
    amount = round(float(ctx.decision.claimable_amount or 0.0), 2)
    if amount <= 0:
        raise ValueError("No outstanding verified V03 compensation to request")
    text = (
        f"Solicito el pago pendiente de {amount:.2f} € por la denegación involuntaria de embarque, "
        "conforme al artículo 4.3 en relación con el artículo 7 del Reglamento (CE) n.º 261/2004. "
        "El expediente confirma reserva y presentación válidas, ausencia de un motivo razonable automatizado "
        "del artículo 2.j) y la banda de distancia utilizada para el cálculo."
    )
    if ctx.decision.calculation and ctx.decision.calculation.get("article_7_2_reduction_applied"):
        text += " La cuantía incorpora la reducción del 50 % prevista en el artículo 7.2 por el transporte alternativo."
    return {
        "claim_type": "V03_INVOLUNTARY_DENIED_BOARDING_COMPENSATION",
        "amount": amount,
        "text": text,
    }


RENDERERS: dict[str, Renderer] = {
    "E01": _render_e01,
    "E03": _render_e03,
    "E05": _render_e05,
    "E06": _render_e06,
    "E07": _render_e07,
    "C02": _render_c02,
    "C03": _render_c03,
    "T01": _render_t01,
    "T02": _render_t02,
    "V01": _render_v01,
    "V02": _render_v02,
    "V03": _render_v03,
}


def prepare_registered_claim_package(db: Session, case: Case) -> dict[str, Any]:
    renderer = RENDERERS.get(case.family or "")
    if renderer is None:
        raise ValueError("No registry claim renderer is registered for this family")

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
    if rendered.get("amount_status"):
        payload["amount_status"] = rendered["amount_status"]

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
                "amount_status": payload.get("amount_status"),
                "economic_value": decision.economic_value,
                "family": case.family,
            },
        )
    )
    db.commit()
    db.refresh(action)
    return {"action_id": action.id, **payload}
