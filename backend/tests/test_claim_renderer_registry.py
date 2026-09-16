import pytest
from sqlalchemy import func, select

from app import services_v2 as svc
from app.family_manifest import FAMILY_MANIFEST
from app.models import Action, Case, Decision, Fact, LegalRuleVersion


EXTENSION_FAMILY_SCENARIOS = {
    "E01": {
        "action": "PREPARE_E01_PRICING_CORRECTION",
        "claimable": 0.0,
        "economic": 25.0,
        "facts": {
            "electricity.pricing_promised_terms": "0,15 €/kWh",
            "electricity.pricing_applied_terms": "0,19 €/kWh",
        },
        "claim_type": "E01_CONTRACTED_PRICE_OR_TARIFF_CORRECTION",
    },
    "E03": {
        "action": "PREPARE_UNAUTHORIZED_SWITCH_RESTORATION",
        "claimable": 35.0,
        "economic": 35.0,
        "facts": {
            "electricity.previous_supplier": "Comercializadora anterior",
            "electricity.incoming_supplier": "Comercializadora nueva",
            "electricity.express_consent_given": False,
            "electricity.switch_cups_correct": True,
        },
        "claim_type": "E03_UNAUTHORIZED_SWITCH_RESTORATION",
    },
    "E05": {
        "action": "PREPARE_E05_PENALTY_REFUND",
        "claimable": 49.99,
        "economic": 49.99,
        "facts": {},
        "claim_type": "E05_TERMINATION_PENALTY_REFUND",
    },
    "E06": {
        "action": "PREPARE_E06_LIMIT_REGULARIZATION",
        "claimable": 0.0,
        "economic": 120.0,
        "facts": {"electricity.regularization_period_months": 18},
        "claim_type": "E06_LIMIT_UNDERBILLING_REGULARIZATION",
    },
    "E07": {
        "action": "PREPARE_E07_CHANGE_CHALLENGE",
        "claimable": 0.0,
        "economic": None,
        "facts": {},
        "claim_type": "E07_CONTRACT_CHANGE_NOTICE_CHALLENGE",
    },
    "C02": {
        "action": "PREPARE_C02_TERMINATION",
        "claimable": 129.0,
        "economic": 129.0,
        "facts": {
            "purchase.product_name": "cafetera",
            "purchase.defect_material": True,
        },
        "claim_type": "C02_TERMINATION_AFTER_FAILED_CONFORMITY",
    },
    "C03": {
        "action": "PREPARE_C03_CONFORMITY_CLAIM",
        "claimable": 0.0,
        "economic": 80.0,
        "facts": {
            "purchase.product_name": "chaqueta",
            "purchase.contract_description": "chaqueta azul talla M",
            "purchase.received_description": "chaqueta negra talla L",
        },
        "claim_type": "C03_CONTRACT_MISMATCH_CONFORMITY",
    },
}


def _latest_rule(db, rule_id):
    return db.scalar(
        select(LegalRuleVersion)
        .where(LegalRuleVersion.rule_id == rule_id)
        .order_by(LegalRuleVersion.version.desc())
    )


def _build_ready_case(db, family, scenario):
    vertical = FAMILY_MANIFEST[family].vertical
    case = Case(status="DIAGNOSED", vertical=vertical, family=family, title=f"Test {family}")
    db.add(case)
    db.flush()

    for key, value in scenario["facts"].items():
        db.add(
            Fact(
                case_id=case.id,
                key=key,
                value_json={"value": value},
                state="confirmed",
                materiality="critical",
                user_confirmed=True,
                created_by="user",
            )
        )

    rule_evaluations = []
    for rule_id in FAMILY_MANIFEST[family].rule_ids:
        rule = _latest_rule(db, rule_id)
        assert rule is not None, rule_id
        rule_evaluations.append(
            {
                "rule_id": rule.rule_id,
                "version": rule.version,
                "result": "APPLIES",
                "remedies": ["TEST_REMEDY"],
                "burden_of_proof": [],
            }
        )

    decision = Decision(
        case_id=case.id,
        viability="HIGH",
        scope_status="SUPPORTED",
        economic_value=scenario["economic"],
        claimable_amount=scenario["claimable"],
        worth_pursuing="YES",
        reasoning_summary="Scenario already covered by the family evaluator tests.",
        counterarguments_snapshot=[],
        rule_evaluations_json=rule_evaluations,
    )
    db.add(decision)
    db.flush()

    action = Action(case_id=case.id, type=scenario["action"], status="OPEN", payload_json={})
    db.add(action)
    db.flush()
    case.current_decision_id = decision.id
    case.current_action_id = action.id
    db.commit()
    return case, action


