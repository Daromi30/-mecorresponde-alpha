from sqlalchemy import func, select

from app import services_v2 as svc
from app.models import Case
from app.reviews import HumanReview


def test_reusing_open_review_restores_human_review_phase_without_duplicate(db):
    case = Case(
        status="INTAKE",
        vertical="electricity",
        family="E04-B",
        title="Review deduplication phase sync",
    )
    db.add(case)
    db.commit()
    db.refresh(case)

    first = svc.create_human_review(
        db,
        case,
        reason="MATERIAL_FACT_REVIEW",
        priority="HIGH",
        context={"source": "first"},
    )
    db.commit()
    db.refresh(first)
    assert case.status == "HUMAN_REVIEW"

    case.status = "REANALYZING"
    db.commit()

    reused = svc.create_human_review(
        db,
        case,
        reason="MATERIAL_FACT_REVIEW",
        priority="HIGH",
        context={"source": "second"},
    )
    db.commit()

    db.expire_all()
    refreshed = db.get(Case, case.id)
    assert refreshed is not None
    assert refreshed.status == "HUMAN_REVIEW"
    assert reused.id == first.id
    assert db.scalar(
        select(func.count())
        .select_from(HumanReview)
        .where(
            HumanReview.case_id == case.id,
            HumanReview.reason == "MATERIAL_FACT_REVIEW",
            HumanReview.status == "OPEN",
        )
    ) == 1
