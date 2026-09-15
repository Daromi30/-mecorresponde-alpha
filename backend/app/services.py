from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .engine.c01 import evaluate_c01
from .engine.common import FactValue
from .engine.e02 import evaluate_e02a, evaluate_e02b
from .engine.e04a import evaluate_e04a
from .engine.e04b import evaluate_e04b
from .engine.gateway import DeterministicAlphaGateway
from .engine.questions import next_question
from .models import (
    AIRun, Action, AuditEvent, Calculation, Case, Communication, Counterargument,
    Decision, Document, DocumentExtraction, Evidence, Fact, HumanReview,
    LegalRuleVersion, LegalSource, RuleEvaluation,
)

gateway = DeterministicAlphaGateway()

TITLE_BY_FAMILY = {
    "E04-B": "Mantenimiento tras cambio de comercializadora",
    "E04-A": "Servicio adicional no contratado",
    "E02-A": "Posible sobrefacturación eléctrica",
    "E02-B": "Posible cobro duplicado",
    "C01": "Producto defectuoso o garantía rechazada",
}

EVALUATORS: dict[str, Callable] = {
    "E04-B": evaluate_e04b,
    "E04-A": evaluate_e04a,
    "E02-A": evaluate_e02a,
    "E02-B": evaluate_e02b,
    "C01": evaluate_c01,
}

RULE_BY_FAMILY = {
    "E04-B": "ELEC_ADDON_END_WITH_SUPPLY",
    "E04-A": "CONSUMER_UNREQUESTED_SERVICE",
    "E02-A": "ELEC_OVERBILL_REFUND",
    "E02-B": "PAYMENT_UNDUE_RESTITUTION",
    "C01": "GOODS_CONFORMITY_CURRENT",
}


def audit(db: Session, case_id: str | None, event_type: str, payload: dict[str, Any] | None = None):
    db.add(AuditEvent(case_id=case_id, event_type=event_type, payload_json=payload or {}))


def create_case(db: Session, message: str) -> Case:
    classification = gateway.classify(message)
    family = classification["family"]
    case = Case(
        status="INTAKE",
        vertical=classification["vertical"],
        family=family,
        title=TITLE_BY_FAMILY.get(family, "Caso por clasificar"),
        raw_intake=message,
    )
    db.add(case)
    db.flush()
    db.add(AIRun(case_id=case.id, task="classify", structured_output=classification))
    audit(db, case.id, "CASE_STARTED", {"classification": classification})
    if family is None:
        case.status = "CLOSED_UNSUPPORTED"
    db.commit()
    db.refresh(case)
    return case


