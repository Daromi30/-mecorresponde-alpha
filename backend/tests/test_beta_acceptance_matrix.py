from app.family_manifest import FAMILY_MANIFEST


def _fact(client, case_id, key, value):
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={
            "key": key,
            "value": value,
            "state": "confirmed",
            "user_confirmed": True,
        },
    )
    assert response.status_code == 200, response.text


SCENARIOS = {
    "E01": {
        "message": "En mi factura de luz me aplican un precio distinto al contratado",
        "facts": {
            "electricity.consumer_natural_person": True,
            "electricity.market_type": "free_market",
            "electricity.pricing_issue_date": "2026-09-01",
            "electricity.pricing_issue_type": "contracted_price_mismatch",
            "electricity.pricing_contract_or_offer_evidence_available": True,
            "electricity.pricing_promised_terms": "0,12 €/kWh",
            "electricity.pricing_applied_terms": "0,18 €/kWh",
            "electricity.pricing_difference_confirmed": True,
            "electricity.pricing_estimated_affected_amount": 86.0,
        },
    },
    "E02-A": {
        "message": "La factura eléctrica me ha cobrado de más",
        "facts": {
            "electricity.billing.invoice_date": "2026-07-01",
            "electricity.billing.billed_amount": 150.0,
            "electricity.billing.correct_amount": 100.0,
        },
    },
    "E02-B": {
        "message": "Me han cobrado dos veces la misma factura de luz",
        "facts": {"electricity.billing.same_debt": True},
        "charges": [
            {"amount": 74.30, "evidence_verified": True},
            {"amount": 74.30, "evidence_verified": True},
        ],
    },
    "E03": {
        "message": "Me han cambiado de compañía de luz sin mi consentimiento",
        "facts": {
            "electricity.switch_effective_date": "2026-09-01",
            "electricity.previous_supplier": "Comercializadora anterior",
            "electricity.incoming_supplier": "Comercializadora entrante",
            "electricity.possible_identity_theft": False,
            "electricity.switch_cups_correct": True,
            "electricity.express_consent_given": False,
            "electricity.consent_evidence_status": "not_provided",
            "electricity.unsolicited_supply_amount_paid": 43.20,
        },
    },
    "E04-A": {
        "message": "En la factura de luz me cobran un mantenimiento que nunca contraté",
        "facts": {
            "electricity.addon.identity": "Protección Hogar",
            "electricity.addon.ever_contracted": False,
        },
        "charges": [{"amount": 9.99, "evidence_verified": True}],
    },
    "E04-B": {
        "message": "Me cambié de compañía de luz y me siguen cobrando un mantenimiento",
        "facts": {
            "electricity.supply_end_date": "2026-06-03",
            "electricity.addon.identity": "Protección Hogar",
            "electricity.addon.ever_contracted": True,
            "electricity.addon.contracted_with_supply": True,
            "electricity.addon.keep_requested": False,
        },
        "charges": [
            {
                "amount": 8.99,
                "service_period_start": "2026-06-04",
                "service_period_end": "2026-07-03",
                "evidence_verified": True,
            }
        ],
    },
    "E05": {
        "message": "Me cobran una penalización por cambiar de compañía de luz",
        "facts": {
            "electricity.consumer_natural_person": True,
            "electricity.segment_2_0td": True,
            "electricity.termination_date": "2026-09-01",
            "electricity.termination_penalty_amount": 85.0,
            "electricity.switch_to_pvpc_as_vulnerable": False,
            "electricity.fixed_price_contract": False,
        },
    },
    "E06": {
        "message": "Mi factura de luz tiene una lectura estimada porque falló la lectura remota",
        "facts": {
            "electricity.reading_issue_invoice_date": "2026-09-01",
            "electricity.meter_fraud_tampering_or_complex_technical_issue": False,
            "electricity.reading_issue_type": "estimated_reading",
            "electricity.estimated_reading_reason": "remote_reading_failure",
            "electricity.real_reading_obtained_within_bimonthly_cycle": False,
        },
    },
    "E07": {
        "message": "Mi compañía de luz me ha subido el precio sin avisar",
        "facts": {
            "electricity.contract_change_effective_date": "2026-09-01",
            "electricity.contract_change_kind": "contract_condition_change",
            "electricity.change_notice_received": False,
            "electricity.notice_informed_free_termination_right": False,
        },
    },
    "C01": {
        "message": "Compré un televisor en una tienda, está defectuoso y me rechazan la garantía",
        "facts": {
            "purchase.buyer_is_consumer": True,
            "purchase.seller_is_business": True,
            "purchase.second_hand": False,
            "purchase.product_name": "Televisor",
            "purchase.delivery_date": "2026-01-10",
            "purchase.defect_manifested_date": "2026-09-01",
            "purchase.defect_description": "La pantalla se queda negra",
            "purchase.accidental_damage_or_misuse": False,
            "purchase.price": 1299.0,
            "purchase.seller_denied_conformity": True,
        },
    },
    "C02": {
        "message": "Compré un portátil, ya lo repararon y volvió a fallar",
        "facts": {
            "purchase.buyer_is_consumer": True,
            "purchase.seller_is_business": True,
            "purchase.product_name": "Portátil",
            "purchase.delivery_date": "2026-01-10",
            "purchase.price": 899.0,
            "purchase.conformity_attempts": 1,
            "purchase.lack_after_conformity_attempt": True,
            "purchase.seller_declared_will_not_conform": False,
            "purchase.defect_description": "Tras la reparación vuelve a apagarse solo",
            "purchase.same_origin_after_repair": True,
            "purchase.repair_return_date": "2026-08-20",
            "purchase.preferred_secondary_remedy": "termination",
            "purchase.defect_material": True,
        },
    },
    "C03": {
        "message": "Compré un móvil y me enviaron otro modelo distinto a lo anunciado",
        "facts": {
            "purchase.buyer_is_consumer": True,
            "purchase.seller_is_business": True,
            "purchase.product_name": "Móvil",
            "purchase.delivery_date": "2026-09-01",
            "purchase.price": 699.0,
            "purchase.contract_description": "Modelo X Pro, 256 GB, color negro",
            "purchase.received_description": "Modelo X básico, 128 GB, color negro",
            "purchase.mismatch_confirmed": True,
            "purchase.mismatch_material": True,
            "purchase.seller_denied_conformity": False,
        },
    },
    "C04": {
        "message": "Compré una cafetera online y no me ha llegado el pedido",
        "facts": {
            "purchase.buyer_is_consumer": True,
            "purchase.seller_is_business": True,
            "purchase.product_name": "Cafetera",
            "purchase.order_date": "2026-07-01",
            "purchase.amount_paid": 149.90,
            "purchase.delivered": False,
            "purchase.delivery_date_was_agreed": False,
            "purchase.seller_refused_delivery": False,
            "purchase.delivery_date_essential": False,
            "purchase.additional_delivery_period_requested": True,
            "purchase.additional_delivery_period_deadline": "2026-09-10",
        },
    },
    "C05": {
        "message": "Compré unos auriculares online y quiero devolver la compra dentro de 14 días",
        "facts": {
            "purchase.buyer_is_consumer": True,
            "purchase.seller_is_business": True,
            "purchase.distance_contract": True,
            "purchase.product_name": "Auriculares",
            "purchase.received_date": "2026-09-05",
            "purchase.amount_paid": 120.0,
            "purchase.premium_delivery_extra": 0.0,
            "purchase.withdrawal_exception_possible": False,
            "purchase.withdrawal_information_provided": True,
            "purchase.withdrawal_sent": False,
        },
    },
}


