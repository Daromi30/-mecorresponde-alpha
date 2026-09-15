from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.main import persistence_health
from app.models import Case, Decision, Evidence, Fact
from app.services_v2 import create_case, diagnose, seed_legal, upsert_fact


def test_case_survives_new_postgres_session():
    # Disposable CI database: exercise the same SQLAlchemy models against PostgreSQL.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        seed_legal(db)
        db.commit()
        case = create_case(db, "Me cambié de compañía de luz y me siguen cobrando un mantenimiento")
        case_id = case.id
        upsert_fact(db, case, "electricity.supply_end_date", "2026-06-03", state="confirmed", user_confirmed=True)
        upsert_fact(db, case, "electricity.addon.identity", "Protección Hogar", state="confirmed", user_confirmed=True)
        upsert_fact(db, case, "electricity.addon.ever_contracted", True, state="confirmed", user_confirmed=True)
        upsert_fact(db, case, "electricity.addon.contracted_with_supply", True, state="confirmed", user_confirmed=True)
        upsert_fact(db, case, "electricity.addon.keep_requested", False, state="confirmed", user_confirmed=True)
        upsert_fact(
            db,
            case,
            "electricity.addon.charges",
            [
                {
                    "amount": 8.99,
                    "service_period_start": "2026-06-04",
                    "service_period_end": "2026-07-03",
                    "evidence_verified": True,
                }
            ],
            state="confirmed",
            user_confirmed=True,
        )
        result, decision, _ = diagnose(db, case)
        assert result.viability == "HIGH"
        assert result.claimable_amount == 8.99
        decision_id = decision.id

    # A fresh database session must recover the expediente and its audit-bearing records.
    with SessionLocal() as db:
        recovered = db.get(Case, case_id)
        assert recovered is not None
        assert recovered.status == "DIAGNOSED"
        assert recovered.current_decision_id == decision_id

        facts = db.scalars(select(Fact).where(Fact.case_id == case_id)).all()
        evidence = db.scalars(select(Evidence).where(Evidence.case_id == case_id)).all()
        decisions = db.scalars(select(Decision).where(Decision.case_id == case_id)).all()

        assert len(facts) >= 6
        assert len(evidence) >= 6
        assert len(decisions) >= 1
        assert decisions[-1].claimable_amount == 8.99

    gate = persistence_health()
    assert gate == {"status": "ok", "database": "postgresql", "persistent": True}
