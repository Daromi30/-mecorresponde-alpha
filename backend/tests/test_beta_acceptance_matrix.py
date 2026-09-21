from datetime import timedelta

from app.calendar_clock import spain_today
from app.family_manifest import FAMILY_MANIFEST
from app.legal_source_registry import is_trusted_official_legal_url


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


RECENT_C05_RECEIVED_DATE = (spain_today() - timedelta(days=7)).isoformat()

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
    "T01": {
        "message": "Mi fibra de internet estuvo cortada 12 horas y la operadora no me ha compensado",
        "facts": {
            "telecom.subscriber_has_contract": True,
            "telecom.service_kind": "fixed_internet",
            "telecom.service_restored": True,
            "telecom.interruption_duration_hours": 12.0,
            "telecom.affected_hours_8_22": 8.0,
            "telecom.interruption_due_to_serious_subscriber_breach": False,
            "telecom.interruption_due_to_nonconforming_terminal_damage": False,
            "telecom.internet_fee_identified": True,
            "telecom.monthly_internet_fixed_fee": 40.0,
            "telecom.billing_period_days": 30,
            "telecom.compensation_already_applied": False,
        },
    },
    "T02": {
        "message": "Mi operadora de fibra me ha subido el precio y me ha comunicado un cambio de condiciones",
        "facts": {
            "telecom.final_user_contract": True,
            "telecom.change_notice_received": True,
            "telecom.change_exception_type": "adverse_or_other",
            "telecom.change_notice_date": "2026-09-10",
            "telecom.change_effective_date": "2026-10-15",
            "telecom.notice_informed_free_termination_right": True,
            "telecom.notice_clear_and_durable": True,
            "telecom.contract_contains_valid_change_reason": True,
            "telecom.user_wants_to_terminate": True,
            "telecom.retains_subsidized_terminal": False,
        },
    },
    "V01": {
        "message": "Ryanair me ha cancelado el vuelo y quiero que me devuelvan el dinero del billete",
        "facts": {
            "travel.flight_cancelled_by_operating_carrier": True,
            "travel.cancellation_notified_date": "2026-09-18",
            "travel.departure_airport_in_eu": True,
            "travel.confirmed_reservation": True,
            "travel.fare_status": "public_fare",
            "travel.package_trip": False,
            "travel.booking_scope": "single_flight",
            "travel.passenger_choice": "refund",
            "travel.documented_ticket_price": 189.90,
            "travel.refund_received": False,
        },
    },
    "V02": {
        "message": "Mi vuelo lleva más de cinco horas de retraso y quiero que me devuelvan el billete",
        "facts": {
            "travel.departure_delay_hours": 5.5,
            "travel.departure_airport_in_eu": True,
            "travel.confirmed_reservation": True,
            "travel.fare_status": "public_fare",
            "travel.package_trip": False,
            "travel.booking_scope": "single_flight",
            "travel.delay_refund_requested": True,
            "travel.passenger_took_delayed_flight": False,
            "travel.documented_ticket_price": 210.0,
            "travel.refund_received": False,
        },
    },
    "V03": {
        "message": "Tenía reserva y por overbooking no me dejaron embarcar en mi vuelo",
        "facts": {
            "travel.denied_boarding_involuntary": True,
            "travel.departure_airport_in_eu": True,
            "travel.confirmed_reservation": True,
            "travel.presentation_requirement_met": True,
            "travel.fare_status": "public_fare",
            "travel.denied_boarding_reason": "operational_or_no_reason",
            "travel.distance_band": "le_1500",
            "travel.rerouted_to_final_destination": False,
            "travel.compensation_received": False,
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
            "purchase.received_date": RECENT_C05_RECEIVED_DATE,
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
            assert is_trusted_official_legal_url(legal["official_url"]), (family, legal)

        refreshed = client.get(f"/api/cases/{case_id}")
        assert refreshed.status_code == 200, f"{family}: {refreshed.text}"
        assert refreshed.json()["status"] == "READY_TO_SUBMIT", family
