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
from .engine.e04b import FactValue, evaluate_e04b
from .engine.gateway import DeterministicAlphaGateway
from .engine.questions import next_question
from .models import (
    Action, AuditEvent, Case, Calculation, Communication, Counterargument, Decision, Document,
    DocumentExtraction, Fact, LegalRuleVersion, LegalSource, RuleEvaluation, AIRun
)

gateway = DeterministicAlphaGateway()


def audit(db: Session, case_id: str | None, event_type: str, payload: dict[str, Any] | None = None):
    db.add(AuditEvent(case_id=case_id, event_type=event_type, payload_json=payload or {}))


def create_case(db: Session, message: str) -> Case:
    classification = gateway.classify(message)
    title = "Mantenimiento tras cambio de comercializadora" if classification["family"] == "E04-B" else "Caso por clasificar"
    case = Case(status="INTAKE", vertical=classification["vertical"], family=classification["family"], title=title, raw_intake=message)
    db.add(case); db.flush()
    db.add(AIRun(case_id=case.id, task="classify", structured_output=classification))
    audit(db, case.id, "CASE_STARTED", {"classification": classification})
    if classification["family"] is None:
        case.status = "CLOSED_UNSUPPORTED"
    db.commit(); db.refresh(case)
    return case


def latest_facts(db: Session, case_id: str) -> dict[str, FactValue]:
    rows = db.scalars(select(Fact).where(Fact.case_id == case_id).order_by(Fact.created_at.asc())).all()
    latest: dict[str, Fact] = {}
    for row in rows:
        latest[row.key] = row
    return {k: FactValue(value=v.value_json.get("value"), state=v.state, user_confirmed=v.user_confirmed) for k, v in latest.items()}


def upsert_fact(db: Session, case: Case, key: str, value: Any, state: str="asserted", materiality: str="critical", confidence: float|None=None, user_confirmed: bool=True, created_by: str="user") -> Fact:
    prev = db.scalars(select(Fact).where(Fact.case_id==case.id, Fact.key==key).order_by(Fact.created_at.desc())).first()
    f = Fact(case_id=case.id, key=key, value_json={"value": value}, state=state, materiality=materiality, confidence=confidence, user_confirmed=user_confirmed, created_by=created_by, supersedes_fact_id=prev.id if prev else None)
    db.add(f)
    audit(db, case.id, "FACT_RECORDED", {"key":key,"state":state,"supersedes":prev.id if prev else None})
    case.status = "INTAKE"
    db.commit(); db.refresh(f)
    return f


def get_next_question(db: Session, case: Case) -> dict[str, Any]:
    return next_question(latest_facts(db, case.id), case.family)


def seed_legal(db: Session) -> LegalRuleVersion:
    src = db.get(LegalSource, "RD88_2026")
    if not src:
        src = LegalSource(id="RD88_2026", authority="BOE / Ministerio para la Transición Ecológica", title="Real Decreto 88/2026, de 11 de febrero", official_url="https://www.boe.es/eli/es/rd/2026/02/11/88", publication_date=date(2026,2,11), jurisdiction="ES", status="active")
        db.add(src); db.flush()
    rule = db.scalars(select(LegalRuleVersion).where(LegalRuleVersion.rule_id=="ELEC_ADDON_END_WITH_SUPPLY", LegalRuleVersion.version==1)).first()
    if not rule:
        rule = LegalRuleVersion(rule_id="ELEC_ADDON_END_WITH_SUPPLY", version=1, valid_from=date(2026,2,12), source_id=src.id, article="32.4", conditions_json={"contracted_with_supply":True,"supply_ended":True,"express_keep_request":False}, consequence_json={"additional_service_should_end_with_supply":True}, interpretation="Los servicios adicionales contratados junto con el suministro se extinguen con éste salvo indicación expresa del consumidor.")
        db.add(rule); db.flush()
    return rule


