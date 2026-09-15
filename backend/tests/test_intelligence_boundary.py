import pytest
from sqlalchemy import func, select

from app.engine.gateway import DeterministicAlphaGateway
from app.engine.guarded_gateway import GuardedModelGateway
from app.engine.model_contracts import ModelOutputRejected
from app.family_manifest import FAMILY_MANIFEST
from app.models import Case
import app.services_v2 as services


class MaliciousClassifier:
    def classify(self, text):
        return {
            "vertical": "electricity",
            "family": "E02-B",
            "confidence": 0.99,
            "legal_basis": ["invented-law"],
            "success_probability": 0.98,
        }

    def extract(self, text):
        return {"mentioned_amounts": []}

    def analyze_response(self, text):
        return {"type": "UNKNOWN", "arguments": []}


class WrongFamilyClassifier:
    def classify(self, text):
        return {"vertical": "purchases", "family": "E02-B", "confidence": 0.9}

    def extract(self, text):
        return {"mentioned_amounts": []}

    def analyze_response(self, text):
        return {"type": "UNKNOWN", "arguments": []}


class InventedResponseArgument:
    def classify(self, text):
        return {"vertical": None, "family": None, "confidence": 0.1}

    def extract(self, text):
        return {"mentioned_amounts": []}

    def analyze_response(self, text):
        return {
            "type": "DENIAL",
            "arguments": ["THE_COMPANY_IS_LEGALLY_RIGHT"],
        }


def test_registered_family_manifest_is_the_only_model_routing_space():
    gateway = GuardedModelGateway(DeterministicAlphaGateway())
    result = gateway.classify("Me han cobrado dos veces la misma factura de luz")
    assert result["family"] == "E02-B"
    assert result["vertical"] == FAMILY_MANIFEST["E02-B"].vertical
    assert 0 <= result["confidence"] <= 1


def test_model_cannot_inject_legal_basis_or_success_probability():
    gateway = GuardedModelGateway(MaliciousClassifier())
    with pytest.raises(ModelOutputRejected):
        gateway.classify("texto cualquiera")


def test_model_cannot_route_family_into_wrong_vertical():
    gateway = GuardedModelGateway(WrongFamilyClassifier())
    with pytest.raises(ModelOutputRejected):
        gateway.classify("texto cualquiera")


def test_model_cannot_invent_company_argument_taxonomy():
    gateway = GuardedModelGateway(InventedResponseArgument())
    with pytest.raises(ModelOutputRejected):
        gateway.analyze_response("respuesta de empresa")


def test_extraction_contract_does_not_accept_claimable_amount():
    class BadExtractor:
        def classify(self, text):
            return {"vertical": None, "family": None, "confidence": 0.1}

        def extract(self, text):
            return {"mentioned_amounts": [220.0], "claimable_amount": 220.0}

        def analyze_response(self, text):
            return {"type": "UNKNOWN", "arguments": []}

    gateway = GuardedModelGateway(BadExtractor())
    with pytest.raises(ModelOutputRejected):
        gateway.extract("Pagué 220 euros")


def test_invalid_model_output_fails_closed_at_case_creation(client, db, monkeypatch):
    before = db.scalar(select(func.count()).select_from(Case)) or 0
    monkeypatch.setattr(services, "gateway", GuardedModelGateway(MaliciousClassifier()))

    response = client.post(
        "/api/cases",
        json={"message": "Me han cobrado dos veces la misma factura de luz"},
    )

    assert response.status_code == 503
    assert "No se ha generado ninguna conclusión jurídica" in response.json()["detail"]
    db.expire_all()
    after = db.scalar(select(func.count()).select_from(Case)) or 0
    assert after == before
