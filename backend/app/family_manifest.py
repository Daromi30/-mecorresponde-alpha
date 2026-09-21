from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FamilyManifestEntry:
    code: str
    vertical: str
    title: str
    rule_ids: tuple[str, ...]


FAMILY_MANIFEST: dict[str, FamilyManifestEntry] = {
    "E01": FamilyManifestEntry(
        code="E01",
        vertical="electricity",
        title="Precio, tarifa o descuento eléctrico distinto de lo contratado",
        rule_ids=("ELEC_PRICING_TERMS_CURRENT", "CONSUMER_OFFER_BINDING"),
    ),
    "E02-A": FamilyManifestEntry(
        code="E02-A",
        vertical="electricity",
        title="Posible sobrefacturación eléctrica",
        rule_ids=("ELEC_OVERBILL_REFUND",),
    ),
    "E02-B": FamilyManifestEntry(
        code="E02-B",
        vertical="electricity",
        title="Posible cobro duplicado",
        rule_ids=("UNDUE_PAYMENT_RESTITUTION",),
    ),
    "E03": FamilyManifestEntry(
        code="E03",
        vertical="electricity",
        title="Cambio de comercializadora sin consentimiento",
        rule_ids=("ELEC_SWITCH_EXPRESS_CONSENT",),
    ),
    "E04-A": FamilyManifestEntry(
        code="E04-A",
        vertical="electricity",
        title="Servicio adicional no contratado",
        rule_ids=("UNSOLICITED_SERVICE_NO_PAYMENT", "ADDITIONAL_PAYMENT_EXPRESS_CONSENT"),
    ),
    "E04-B": FamilyManifestEntry(
        code="E04-B",
        vertical="electricity",
        title="Mantenimiento tras cambio de comercializadora",
        rule_ids=("ELEC_ADDON_END_WITH_SUPPLY",),
    ),
    "E05": FamilyManifestEntry(
        code="E05",
        vertical="electricity",
        title="Penalización o permanencia al cancelar la luz",
        rule_ids=("ELEC_TERMINATION_PENALTY_CURRENT",),
    ),
    "E06": FamilyManifestEntry(
        code="E06",
        vertical="electricity",
        title="Lectura estimada o regularización de consumo",
        rule_ids=("ELEC_READING_BILLING_CURRENT",),
    ),
    "E07": FamilyManifestEntry(
        code="E07",
        vertical="electricity",
        title="Cambio de precio o condiciones del contrato eléctrico",
        rule_ids=("ELEC_CONTRACT_CHANGE_NOTICE_CURRENT",),
    ),
    "T01": FamilyManifestEntry(
        code="T01",
        vertical="telecom",
        title="Interrupción temporal del acceso a internet fijo y compensación",
        rule_ids=("TELECOM_FIXED_INTERNET_INTERRUPTION_COMPENSATION",),
    ),
    "T02": FamilyManifestEntry(
        code="T02",
        vertical="telecom",
        title="Cambio de precio o condiciones del contrato de telecomunicaciones",
        rule_ids=("TELECOM_CONTRACT_CHANGE_FREE_TERMINATION",),
    ),
    "V01": FamilyManifestEntry(
        code="V01",
        vertical="travel",
        title="Vuelo cancelado por la aerolínea y reembolso del billete",
        rule_ids=("AIR_CANCELLATION_REFUND_CURRENT",),
    ),
    "C01": FamilyManifestEntry(
        code="C01",
        vertical="purchases",
        title="Producto defectuoso o garantía rechazada",
        rule_ids=("GOODS_CONFORMITY_CURRENT",),
    ),
    "C02": FamilyManifestEntry(
        code="C02",
        vertical="purchases",
        title="Reparación fallida, repetida o demorada",
        rule_ids=("GOODS_POST_CONFORMITY_ATTEMPT",),
    ),
    "C03": FamilyManifestEntry(
        code="C03",
        vertical="purchases",
        title="Producto equivocado, incompleto o distinto de lo contratado",
        rule_ids=("GOODS_CONTRACT_DESCRIPTION",),
    ),
    "C04": FamilyManifestEntry(
        code="C04",
        vertical="purchases",
        title="Pedido no entregado",
        rule_ids=("GOODS_DELIVERY_CURRENT",),
    ),
    "C05": FamilyManifestEntry(
        code="C05",
        vertical="purchases",
        title="Desistimiento o devolución de compra a distancia",
        rule_ids=("DISTANCE_WITHDRAWAL_CURRENT",),
    ),
}


def supported_family_codes() -> tuple[str, ...]:
    return tuple(FAMILY_MANIFEST)


def family_title(code: str | None) -> str:
    entry = FAMILY_MANIFEST.get(code or "")
    return entry.title if entry else "Caso por clasificar"