def diagnose(db: Session, case: Case):
    if case.family != "E04-B":
        raise ValueError("This internal alpha only diagnoses E04-B end-to-end")
    rule = seed_legal(db)
    facts = latest_facts(db, case.id)
    result = evaluate_e04b(facts)
    snap = {k:{"value":v.value,"state":v.state,"user_confirmed":v.user_confirmed} for k,v in facts.items()}
    reval = RuleEvaluation(case_id=case.id, rule_version_id=rule.id, facts_snapshot=snap, result=result.rule_result, missing_conditions=result.missing_facts, failed_conditions=result.failed_conditions)
    db.add(reval); db.flush()
    for ca in result.counterarguments:
        db.add(Counterargument(case_id=case.id, type=ca["type"], description=ca["type"].replace("_"," ").title(), status=ca["status"], impact=ca["impact"]))
    if result.calculation is not None:
        db.add(Calculation(case_id=case.id, type="refund_sum", inputs_json=result.calculation, formula_version="E04B-CALC-1", result=float(result.claimable_amount or 0.0), explanation="Suma de cargos acreditados correspondientes íntegramente a períodos posteriores al fin del suministro."))
    dec = Decision(case_id=case.id, viability=result.viability, scope_status=result.scope_status, claimable_amount=result.claimable_amount, economic_value=result.claimable_amount, worth_pursuing=result.worth_pursuing, professional_review_required=result.viability=="PROFESSIONAL_REVIEW", reasoning_summary=result.reasoning_summary, counterarguments_snapshot=result.counterarguments, rule_evaluations_json=[{"rule_id":rule.rule_id,"version":rule.version,"result":result.rule_result}])
    db.add(dec); db.flush()
    action = Action(case_id=case.id, type=result.next_action, payload_json={"claimable_amount":result.claimable_amount})
    db.add(action); db.flush()
    case.current_decision_id = dec.id; case.current_action_id = action.id
    case.status = "DIAGNOSED" if not result.missing_facts else "NEEDS_INFORMATION"
    audit(db, case.id, "DIAGNOSIS_GENERATED", {"decision_id":dec.id,"viability":result.viability})
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
    db.add(doc); db.flush()
    raw = ""; pages = None; flags=[]
    try:
        if content_type == "application/pdf" or filename.lower().endswith(".pdf"):
            reader = PdfReader(str(path)); pages=len(reader.pages); raw="\n".join((p.extract_text() or "") for p in reader.pages)
        elif content_type.startswith("text/") or filename.lower().endswith((".txt",".csv")):
            raw = data.decode("utf-8", errors="replace")
        else:
            flags.append("NO_TEXT_EXTRACTOR_FOR_MIME")
        doc.processing_status = "PROCESSED" if raw else "NEEDS_REVIEW"
        doc.page_count = pages
    except Exception as exc:
        doc.processing_status = "FAILED"; flags.append(type(exc).__name__)
    extracted = {}
    if raw:
        match = re.search(r"(?:mantenimiento|protecci[oó]n|servicio)[^\n€]{0,80}?(\d{1,3}[.,]\d{2})\s*€", raw, re.I)
        if match:
            extracted["possible_addon_price"] = float(match.group(1).replace(",","."))
    ext = DocumentExtraction(document_id=doc.id, extractor_version="local-text-1", raw_text=raw[:200000] if raw else None, structured_json=extracted, quality_flags=flags, completed_at=datetime.now(timezone.utc))
    db.add(ext)
    audit(db, case.id, "DOCUMENT_UPLOADED", {"document_id":doc.id,"extracted":extracted})
    db.commit(); db.refresh(doc)
    return doc, ext


def analyze_company_response(db: Session, case: Case, text: str):
    result = gateway.analyze_response(text)
    db.add(AIRun(case_id=case.id, task="analyze_response", structured_output=result))
    db.add(Communication(case_id=case.id, direction="INBOUND", channel="user_paste", body=text, received_at=datetime.now(timezone.utc)))
    if "INDEPENDENT_ADDON_CONTRACT" in result["arguments"]:
        upsert_fact(db, case, "company.asserts_independent_addon_contract", True, state="asserted", user_confirmed=False, created_by="company")
    if "EXPRESS_KEEP_REQUEST" in result["arguments"]:
        upsert_fact(db, case, "company.asserts_keep_request", True, state="asserted", user_confirmed=False, created_by="company")
    case.status = "RESPONSE_RECEIVED"
    audit(db, case.id, "RESPONSE_ANALYZED", result)
    db.commit()
    return result


def prepare_claim_package(db: Session, case: Case) -> dict[str, Any]:
    decision = db.scalars(select(Decision).where(Decision.case_id == case.id).order_by(Decision.created_at.desc())).first()
    if not decision:
        raise ValueError("Diagnose the case before preparing a claim")
    if decision.viability not in {"HIGH", "MEDIUM"} or not decision.claimable_amount or decision.claimable_amount <= 0:
        raise ValueError("Current diagnosis does not support preparing an E04-B refund claim")
    facts = latest_facts(db, case.id)
    addon = facts.get("electricity.addon.identity").value if facts.get("electricity.addon.identity") else "servicio adicional"
    end_date = facts.get("electricity.supply_end_date").value if facts.get("electricity.supply_end_date") else None
    amount = round(float(decision.claimable_amount), 2)
    text = ("Solicito la cancelación definitiva del servicio adicional " + str(addon) + ", el cese de nuevos cargos y la devolución de " f"{amount:.2f} €. El suministro eléctrico con la antigua comercializadora finalizó el {end_date}. " "Según los hechos y documentos actualmente incorporados al expediente, el servicio fue contratado junto con el suministro y " "no consta que solicitara expresamente mantenerlo tras su finalización. La reclamación se apoya en el artículo 32.4 del Real Decreto 88/2026. " "Solicito igualmente confirmación escrita de la cancelación y del abono correspondiente.")
    payload = {"claim_type": "REFUND_POST_TERMINATION_CHARGES", "remedies": ["CANCEL_ADDON", "REFUND_VERIFIED_POST_TERMINATION_CHARGES", "CEASE_FUTURE_CHARGES", "CONFIRM_CANCELLATION"], "amount": amount, "currency": "EUR", "legal_basis": [{"rule_id": "ELEC_ADDON_END_WITH_SUPPLY", "article": "32.4", "source": "RD 88/2026"}], "facts": {"supply_end_date": end_date, "addon_identity": addon}, "text": text}
    action = Action(case_id=case.id, type="SUBMIT_INITIAL_CLAIM", status="READY", payload_json=payload)
    db.add(action); db.flush()
    case.current_action_id = action.id
    case.status = "READY_TO_SUBMIT"
    audit(db, case.id, "CLAIM_PACKAGE_PREPARED", {"action_id": action.id, "amount": amount})
    db.commit(); db.refresh(action)
    return {"action_id": action.id, **payload}
