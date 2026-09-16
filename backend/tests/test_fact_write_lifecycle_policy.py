from sqlalchemy import select

from app import services_v2 as svc
from app.models import Action, AuditEvent, Case, Document, Evidence, Fact


def test_company_fact_preserves_advanced_case_phase_and_provenance(db):
    case = Case(
        status="WAITING_RESPONSE",
        vertical="electricity",
        family="E04-B",
        title="Company fact lifecycle",
        current_decision_id="decision-remains-current",
    )
    db.add(case)
    db.flush()
    waiting = Action(case_id=case.id, type="WAIT_FOR_RESPONSE", status="OPEN", payload_json={})
    db.add(waiting)
    db.flush()
    case.current_action_id = waiting.id
    db.commit()
    db.refresh(case)

    fact = svc.upsert_fact(
        db,
        case,
        "company.asserts_independent_addon_contract",
        True,
        state="asserted",
        user_confirmed=False,
        created_by="company",
    )

    db.expire_all()
    refreshed = db.get(Case, case.id)
    assert refreshed is not None
    assert refreshed.status == "WAITING_RESPONSE"
    assert refreshed.current_action_id == waiting.id
    assert refreshed.current_decision_id == "decision-remains-current"
    assert db.get(Action, waiting.id).status == "OPEN"

    stored = db.get(Fact, fact.id)
    assert stored is not None
    assert stored.created_by == "company"
    assert stored.user_confirmed is False
    evidence = db.scalar(
        select(Evidence).where(Evidence.case_id == case.id, Evidence.fact_id == fact.id)
    )
    assert evidence is not None
    assert evidence.source_type == "company"
    assert evidence.strength == "medium"

    audit = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.case_id == case.id,
            AuditEvent.event_type == "FACT_RECORDED",
        )
        .order_by(AuditEvent.created_at.desc())
    ).first()
    assert audit is not None
    assert (audit.payload_json or {}).get("source") == "company"


def test_user_fact_reopens_intake_and_supersedes_stale_analysis(db):
    case = Case(
        status="READY_TO_SUBMIT",
        vertical="electricity",
        family="E04-B",
        title="User fact lifecycle",
        current_decision_id="stale-decision-id",
    )
    db.add(case)
    db.flush()
    prepared = Action(
        case_id=case.id,
        type="SUBMIT_INITIAL_CLAIM",
        status="READY",
        payload_json={"text": "stale prepared claim"},
    )
    db.add(prepared)
    db.flush()
    case.current_action_id = prepared.id
    db.commit()
    db.refresh(case)

    svc.upsert_fact(
        db,
        case,
        "electricity.addon.keep_requested",
        False,
        state="confirmed",
        user_confirmed=True,
        created_by="user",
    )

    db.expire_all()
    refreshed = db.get(Case, case.id)
    assert refreshed is not None
    assert refreshed.status == "INTAKE"
    assert refreshed.current_action_id is None
    assert refreshed.current_decision_id is None

    stale_action = db.get(Action, prepared.id)
    assert stale_action is not None
    assert stale_action.status == "SUPERSEDED"
    assert stale_action.completed_at is not None

    audit = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.case_id == case.id,
            AuditEvent.event_type == "CURRENT_ANALYSIS_SUPERSEDED",
        )
        .order_by(AuditEvent.created_at.desc())
    ).first()
    assert audit is not None
    payload = audit.payload_json or {}
    assert payload.get("fact_key") == "electricity.addon.keep_requested"
    assert payload.get("source") == "user"
    assert payload.get("previous_action_id") == prepared.id
    assert payload.get("previous_decision_id") == "stale-decision-id"


def test_document_fact_reopens_intake_and_supersedes_prepared_claim(db):
    case = Case(
        status="READY_TO_SUBMIT",
        vertical="electricity",
        family="E04-B",
        title="Document fact lifecycle",
        current_decision_id="document-stale-decision",
    )
    db.add(case)
    db.flush()
    document = Document(
        case_id=case.id,
        storage_key="synthetic/test.pdf",
        original_filename="test.pdf",
        mime_type="application/pdf",
        sha256="a" * 64,
        contains_sensitive_data=False,
    )
    prepared = Action(
        case_id=case.id,
        type="SUBMIT_INITIAL_CLAIM",
        status="READY",
        payload_json={"text": "claim prepared before document confirmation"},
    )
    db.add_all([document, prepared])
    db.flush()
    case.current_action_id = prepared.id
    db.commit()
    db.refresh(case)

    fact = svc.confirm_document_fact(
        db,
        case,
        document,
        key="electricity.addon.keep_requested",
        value=False,
        locator="page 1",
        excerpt="No solicita mantener el servicio adicional",
    )

    db.expire_all()
    refreshed = db.get(Case, case.id)
    assert refreshed is not None
    assert refreshed.status == "INTAKE"
    assert refreshed.current_action_id is None
    assert refreshed.current_decision_id is None

    stale_action = db.get(Action, prepared.id)
    assert stale_action is not None
    assert stale_action.status == "SUPERSEDED"
    assert stale_action.completed_at is not None

    evidence = db.scalar(
        select(Evidence).where(
            Evidence.case_id == case.id,
            Evidence.fact_id == fact.id,
            Evidence.document_id == document.id,
        )
    )
    assert evidence is not None
    assert evidence.source_type == "document"
    assert evidence.strength == "strong"

    audit = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.case_id == case.id,
            AuditEvent.event_type == "CURRENT_ANALYSIS_SUPERSEDED",
        )
        .order_by(AuditEvent.created_at.desc())
    ).first()
    assert audit is not None
    payload = audit.payload_json or {}
    assert payload.get("fact_key") == "electricity.addon.keep_requested"
    assert payload.get("source") == "document"
    assert payload.get("previous_action_id") == prepared.id
    assert payload.get("previous_decision_id") == "document-stale-decision"
