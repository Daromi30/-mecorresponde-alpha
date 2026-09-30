import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ADMIN_API_TOKEN"] = "test-admin-token"

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.auth import hash_password, normalize_email
from app.auth_models import User
from app.demo_boundary import enforce_demo_boundary
from app.main import app
from app.services_v2 import seed_legal


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with TestingSession() as session:
        seed_legal(session)
        session.commit()
        yield session


@pytest.fixture()
def client(db):
    def override():
        yield db
    def internal_flexible_fixture(request: Request):
        # API regression fixtures deliberately exercise the unrestricted Motor.
        # This override exists only in tests; production has no HTTP escape hatch.
        request.state.allow_flexible_fixture = True
    app.dependency_overrides[get_db] = override
    app.dependency_overrides[enforce_demo_boundary] = internal_flexible_fixture
    with TestClient(app) as test_client:
        def historical_account(email: str, password: str):
            # Seed a pre-existing fictional account outside HTTP, then exercise
            # the real login path. Public registration is never overridden.
            normalized = normalize_email(email)
            db.add(User(email=normalized, password_hash=hash_password(password)))
            db.commit()
            response = test_client.post(
                "/api/auth/login", json={"email": normalized, "password": password}
            )
            assert response.status_code == 200, response.text
            return response

        test_client.historical_account = historical_account
        yield test_client
    app.dependency_overrides.clear()
