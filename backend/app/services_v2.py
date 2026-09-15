from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .engine.common import FactValue
from .engine.e02 import evaluate_e02a, evaluate_e02b
from .engine.e04a import evaluate_e04a
from .engine.e04b import evaluate_e04b
from .engine.gateway import DeterministicAlphaGateway
from .engine.questions import next_question
from .models import (
    AIRun, Action, AuditEvent, Calculation, Case, Communication, Counterargument,
    Decision, Document, DocumentExtraction, Evidence, Fact, LegalRuleVersion,
    LegalSource, RuleEvaluation,
)
from .reviews import HumanReview

gateway = DeterministicAlphaGateway()


def audit(db: Session, case_id: str | None, event_type: str, payload: dict[str, Any] | None = None):
    db.add(AuditEvent(case_id=case_id, event_type=event_type, payload_json=payload or {}))


def create_human_review(db: Session, case: Case, reason: str, priority: str = "NORMAL", context: dict[str, Any] | None = None) -> HumanReview:
    existing = db.scalars(select(HumanReview).where(HumanReview.case_id == case.id, HumanReview.reason == reason, HumanReview.status == "OPEN")).first()
    if existing:
        return existing
    review = HumanReview(case_id=case.id, reason=reason, priority=priority, context_json=context or {})
    db.add(review)
    case.status = "HUMAN_REVIEW"
    audit(db, case.id, "HUMAN_REVIEW_TRIGGERED", {"reason": reason, "priority": priority})
    return review


def create_case(db: Session, message: str) -> Case:
    classification = gateway.classify(message)
    titles = {
        "E04-B": "Mantenimiento tras cambio de comercializadora",
        "E04-A": "Servicio adicional no contratado",
        "E02-A": "Posible sobrefacturación eléctrica",
        "E02-B": "Posible cobro duplicado",
    }
    case = Case(status="INTAKE", vertical=classification["vertical"], family=classification["family"], title=titles.get(classification["family"], "Caso por clasificar"), raw_intake=message)
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
    rows = db.scalars(select(Fact).where(Fact.case_id == case_id).order_by(Fact.created_at.asc())).all()
    latest: dict[str, Fact] = {}
    for row in rows:
        latest[row.key] = row
    return {k: FactValue(value=v.value_json.get("value"), state=v.state, user_confirmed=v.user_confirmed) for k, v in latest.items()}


def upsert_fact(db: Session, case: Case, key: str, value: Any, state: str = "asserted", materiality: str = "critical", confidence: float | None = None, user_confirmed: bool = True, created_by: str = "user") -> Fact:
    prev = db.scalars(select(Fact).where(Fact.case_id == case.id, Fact.key == key).order_by(Fact.created_at.desc())).first()
    f = Fact(case_id=case.id, key=key, value_json={"value": value}, state=state, materiality=materiality, confidence=confidence, user_confirmed=user_confirmed, created_by=created_by, supersedes_fact_id=prev.id if prev else None)
    db.add(f)
    db.flush()
    if created_by in {"user", "company", "human"}:
        db.add(Evidence(case_id=case.id, fact_id=f.id, source_type=created_by, strength="strong" if user_confirmed or created_by == "human" else "medium"))
    audit(db, case.id, "FACT_RECORDED", {"key": key, "state": state, "supersedes": prev.id if prev else None})
    case.status = "INTAKE"
    db.commit()
    db.refresh(f)
    return f


def get_next_question(db: Session, case: Case) -> dict[str, Any]:
    return next_question(latest_facts(db, case.id), case.family)


def _ensure_source(db: Session, source_id: str, authority: str, title: str, official_url: str, publication_date: date | None) -> LegalSource:
    src = db.get(LegalSource, source_id)
    if not src:
        src = LegalSource(id=source_id, authority=authority, title=title, official_url=official_url, publication_date=publication_date, jurisdiction="ES", status="active")
        db.add(src)
        db.flush()
    return src


def _ensure_rule(db: Session, rule_id: str, version: int, valid_from: date, source_id: str, article: str, conditions: dict[str, Any], consequence: dict[str, Any], interpretation: str) -> LegalRuleVersion:
    rule = db.scalars(select(LegalRuleVersion).where(LegalRuleVersion.rule_id == rule_id, LegalRuleVersion.version == version)).first()
    if not rule:
        rule = LegalRuleVersion(rule_id=rule_id, version=version, valid_from=valid_from, source_id=source_id, article=article, conditions_json=conditions, consequence_json=consequence, interpretation=interpretation)
        db.add(rule)
        db.flush()
    return rule


