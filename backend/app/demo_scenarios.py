"""Server-owned fictional inputs for the temporary public demonstration.

These are examples for the real, flexible Motor; they are not its family schema.
The browser sends only an opaque ID and never supplies the narrative or facts.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DemoScenario:
    id: str
    label: str
    vertical: str
    message: str
    facts: tuple[tuple[str, Any], ...]


SCENARIOS = {
    item.id: item for item in (
        DemoScenario(
            "scn_8a1f3c67", "Tarifa de luz distinta a la pactada", "electricity",
            "Ejemplo ficticio: una factura de luz aplica un precio distinto al contratado.",
            (
                ("electricity.consumer_natural_person", True),
                ("electricity.market_type", "free_market"),
                ("electricity.pricing_issue_date", "2026-09-01"),
                ("electricity.pricing_issue_type", "contracted_price_mismatch"),
                ("electricity.pricing_contract_or_offer_evidence_available", True),
                ("electricity.pricing_promised_terms", "0,12 €/kWh (ficticio)"),
                ("electricity.pricing_applied_terms", "0,18 €/kWh (ficticio)"),
                ("electricity.pricing_difference_confirmed", True),
                ("electricity.pricing_estimated_affected_amount", 86.0),
            ),
        ),
        DemoScenario(
            "scn_4d92e7b0", "Garantía de un televisor ficticio", "purchases",
            "Ejemplo ficticio: una tienda rechaza la garantía de un televisor defectuoso.",
            (
                ("purchase.buyer_is_consumer", True),
                ("purchase.seller_is_business", True),
                ("purchase.second_hand", False),
                ("purchase.product_name", "Televisor ficticio"),
                ("purchase.delivery_date", "2026-01-10"),
                ("purchase.defect_manifested_date", "2026-09-01"),
                ("purchase.defect_description", "La pantalla ficticia se queda negra"),
                ("purchase.accidental_damage_or_misuse", False),
                ("purchase.price", 1299.0),
                ("purchase.seller_denied_conformity", True),
            ),
        ),
        DemoScenario(
            "scn_b63c0a51", "Interrupción ficticia de fibra", "telecom",
            "Mi fibra estuvo sin internet 12 horas y no me han compensado",
            (
                ("telecom.subscriber_has_contract", True),
                ("telecom.service_kind", "fixed_internet"),
                ("telecom.service_restored", True),
                ("telecom.interruption_duration_hours", 12.0),
                ("telecom.affected_hours_8_22", 8.0),
                ("telecom.interruption_due_to_serious_subscriber_breach", False),
                ("telecom.interruption_due_to_nonconforming_terminal_damage", False),
                ("telecom.internet_fee_identified", True),
                ("telecom.monthly_internet_fixed_fee", 40.0),
                ("telecom.billing_period_days", 30),
                ("telecom.compensation_already_applied", False),
            ),
        ),
        DemoScenario(
            "scn_e2957f4b", "Fianza ficticia no devuelta", "rentals",
            "Mi casero no me devuelve la fianza del alquiler después de entregar las llaves",
            (
                ("rental.contract_type", "dwelling"),
                ("rental.lease_ended", True),
                ("rental.keys_delivered_date", "2026-08-01"),
                ("rental.keys_delivery_proof_available", True),
                ("rental.deposit_type", "statutory_cash_deposit"),
                ("rental.refundable_balance_status", "confirmed_amount"),
                ("rental.confirmed_refundable_balance", 900.0),
                ("rental.refund_received", False),
            ),
        ),
    )
}


def public_catalog() -> list[dict[str, str]]:
    return [
        {"id": item.id, "label": item.label, "vertical": item.vertical}
        for item in SCENARIOS.values()
    ]