def latest_facts(db: Session, case_id: str) -> dict[str, FactValue]:
    rows = db.scalars(select(Fact).where(Fact.case_id == case_id).order_by(Fact.created_at.asc())).all()
    latest: dict[str, Fact] = {}
    for row in rows:
        latest[row.key] = row
    return {
        key: FactValue(value=row.value_json.get("value"), state=row.state, user_confirmed=row.user_confirmed)
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
    create_provenance: bool = True,
) -> Fact:
    prev = db.scalars(
        select(Fact).where(Fact.case_id == case.id, Fact.key == key).order_by(Fact.created_at.desc())
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
    if create_provenance and created_by == "user":
        db.add(Evidence(
            case_id=case.id,
            fact_id=fact.id,
            source_type="user",
            strength="strong" if user_confirmed else "medium",
        ))
    audit(db, case.id, "FACT_RECORDED", {
        "fact_id": fact.id, "key": key, "state": state,
        "source": created_by, "supersedes": prev.id if prev else None,
    })
    case.status = "INTAKE"
    db.commit()
    db.refresh(fact)
    return fact


def confirm_document_fact(
    db: Session, case: Case, document: Document, key: str, value: Any,
    locator: str | None = None, excerpt: str | None = None,
) -> Fact:
    fact = upsert_fact(
        db, case, key, value, state="confirmed", user_confirmed=True,
        created_by="document", create_provenance=False,
    )
    db.add(Evidence(
        case_id=case.id,
        fact_id=fact.id,
        document_id=document.id,
        source_type="document",
        locator=locator,
        excerpt=excerpt,
        strength="strong",
    ))
    audit(db, case.id, "DOCUMENT_FACT_CONFIRMED", {"document_id": document.id, "fact_id": fact.id, "key": key})
    db.commit()
    return fact


def get_next_question(db: Session, case: Case) -> dict[str, Any]:
    return next_question(latest_facts(db, case.id), case.family)


def _source(db: Session, source_id: str, authority: str, title: str, url: str, publication_date: date | None):
    src = db.get(LegalSource, source_id)
    if not src:
        src = LegalSource(
            id=source_id, authority=authority, title=title, official_url=url,
            publication_date=publication_date, jurisdiction="ES", status="active",
        )
        db.add(src)
        db.flush()
    return src


def _rule(
    db: Session, rule_id: str, valid_from: date, source_id: str, article: str,
    interpretation: str, conditions: dict[str, Any] | None = None,
    consequence: dict[str, Any] | None = None,
):
    rule = db.scalars(
        select(LegalRuleVersion).where(LegalRuleVersion.rule_id == rule_id, LegalRuleVersion.version == 1)
    ).first()
    if not rule:
        rule = LegalRuleVersion(
            rule_id=rule_id, version=1, valid_from=valid_from, source_id=source_id,
            article=article, conditions_json=conditions or {}, consequence_json=consequence or {},
            interpretation=interpretation, review_status="approved",
        )
        db.add(rule)
        db.flush()
    return rule


def seed_legal(db: Session) -> dict[str, LegalRuleVersion]:
    rd88 = _source(
        db, "RD88_2026", "BOE / Ministerio para la Transición Ecológica",
        "Real Decreto 88/2026, de 11 de febrero",
        "https://www.boe.es/eli/es/rd/2026/02/11/88", date(2026, 2, 11),
    )
    consumer = _source(
        db, "TRLGDCU", "BOE",
        "Real Decreto Legislativo 1/2007 - texto refundido de la Ley General para la Defensa de los Consumidores y Usuarios",
        "https://www.boe.es/buscar/act.php?id=BOE-A-2007-20555", date(2007, 11, 16),
    )
    civil = _source(
        db, "CODIGO_CIVIL", "BOE", "Código Civil",
        "https://www.boe.es/buscar/act.php?id=BOE-A-1889-4763", date(1889, 7, 25),
    )
    rules = {
        "E04-B": _rule(
            db, "ELEC_ADDON_END_WITH_SUPPLY", date(2026, 2, 12), rd88.id, "32.4",
            "Los servicios adicionales contratados junto con el suministro se extinguen con éste salvo indicación expresa del consumidor.",
            {"contracted_with_supply": True, "supply_ended": True, "express_keep_request": False},
            {"additional_service_should_end_with_supply": True},
        ),
        "E04-A": _rule(
            db, "CONSUMER_UNREQUESTED_SERVICE", date(2014, 3, 29), consumer.id, "66 quáter; 60 bis",
            "Los servicios no solicitados no pueden generar pretensión de pago y los pagos adicionales requieren consentimiento expreso.",
        ),
        "E02-A": _rule(
            db, "ELEC_OVERBILL_REFUND", date(2026, 6, 12), rd88.id, "45.2",
            "La sobrefacturación soportada por este ruleset se analiza con la regla sectorial vigente desde el 12/06/2026.",
        ),
        "E02-B": _rule(
            db, "PAYMENT_UNDUE_RESTITUTION", date(1889, 8, 16), civil.id, "1895",
            "El cobro indebido de una cantidad no debida genera obligación de restitución cuando se cumplen los presupuestos legales.",
        ),
        "C01": _rule(
            db, "GOODS_CONFORMITY_CURRENT", date(2022, 1, 1), consumer.id, "117-121",
            "Para bienes de consumo, el régimen vigente desde 01/01/2022 regula puesta en conformidad, remedios, plazo de tres años y presunción de dos años.",
        ),
    }
    return rules


def _ensure_review(db: Session, case: Case, reason: str, priority: str = "NORMAL") -> HumanReview:
    existing = db.scalars(
        select(HumanReview).where(
            HumanReview.case_id == case.id,
            HumanReview.reason == reason,
            HumanReview.status == "OPEN",
        )
    ).first()
    if existing:
        return existing
    review = HumanReview(case_id=case.id, reason=reason, priority=priority, status="OPEN")
    db.add(review)
    db.flush()
    audit(db, case.id, "HUMAN_REVIEW_QUEUED", {"review_id": review.id, "reason": reason, "priority": priority})
    return review


def diagnose(db: Session, case: Case):
    evaluator = EVALUATORS.get(case.family or "")
    if not evaluator:
        raise ValueError("Esta familia todavía no está automatizada en la alpha")
    rules = seed_legal(db)
    rule = rules[case.family]
    facts = latest_facts(db, case.id)
    result = evaluator(facts)
    snap = {k: {"value": v.value, "state": v.state, "user_confirmed": v.user_confirmed} for k, v in facts.items()}
    db.add(RuleEvaluation(
        case_id=case.id,
        rule_version_id=rule.id,
        facts_snapshot=snap,
        result=result.rule_result,
        missing_conditions=result.missing_facts,
        failed_conditions=result.failed_conditions,
        engine_version=f"{case.family.lower()}-1",
    ))
    for ca in result.counterarguments:
        db.add(Counterargument(
            case_id=case.id,
            type=ca["type"],
            origin=ca.get("origin", "known_rule"),
            description=ca["type"].replace("_", " ").title(),
            status=ca.get("status", "open"),
            impact=str(ca.get("impact", "material")),
        ))
    if result.calculation is not None:
        db.add(Calculation(
            case_id=case.id,
            type=result.calculation.get("type", "calculation"),
            inputs_json=result.calculation,
            formula_version=f"{case.family}-CALC-1",
            result=float(result.claimable_amount or 0.0),
            explanation="Cálculo determinista reproducible a partir de hechos confirmados del expediente.",
        ))
    economic_value = getattr(result, "economic_value", None)
    if economic_value is None:
        economic_value = result.claimable_amount
    remedies = getattr(result, "remedies", [])
    burden = getattr(result, "burden_of_proof", [])
    dec = Decision(
        case_id=case.id,
        viability=result.viability,
        scope_status=result.scope_status,
        claimable_amount=result.claimable_amount,
        economic_value=economic_value,
        worth_pursuing=result.worth_pursuing,
        professional_review_required=result.viability == "PROFESSIONAL_REVIEW",
        reasoning_summary=result.reasoning_summary,
        counterarguments_snapshot=result.counterarguments,
        rule_evaluations_json=[{
            "rule_id": rule.rule_id, "version": rule.version, "result": result.rule_result,
            "remedies": remedies, "burden_of_proof": burden,
        }],
    )
    db.add(dec)
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
    case.current_decision_id = dec.id
    case.current_action_id = action.id
    if result.missing_facts:
        case.status = "NEEDS_INFORMATION"
    elif result.scope_status in {"LEGACY_REVIEW", "LIMITED_SCOPE"} or result.viability == "PROFESSIONAL_REVIEW":
        case.status = "HUMAN_REVIEW"
        _ensure_review(db, case, result.scope_status or result.viability, "HIGH")
    elif result.viability == "RECLASSIFY":
        case.status = "REANALYZING"
    else:
        case.status = "DIAGNOSED"
    audit(db, case.id, "DIAGNOSIS_GENERATED", {
        "decision_id": dec.id, "family": case.family, "viability": result.viability,
        "scope_status": result.scope_status,
    })
    db.commit()
    return result, dec, action


def save_upload(db: Session, case: Case, filename: str, content_type: str, data: bytes):
    storage = Path(settings.storage_dir) / case.id
    storage.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)[:180]
    path = storage / f"{digest[:12]}_{safe_name}"
    path.write_bytes(data)
    doc = Document(
        case_id=case.id, storage_key=str(path), original_filename=filename,
        mime_type=content_type, sha256=digest,
    )
    db.add(doc)
    db.flush()
    db.add(Evidence(case_id=case.id, document_id=doc.id, source_type="document", strength="medium"))
    raw = ""
    pages = None
    flags: list[str] = []
    try:
        if content_type == "application/pdf" or filename.lower().endswith(".pdf"):
            reader = PdfReader(str(path))
            pages = len(reader.pages)
            raw = "\n".join((p.extract_text() or "") for p in reader.pages)
        elif content_type.startswith("text/") or filename.lower().endswith((".txt", ".csv")):
            raw = data.decode("utf-8", errors="replace")
        else:
            flags.append("NO_TEXT_EXTRACTOR_FOR_MIME")
        doc.processing_status = "PROCESSED" if raw else "NEEDS_REVIEW"
        doc.page_count = pages
    except Exception as exc:
        doc.processing_status = "FAILED"
        flags.append(type(exc).__name__)
    extracted: dict[str, Any] = {}
    if raw:
        money = re.findall(r"(\d{1,5}[.,]\d{2})\s*(?:€|EUR)", raw, flags=re.I)
        if money:
            extracted["possible_amounts"] = [float(x.replace(",", ".")) for x in money[:20]]
        maintenance = re.search(r"(?:mantenimiento|protecci[oó]n|servicio)[^\n€]{0,80}?(\d{1,3}[.,]\d{2})\s*(?:€|EUR)", raw, re.I)
        if maintenance:
            extracted["possible_addon_price"] = float(maintenance.group(1).replace(",", "."))
    ext = DocumentExtraction(
        document_id=doc.id,
        extractor_version="local-text-2",
        raw_text=raw[:200000] if raw else None,
        structured_json=extracted,
        quality_flags=flags,
        completed_at=datetime.now(timezone.utc),
    )
    db.add(ext)
    audit(db, case.id, "DOCUMENT_UPLOADED", {"document_id": doc.id, "extracted": extracted})
    db.commit()
    db.refresh(doc)
    return doc, ext