def seed_legal(db: Session) -> dict[str, LegalRuleVersion]:
    _ensure_source(db, "RD88_2026", "BOE / Ministerio para la Transición Ecológica", "Real Decreto 88/2026, de 11 de febrero", "https://www.boe.es/eli/es/rd/2026/02/11/88", date(2026, 2, 11))
    _ensure_source(db, "TRLGDCU", "BOE", "Real Decreto Legislativo 1/2007, texto refundido de la Ley General para la Defensa de los Consumidores y Usuarios", "https://www.boe.es/buscar/act.php?id=BOE-A-2007-20555", date(2007, 11, 16))
    _ensure_source(db, "CODIGO_CIVIL", "BOE", "Código Civil", "https://www.boe.es/buscar/act.php?id=BOE-A-1889-4763", date(1889, 7, 24))
    return {
        "ELEC_ADDON_END_WITH_SUPPLY": _ensure_rule(db, "ELEC_ADDON_END_WITH_SUPPLY", 1, date(2026, 2, 12), "RD88_2026", "32.4", {"contracted_with_supply": True, "supply_ended": True, "express_keep_request": False}, {"additional_service_should_end_with_supply": True}, "Los servicios adicionales contratados junto con el suministro se extinguen con éste salvo indicación expresa del consumidor."),
        "UNSOLICITED_SERVICE_NO_PAYMENT": _ensure_rule(db, "UNSOLICITED_SERVICE_NO_PAYMENT", 1, date(2014, 3, 29), "TRLGDCU", "66 quáter", {"service_not_requested": True, "payment_claimed": True}, {"consumer_not_obliged_to_pay": True}, "No puede exigirse pago por servicios no solicitados; la falta de respuesta no equivale a consentimiento."),
        "ADDITIONAL_PAYMENT_EXPRESS_CONSENT": _ensure_rule(db, "ADDITIONAL_PAYMENT_EXPRESS_CONSENT", 1, date(2014, 3, 29), "TRLGDCU", "60 bis", {"additional_payment": True}, {"express_consent_required": True, "burden_on_business": True}, "Los pagos adicionales requieren consentimiento expreso y el empresario debe probar su obtención."),
        "ELEC_OVERBILL_REFUND": _ensure_rule(db, "ELEC_OVERBILL_REFUND", 1, date(2026, 6, 12), "RD88_2026", "45.2", {"billed_above_due": True}, {"refund_in_next_bill": True, "interest": "legal_interest_plus_150bp"}, "Las cantidades facturadas por encima de las debidas deben devolverse en la primera facturación siguiente, con los intereses previstos en el artículo."),
        "UNDUE_PAYMENT_RESTITUTION": _ensure_rule(db, "UNDUE_PAYMENT_RESTITUTION", 1, date(1889, 7, 25), "CODIGO_CIVIL", "1895", {"payment_not_due": True, "delivered_by_error": True}, {"restitution_required": True}, "El cobro de lo que no había derecho a cobrar y fue entregado por error genera obligación de restitución."),
    }


EVALUATORS = {"E04-B": evaluate_e04b, "E04-A": evaluate_e04a, "E02-A": evaluate_e02a, "E02-B": evaluate_e02b}
FAMILY_RULES = {
    "E04-B": ["ELEC_ADDON_END_WITH_SUPPLY"],
    "E04-A": ["UNSOLICITED_SERVICE_NO_PAYMENT", "ADDITIONAL_PAYMENT_EXPRESS_CONSENT"],
    "E02-A": ["ELEC_OVERBILL_REFUND"],
    "E02-B": ["UNDUE_PAYMENT_RESTITUTION"],
}


