"""Synthetic-only RB-022 fixtures. Never imported by application code."""

from datetime import timedelta

from app.auth_models import RealBetaRelease, ReleaseApproval, ReleaseAuthority
from app.real_beta_gate import scope_fingerprint, utcnow


def eligible_test_release(db, users, families=("E02-A", "C01")):
    owner = ReleaseAuthority(authority_type="OWNER_APPROVER")
    professional = ReleaseAuthority(authority_type="PROFESSIONAL_APPROVER")
    now = utcnow()
    limits = (10, 10, 1, 2, 14) if set(families) == {"E02-A", "C01"} else (5, 5, 1, 1, 7)
    release = RealBetaRelease(
        version=1, status="OPEN", families_json=list(families),
        cohort_user_ids_json=[user.id for user in users],
        max_users=limits[0], max_cases_total=limits[1],
        max_active_cases_per_user=limits[2], max_daily_admissions=limits[3],
        max_duration_days=limits[4], starts_at=now - timedelta(minutes=1),
        ends_at=now + timedelta(days=1), scope_fingerprint="0" * 64,
    )
    db.add_all((owner, professional, release))
    db.flush()
    release.scope_fingerprint = scope_fingerprint(release)
    db.add_all((
        ReleaseApproval(release_id=release.id, release_version=release.version,
                        scope_fingerprint=release.scope_fingerprint,
                        authority_id=owner.id, authority_type=owner.authority_type),
        ReleaseApproval(release_id=release.id, release_version=release.version,
                        scope_fingerprint=release.scope_fingerprint,
                        authority_id=professional.id, authority_type=professional.authority_type),
    ))
    db.commit()
    return release, owner, professional
