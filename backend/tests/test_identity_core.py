from sqlalchemy import select

from app.db import SessionLocal
from app.identity import ExternalIdentity, UserAccount


def test_account_core_stores_provider_subject_not_passwords(client):
    # Starting the TestClient applies the same migrations used by production.
    with SessionLocal() as db:
        user = UserAccount(email="persona@example.test", email_verified=True)
        db.add(user)
        db.flush()
        identity = ExternalIdentity(
            user_id=user.id,
            provider="oidc-test",
            subject="provider-subject-123",
            email_snapshot=user.email,
        )
        db.add(identity)
        db.commit()

        stored = db.scalar(select(ExternalIdentity).where(ExternalIdentity.subject == "provider-subject-123"))
        assert stored is not None
        assert stored.user_id == user.id
        assert stored.provider == "oidc-test"

    assert not hasattr(UserAccount, "password")
    assert not hasattr(UserAccount, "password_hash")
    assert not hasattr(ExternalIdentity, "access_token")
    assert not hasattr(ExternalIdentity, "refresh_token")