def diagnose(db: Session, case: Case):
    evaluator = EVALUATORS.get(case.family or "")
    if not evaluator:
        raise ValueError("This case family is not automated in the current alpha")
    rules = seed_legal(db)
    facts = latest_facts(db, case.id)
    result = evaluator(facts)
    snap = {k: {"value": v.value, "state": v.state, "user_confirmed": v.user_confirmed} for k, v in facts.items()}
    evaluated_rules = []
    for rule_id in FAMILY_RULES.get(case.family or "", []):
        rule = rules[rule_id]
        db.add(RuleEvaluation(case_id=case.id, rule_version_id=rule.id, facts_snapshot=snap, result=result.rule_result, missing_conditions=result.missing_facts, failed_conditions=result.failed_conditions, engine_version=f"{(case.family or 'unknown').lower()}-1"))
        evaluated_rules.append({"rule_id": rule.rule_id, "version": rule.version, "result": result.rule_result})
    for ca in result.counterarguments:
        db.add(Counterargument(case_id=case.id, type=ca["type"], origin=ca.get("origin", "known_rule"), description=ca["type"].replace("_", " ").title(), status=ca["status"], impact=ca["impact"]))
    if result.calculation is not None:
        db.add(Calculation(case_id=case.id, type=result.calculation.get("type", "case_calculation"), inputs_json=result.calculation, formula_version=f"{case.family}-CALC-1", result=float(result.claimable_amount or 0.0), explanation="Cálculo determinista reproducible a partir de los hechos confirmados del expediente."))
    dec = Decision(case_id=case.id, viability=result.viability, scope_status=result.scope_status, claimable_amount=result.claimable_amount, economic_value=result.claimable_amount, worth_pursuing=result.worth_pursuing, professional_review_required=result.viability == "PROFESSIONAL_REVIEW", reasoning_summary=result.reasoning_summary, counterarguments_snapshot=result.counterarguments, rule_evaluations_json=evaluated_rules)
    db.add(dec)
    db.flush()
    action = Action(case_id=case.id, type=result.next_action, payload_json={"claimable_amount": result.claimable_amount})
    db.add(action)
    db.flush()
    case.current_decision_id = dec.id
    case.current_action_id = action.id
    case.status = "DIAGNOSED" if not result.missing_facts else "NEEDS_INFORMATION"
    if result.viability == "PROFESSIONAL_REVIEW" or result.next_action.startswith("HUMAN_REVIEW"):
        create_human_review(db, case, result.next_action, "HIGH", {"family": case.family})
    audit(db, case.id, "DIAGNOSIS_GENERATED", {"decision_id": dec.id, "viability": result.viability, "family": case.family})
    db.commit()
    return result, dec, action


def save_upload(db: Session, case: Case, filename: str, content_type: str, data: bytes):
    storage = Path(settings.storage_dir) / case.id
    storage.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)[:180]
    path = storage / f"{digest[:12]}_{safe_name}"
    path.write_bytes(data)
    doc = Document(case_id=case.id, storage_key=str(path), original_filename=filename, mime_type=content_type, sha256=digest)
    db.add(doc)
    db.flush()
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
        match = re.search(r"(?:mantenimiento|protecci[oó]n|servicio)[^\n€]{0,80}?(\d{1,3}[.,]\d{2})\s*€", raw, re.I)
        if match:
            price = float(match.group(1).replace(",", "."))
            extracted["possible_addon_price"] = price
            candidate = Fact(case_id=case.id, key="electricity.addon.detected_price", value_json={"value": price}, state="inferred", materiality="context", confidence=0.65, user_confirmed=False, created_by="system")
            db.add(candidate)
            db.flush()
            db.add(Evidence(case_id=case.id, fact_id=candidate.id, document_id=doc.id, source_type="document", excerpt=match.group(0)[:500], strength="medium"))
    ext = DocumentExtraction(document_id=doc.id, extractor_version="local-text-2", raw_text=raw[:200000] if raw else None, structured_json=extracted, quality_flags=flags, completed_at=datetime.now(timezone.utc))
    db.add(ext)
    audit(db, case.id, "DOCUMENT_UPLOADED", {"document_id": doc.id, "extracted": extracted})
    db.commit()
    db.refresh(doc)
    return doc, ext


def confirm_document_fact(db: Session, case: Case, document: Document, *, key: str, value: Any, locator: str | None = None, excerpt: str | None = None, materiality: str = "critical") -> Fact:
    prev = db.scalars(select(Fact).where(Fact.case_id == case.id, Fact.key == key).order_by(Fact.created_at.desc())).first()
    fact = Fact(case_id=case.id, key=key, value_json={"value": value}, state="confirmed", materiality=materiality, confidence=1.0, user_confirmed=True, created_by="user", supersedes_fact_id=prev.id if prev else None)
    db.add(fact)
    db.flush()
    db.add(Evidence(case_id=case.id, fact_id=fact.id, document_id=document.id, source_type="document", locator=locator, excerpt=excerpt, strength="strong"))
    audit(db, case.id, "DOCUMENT_FACT_CONFIRMED", {"document_id": document.id, "fact_id": fact.id, "key": key})
    db.commit()
    db.refresh(fact)
    return fact