def test_beta_acceptance_matrix_covers_every_registered_resolution_family(client):
    assert set(SCENARIOS) == set(FAMILY_MANIFEST)

    for family, scenario in SCENARIOS.items():
        created = client.post("/api/cases", json={"message": scenario["message"]})
        assert created.status_code == 200, f"{family}: {created.text}"
        case = created.json()
        case_id = case["id"]
        manifest = FAMILY_MANIFEST[family]
        assert case["family"] == family
        assert case["vertical"] == manifest.vertical

        for key, value in scenario["facts"].items():
            _fact(client, case_id, key, value)

        charges = scenario.get("charges")
        if charges:
            response = client.post(
                f"/api/cases/{case_id}/charges",
                json={"charges": charges},
            )
            assert response.status_code == 200, f"{family}: {response.text}"

        diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
        assert diagnosis.status_code == 200, f"{family}: {diagnosis.text}"
        decision = diagnosis.json()
        assert decision["viability"] == "HIGH", f"{family}: {decision}"

        prepared = client.post(f"/api/cases/{case_id}/prepare-claim")
        assert prepared.status_code == 200, f"{family}: {prepared.text}"
        package = prepared.json()
        assert package["claim_type"], family
        assert package["text"], family
        assert package["legal_basis"], family
        for legal in package["legal_basis"]:
            assert legal["rule_id"] in manifest.rule_ids, (family, legal)
            assert legal["version"] >= 1, (family, legal)
            assert legal["article"], (family, legal)
            assert legal["source"], (family, legal)
            assert legal["official_url"].startswith("https://www.boe.es/"), (family, legal)

        refreshed = client.get(f"/api/cases/{case_id}")
        assert refreshed.status_code == 200, f"{family}: {refreshed.text}"
        assert refreshed.json()["status"] == "READY_TO_SUBMIT", family
