from __future__ import annotations

from sqlalchemy.orm import Session

from .routers import cases_v2


_INSTALLED = False


def install_atomic_case_creation_policy() -> None:
    """Keep case creation and anonymous access issuance in one database transaction.

    The historical service layer commits while building a case (and may commit again while
    creating the assisted-classification fallback). The HTTP route then creates CaseAccess and
    commits again. If that final commit failed, the database could retain a case that the
    claimant never received a usable capability for.

    `cases_v2.create` already owns the correct outer commit after it adds CaseAccess and the
    CASE_ACCESS_ISSUED audit. This wrapper therefore turns only the commits performed inside
    `create_case` into flushes for the duration of that call. The route's final commit remains
    the single real commit. No evaluator, classifier, title, fallback review, token format or
    access rule is duplicated here.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    previous_create_case = cases_v2.create_case

    def create_case_without_internal_commits(db: Session, message: str):
        real_commit = db.commit

        def flush_instead_of_commit() -> None:
            db.flush()

        db.commit = flush_instead_of_commit  # type: ignore[method-assign]
        try:
            return previous_create_case(db, message)
        except Exception:
            db.rollback()
            raise
        finally:
            db.commit = real_commit  # type: ignore[method-assign]

    cases_v2.create_case = create_case_without_internal_commits
    _INSTALLED = True