@pytest.mark.parametrize("family", sorted(EXTENSION_FAMILY_SCENARIOS))
def test_extension_family_registry_preserves_claim_contract_and_adds_verified_provenance(db, family):
    scenario = EXTENSION_FAMILY_SCENARIOS[family]
    case, previous_action = _build_ready_case(db, family, scenario)

    package = svc.prepare_claim_package(db, case)

    assert package["claim_type"] == scenario["claim_type"]
    assert package["currency"] == "EUR"
    assert package["text"]
    assert package["legal_basis"]
    assert all(item["official_url"].startswith("https://www.boe.es/") for item in package["legal_basis"])
    assert all(item["version"] >= 1 for item in package["legal_basis"])
    assert all(item["rule_id"] in FAMILY_MANIFEST[family].rule_ids for item in package["legal_basis"])

    db.refresh(previous_action)
    db.refresh(case)
    assert previous_action.status == "COMPLETED"
    assert previous_action.completed_at is not None
    assert case.status == "READY_TO_SUBMIT"
    assert case.current_action_id == package["action_id"]
    submit = db.get(Action, package["action_id"])
    assert submit.type == "SUBMIT_INITIAL_CLAIM"
    assert submit.status == "READY"


def test_registry_claim_package_preparation_is_idempotent(db):
    case, _ = _build_ready_case(db, "E03", EXTENSION_FAMILY_SCENARIOS["E03"])
    first = svc.prepare_claim_package(db, case)
    second = svc.prepare_claim_package(db, case)
    assert second == first
    assert db.scalar(
        select(func.count()).select_from(Action).where(
            Action.case_id == case.id,
            Action.type == "SUBMIT_INITIAL_CLAIM",
        )
    ) == 1


def test_unquantified_routes_do_not_turn_economic_value_into_claim_amount(db):
    for family in ["E01", "E06", "E07", "C03"]:
        scenario = EXTENSION_FAMILY_SCENARIOS[family]
        case, _ = _build_ready_case(db, family, scenario)
        package = svc.prepare_claim_package(db, case)
        assert package["amount"] == 0.0
        if scenario["economic"] is not None:
            assert package["economic_value"] == scenario["economic"]


def test_price_reduction_route_refuses_to_invent_a_proportional_amount(db):
    scenario = {
        **EXTENSION_FAMILY_SCENARIOS["C02"],
        "action": "PREPARE_C02_PRICE_REDUCTION",
        "claimable": 0.0,
        "facts": {"purchase.product_name": "cafetera"},
    }
    case, _ = _build_ready_case(db, "C02", scenario)
    package = svc.prepare_claim_package(db, case)
    assert package["claim_type"] == "C02_PRICE_REDUCTION_AFTER_FAILED_CONFORMITY"
    assert package["amount"] == 0.0
    assert "no se inventa automáticamente" in package["text"]


def test_claim_rendering_fails_closed_if_reviewed_rule_is_not_approved(db):
    scenario = EXTENSION_FAMILY_SCENARIOS["E05"]
    case, _ = _build_ready_case(db, "E05", scenario)
    rule_id = FAMILY_MANIFEST["E05"].rule_ids[0]
    rule = _latest_rule(db, rule_id)
    rule.review_status = "pending"
    db.commit()

    with pytest.raises(ValueError, match="Reviewed legal rule version missing"):
        svc.prepare_claim_package(db, case)
