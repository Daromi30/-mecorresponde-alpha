from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class FamilyManifestEntry:
    code: str
    vertical: str
    title: str
    rule_ids: tuple[str, ...]

FAMILY_MANIFEST: dict[str, FamilyManifestEntry] = {
    "E01": FamilyManifestEntry("E01","electricity","Precio, tarifa o descuento eléctrico distinto de lo contratado",("ELEC_PRICING_TERMS_CURRENT","CONSUMER_OFFER_BINDING")),
    "E02-A": FamilyManifestEntry("E02-A","electricity","Posible sobrefacturación eléctrica",("ELEC_OVERBILL_REFUND",)),
    "E02-B": FamilyManifestEntry("E02-B","electricity","Posible cobro duplicado",("UNDUE_PAYMENT_RESTITUTION",)),
    "E03": FamilyManifestEntry("E03","electricity","Cambio de comercializadora sin consentimiento",("ELEC_SWITCH_EXPRESS_CONSENT",)),
    "E04-A": FamilyManifestEntry("E04-A","electricity","Servicio adicional no contratado",("UNSOLICITED_SERVICE_NO_PAYMENT","ADDITIONAL_PAYMENT_EXPRESS_CONSENT")),
    "E04-B": FamilyManifestEntry("E04-B","electricity","Mantenimiento tras cambio de comercializadora",("ELEC_ADDON_END_WITH_SUPPLY",)),
    "E05": FamilyManifestEntry("E05","electricity","Penalización o permanencia al cancelar la luz",("ELEC_TERMINATION_PENALTY_CURRENT",)),
    "E06": FamilyManifestEntry("E06","electricity","Lectura estimada o regularización de consumo",("ELEC_READING_BILLING_CURRENT",)),
    "E07": FamilyManifestEntry("E07","electricity","Cambio de precio o condiciones del contrato eléctrico",("ELEC_CONTRACT_CHANGE_NOTICE_CURRENT",)),
    "T01": FamilyManifestEntry("T01","telecom","Interrupción temporal del acceso a internet fijo y compensación",("TELECOM_FIXED_INTERNET_INTERRUPTION_COMPENSATION",)),
    "T02": FamilyManifestEntry("T02","telecom","Cambio de precio o condiciones del contrato de telecomunicaciones",("TELECOM_CONTRACT_CHANGE_FREE_TERMINATION",)),
    "V01": FamilyManifestEntry("V01","travel","Vuelo cancelado por la aerolínea y reembolso del billete",("AIR_CANCELLATION_REFUND_CURRENT",)),
    "V02": FamilyManifestEntry("V02","travel","Vuelo retrasado al menos cinco horas y reembolso del billete",("AIR_FIVE_HOUR_DELAY_REFUND_CURRENT",)),
    "V03": FamilyManifestEntry("V03","travel","Denegación involuntaria de embarque y compensación",("AIR_INVOLUNTARY_DENIED_BOARDING_COMPENSATION_CURRENT",)),
    "B01": FamilyManifestEntry("B01","banking","Operación de pago no autorizada y solicitud de reembolso",("PAYMENT_UNAUTHORIZED_REFUND_CURRENT",)),
    "B02": FamilyManifestEntry("B02","banking","Adeudo domiciliado autorizado y solicitud de devolución",("PAYMENT_AUTHORIZED_DIRECT_DEBIT_REFUND_CURRENT",)),
    "B03": FamilyManifestEntry("B03","banking","Comisión bancaria por servicio no solicitado, no aceptado o no prestado",("BANK_FEE_REQUEST_AND_SERVICE_CURRENT",)),
    "C01": FamilyManifestEntry("C01","purchases","Producto defectuoso o garantía rechazada",("GOODS_CONFORMITY_CURRENT",)),
    "C02": FamilyManifestEntry("C02","purchases","Reparación fallida, repetida o demorada",("GOODS_POST_CONFORMITY_ATTEMPT",)),
    "C03": FamilyManifestEntry("C03","purchases","Producto equivocado, incompleto o distinto de lo contratado",("GOODS_CONTRACT_DESCRIPTION",)),
    "C04": FamilyManifestEntry("C04","purchases","Pedido no entregado",("GOODS_DELIVERY_CURRENT",)),
    "C05": FamilyManifestEntry("C05","purchases","Desistimiento o devolución de compra a distancia",("DISTANCE_WITHDRAWAL_CURRENT",)),
}

def supported_family_codes() -> tuple[str, ...]: return tuple(FAMILY_MANIFEST)
def family_title(code: str | None) -> str:
    entry=FAMILY_MANIFEST.get(code or "")
    return entry.title if entry else "Caso por clasificar"