def analyze_company_response(db: Session, case: Case, text: str):
    result = gateway.analyze_response(text)
    db.add(AIRun(case_id=case.id, task="analyze_response", structured_output=result))
    db.add(Communication(
        case_id=case.id, direction="INBOUND", channel="user_paste",
        body=text, received_at=datetime.now(timezone.utc),
    ))
    argument_fact = {
        "INDEPENDENT_ADDON_CONTRACT": "company.asserts_independent_addon_contract",
        "EXPRESS_KEEP_REQUEST": "company.asserts_keep_request",
        "CONSENT_EVIDENCE": "company.asserts_consent",
        "CORRECT_AMOUNT_DISPUTED": "company.asserts_correct_amount",
        "DIFFERENT_DEBTS": "company.asserts_different_debts",
        "MISUSE_OR_ACCIDENTAL_DAMAGE": "company.asserts_misuse",
        "OUTSIDE_LEGAL_GUARANTEE": "company.asserts_outside_guarantee",
        "REFER_TO_MANUFACTURER": "company.redirects_to_manufacturer",
    }
    for argument in result["arguments"]:
        key = argument_fact.get(argument)
        if key:
            upsert_fact(
                db, case, key, True, state="asserted", user_confirmed=False,
                created_by="company", create_provenance=False,
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
        raise ValueError("Diagnostica el caso antes de preparar una actuación")
    if decision.viability not in {"HIGH", "MEDIUM"}:
        raise ValueError("El diagnóstico actual no permite preparar esta actuación automáticamente")
    facts = latest_facts(db, case.id)
    evaluator = EVALUATORS[case.family]
    result = evaluator(facts)
    amount = round(float(decision.claimable_amount or 0.0), 2)
    remedies = getattr(result, "remedies", [])

    if case.family == "E04-B":
        addon = facts.get("electricity.addon.identity").value if facts.get("electricity.addon.identity") else "servicio adicional"
        end_date = facts.get("electricity.supply_end_date").value if facts.get("electricity.supply_end_date") else None
        text = (
            f"Solicito la cancelación definitiva del servicio adicional {addon}, el cese de nuevos cargos y la devolución de {amount:.2f} €. "
            f"El suministro anterior finalizó el {end_date}. La solicitud se apoya en el artículo 32.4 del Real Decreto 88/2026, "
            "según los hechos actualmente confirmados en el expediente."
        )
        claim_type = "REFUND_POST_TERMINATION_CHARGES"
    elif case.family == "E04-A":
        addon = facts.get("electricity.addon.identity").value if facts.get("electricity.addon.identity") else "servicio adicional"
        text = (
            f"Solicito el cese del servicio {addon} y la devolución de {amount:.2f} € cobrados por un servicio que no consta solicitado. "
            "La reclamación se apoya en los artículos 66 quáter y 60 bis del TRLGDCU, sin perjuicio de la prueba de consentimiento que pueda aportar la empresa."
        )
        claim_type = "UNREQUESTED_SERVICE_REFUND"
    elif case.family == "E02-A":
        text = (
            f"Solicito la corrección de la facturación y la devolución de {amount:.2f} € identificados como importe facturado por encima del debido, "
            "con base en el artículo 45.2 del Real Decreto 88/2026 dentro de su ámbito temporal de aplicación."
        )
        claim_type = "ELECTRICITY_OVERBILL_REFUND"
    elif case.family == "E02-B":
        text = (
            f"Solicito la restitución de {amount:.2f} € correspondientes al segundo pago acreditado de la misma deuda. "
            "El expediente lo trata como cobro indebido conforme al artículo 1895 del Código Civil, sin confundirlo con una sobrefacturación sectorial."
        )
        claim_type = "DUPLICATE_PAYMENT_RESTITUTION"
    elif case.family == "C01":
        product = facts.get("purchase.product_name").value if facts.get("purchase.product_name") else "producto"
        value = decision.economic_value
        text = (
            f"Solicito la puesta en conformidad del {product} sin coste, mediante reparación o sustitución según proceda legalmente. "
            "La falta de conformidad se analiza bajo los artículos 117 a 121 del TRLGDCU. "
            "Este expediente no convierte automáticamente el valor del producto en una devolución en efectivo: los remedios dependen de la fase y de los hechos acreditados."
        )
        claim_type = "GOODS_CONFORMITY"
        amount = 0.0
    else:
        raise ValueError("Familia no soportada para actuación automática")

    payload = {
        "claim_type": claim_type,
        "family": case.family,
        "amount": amount,
        "economic_value": decision.economic_value,
        "currency": "EUR",
        "remedies": remedies,
        "sources": result.sources,
        "text": text,
    }
    action = Action(case_id=case.id, type="SUBMIT_INITIAL_CLAIM", status="READY", payload_json=payload)
    db.add(action)
    db.flush()
    case.current_action_id = action.id
    case.status = "READY_TO_SUBMIT"
    audit(db, case.id, "CLAIM_PACKAGE_PREPARED", {"action_id": action.id, "family": case.family, "amount": amount})
    db.commit()
    db.refresh(action)
    return {"action_id": action.id, **payload}
