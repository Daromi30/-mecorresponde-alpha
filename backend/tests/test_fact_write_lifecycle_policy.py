from sqlalchemy import select

from app import services_v2 as svc
from app.models import AuditEvent, Case, Evidence, Fact


def test_company_fact_preserves_advanced_case_phase_and_provenance(db):
    case = Case(
        status="WAITING_RESPONSE",
        vertical="electricity",
        family="E04-B",
        title="Company fact lifecycle",
    )
    db.add(case)
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


def test_user_fact_still_reopens_intake_for_reanalysis(db):
    case = Case(
        status="DIAGNOSED",
        vertical="electricity",
        family="E04-B",
        title="User fact lifecycle",
    )
    db.add(case)
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