def analyze_company_response(db: Session, case: Case, text: str):
    result = gateway.analyze_response(text)
    db.add(AIRun(case_id=case.id, task="analyze_response", structured_output=result))
    db.add(Communication(case_id=case.id, direction="INBOUND", channel="user_paste", body=text, received_at=datetime.now(timezone.utc)))
    argument_fact_map = {
        "INDEPENDENT_ADDON_CONTRACT": "company.asserts_independent_addon_contract",
        "EXPRESS_KEEP_REQUEST": "company.asserts_keep_request",
        "CONSENT_EVIDENCE": "company.asserts_consent",
        "CORRECT_AMOUNT_DISPUTED": "company.disputes_correct_amount",
        "DIFFERENT_DEBTS": "company.asserts_different_debts",
    }
    for argument in result["arguments"]:
        key = argument_fact_map.get(argument)
        if key:
            upsert_fact(db, case, key, True, state="asserted", user_confirmed=False, created_by="company")
    case.status = "RESPONSE_RECEIVED"
    audit(db, case.id, "RESPONSE_ANALYZED", result)
    db.commit()
    return result


def prepare_claim_package(db: Session, case: Case) -> dict[str, Any]:
    decision = db.scalars(select(Decision).where(Decision.case_id == case.id).order_by(Decision.created_at.desc())).first()
    if not decision:
        raise ValueError("Diagnose the case before preparing a claim")
    if decision.viability not in {"HIGH", "MEDIUM"} or not decision.claimable_amount or decision.claimable_amount <= 0:
        raise ValueError("Current diagnosis does not support preparing a monetary claim")
    facts = latest_facts(db, case.id)
    amount = round(float(decision.claimable_amount), 2)
    if case.family == "E04-B":
        addon = facts.get("electricity.addon.identity").value if facts.get("electricity.addon.identity") else "servicio adicional"
        end_date = facts.get("electricity.supply_end_date").value if facts.get("electricity.supply_end_date") else None
        remedies = ["CANCEL_ADDON", "REFUND_VERIFIED_POST_TERMINATION_CHARGES", "CEASE_FUTURE_CHARGES", "CONFIRM_CANCELLATION"]
        legal_basis = [{"rule_id":"ELEC_ADDON_END_WITH_SUPPLY", "article":"32.4", "source":"RD 88/2026"}]
        text = f"Solicito la cancelación definitiva del servicio adicional {addon}, el cese de nuevos cargos y la devolución de {amount:.2f} €. El suministro eléctrico con la antigua comercializadora finalizó el {end_date}. La reclamación se apoya en el artículo 32.4 del Real Decreto 88/2026."
    elif case.family == "E04-A":
        addon = facts.get("electricity.addon.identity").value if facts.get("electricity.addon.identity") else "servicio adicional"
        remedies = ["CANCEL_ADDON", "REFUND_UNAUTHORIZED_CHARGES", "CEASE_FUTURE_CHARGES"]
        legal_basis = [{"rule_id":"UNSOLICITED_SERVICE_NO_PAYMENT", "article":"66 quáter", "source":"TRLGDCU"}, {"rule_id":"ADDITIONAL_PAYMENT_EXPRESS_CONSENT", "article":"60 bis", "source":"TRLGDCU"}]
        text = f"Solicito la cancelación del servicio {addon}, el cese de cargos y la devolución de {amount:.2f} €. No reconozco haber solicitado ni consentido expresamente este servicio. Los artículos 66 quáter y 60 bis del TRLGDCU protegen frente a servicios no solicitados y pagos adicionales sin consentimiento expreso."
    elif case.family == "E02-A":
        remedies = ["CORRECT_INVOICE", "REFUND_OVERBILLED_AMOUNT"]
        legal_basis = [{"rule_id":"ELEC_OVERBILL_REFUND", "article":"45.2", "source":"RD 88/2026"}]
        text = f"Solicito la corrección de la facturación y la devolución de {amount:.2f} € facturados por encima de lo debido, conforme al artículo 45.2 del Real Decreto 88/2026."
    elif case.family == "E02-B":
        remedies = ["REFUND_DUPLICATE_PAYMENT"]
        legal_basis = [{"rule_id":"UNDUE_PAYMENT_RESTITUTION", "article":"1895", "source":"Código Civil"}]
        text = f"Solicito la devolución de {amount:.2f} € correspondientes a un segundo pago de la misma deuda, conforme al artículo 1895 del Código Civil sobre cobro de lo indebido."
    else:
        raise ValueError("Claim renderer not implemented for this family")
    payload = {"claim_type": f"{case.family}_INITIAL_CLAIM", "remedies": remedies, "amount": amount, "currency": "EUR", "legal_basis": legal_basis, "text": text}
    action = Action(case_id=case.id, type="SUBMIT_INITIAL_CLAIM", status="READY", payload_json=payload)
    db.add(action)
    db.flush()
    case.current_action_id = action.id
    case.status = "READY_TO_SUBMIT"
    audit(db, case.id, "CLAIM_PACKAGE_PREPARED", {"action_id": action.id, "amount": amount, "family": case.family})
    db.commit()
    db.refresh(action)
    return {"action_id": action.id, **payload}
