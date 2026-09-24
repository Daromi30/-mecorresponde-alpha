from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Protocol


class ModelGateway(Protocol):
    def classify(self, text: str) -> dict[str, Any]: ...
    def extract(self, text: str) -> dict[str, Any]: ...
    def analyze_response(self, text: str) -> dict[str, Any]: ...


def _normalized(text: str) -> str:
    lowered = text.lower()
    return "".join(
        char for char in unicodedata.normalize("NFD", lowered)
        if unicodedata.category(char) != "Mn"
    )


_ACCEPTANCE_PHRASES = (
    "aceptamos su reclamacion", "aceptamos la reclamacion",
    "aceptamos esta reclamacion", "aceptamos la devolucion",
    "aceptamos el reembolso", "estimamos su reclamacion", "devolveremos",
    "procedemos a devolver", "procedemos a reparar", "procedemos a sustituir",
    "restableceremos su contrato anterior",
)
_NEGATED_ACCEPTANCE = re.compile(
    r"\b(?:no|nunca|tampoco|ni)\s+(?:(?:le|les|se|podemos|vamos|hemos|a)\s+){0,3}"
    r"(?:aceptamos|estimamos|devolvemos|devolveremos|reembolsamos|reembolsaremos|"
    r"procedemos\s+a\s+(?:devolver|reparar|sustituir)|"
    r"restableceremos)\b"
)
_EXPLICIT_REJECTION = re.compile(
    r"\b(?:rechazamos|desestimamos|denegamos)\s+(?:su|la|el|esta|este)\s+"
    r"(?:reclamacion|solicitud|peticion|reembolso|devolucion)\b"
)
_REMEDY_REFUSAL = re.compile(
    r"\b(?:no|ni)\s+(?:la|el|su|los|las)\s+"
    r"(?:devolucion|reembolso|reparacion|sustitucion|compensacion|importe|pago)\b"
)


@dataclass
class DeterministicAlphaGateway:
    """No LLM. Validates routing/rules/workflow before a model provider is added."""

    def classify(self, text: str) -> dict[str, Any]:
        t = _normalized(text)
        electricity = any(w in t for w in ["luz", "electric", "comercializadora", "endesa", "iberdrola", "naturgy", "repsol", "factura electrica", "cups", "contador", "tarifa"])
        maintenance = any(w in t for w in ["mantenimiento", "servicio", "proteccion", "asistencia"])
        switch = any(w in t for w in ["cambie", "cambiar", "cambio", "baja", "me fui", "otra compania"])
        never = any(w in t for w in ["nunca contrat", "no contrate", "sin contratar", "no lo pedi"])
        duplicate = any(w in t for w in ["dos veces", "duplicado", "duplicada", "doble cargo", "doble cobro", "me lo han cobrado dos"])
        overbill = any(w in t for w in ["cobrado de mas", "facturado de mas", "factura incorrecta", "importe incorrecto", "me cobran mas"])
        tariff_mismatch = "tarifa" in t and any(w in t for w in [
            "distinta", "diferente", "incorrecta", "otra tarifa", "no contrate", "no contratada",
        ])
        pricing_mismatch = tariff_mismatch or any(w in t for w in [
            "precio distinto al contratado", "precio diferente al contratado", "precio distinto de lo contratado",
            "precio distinto al ofertado", "precio diferente al ofertado", "no respetan el precio", "no me respetan el precio",
            "tarifa distinta a la contratada", "tarifa diferente a la contratada", "tarifa distinta", "tarifa diferente", "tarifa es distinta", "tarifa que no contrate", "tarifa incorrecta", "otra tarifa",
            "no me aplican el descuento", "no respetan el descuento", "no me respetan el descuento", "descuento no aplicado",
            "me quito un descuento", "me quitaron un descuento", "me han quitado un descuento", "me quitaron el descuento", "me han quitado el descuento",
            "descuento prometido", "descuento que me prometieron", "descuento promocional", "promocion no aplicada", "promocion distinta", "descuento distinto",
        ])
        unauthorized_switch = any(w in t for w in [
            "me cambiaron de compania", "me han cambiado de compania",
            "cambio sin permiso", "cambio sin mi permiso", "sin consentimiento", "no autorice el cambio",
            "no acepte cambiar", "comercializadora que no contrate",
            "cups incorrecto", "cups equivocado", "cambio de comercializadora no solicitado",
        ])
        termination_penalty = any(w in t for w in [
            "penalizacion", "penalidad", "permanencia", "cargo por cancelar",
            "cargo por cambiar", "me cobran por irme", "me cobran por cambiar", "cobro por rescindir",
            "penalizacion por rescision", "penalizacion por baja",
        ])
        reading_regularization = any(w in t for w in [
            "lectura estimada", "consumo estimado", "lecturas estimadas", "consumos estimados",
            "regularizacion", "me regularizan", "factura de regularizacion",
            "lectura real", "fallo de lectura", "no pudieron leer el contador", "no pudieron acceder al contador",
            "estimaron el consumo", "estimacion del consumo",
        ])
        contract_change = any(w in t for w in [
            "subida sin avisar", "subida de precio", "subida del precio",
            "subieron el precio sin avisar", "me ha subido el precio", "me han subido el precio", "me subieron el precio", "me subio el precio",
            "me cambiaron el precio", "me ha cambiado el precio", "me han cambiado el precio",
            "cambio de precio", "cambio de condiciones", "cambiaron las condiciones", "me ha cambiado las condiciones", "me han cambiado las condiciones",
            "modificaron el contrato", "modificacion del contrato",
            "revision de precio", "revision de precios", "actualizacion de precio", "formula de revision",
        ])
        telecom = any(w in t for w in [
            "internet", "fibra", "router", "wifi", "operador", "operadora",
            "movistar", "vodafone", "orange", "digi", "o2", "masmovil", "yoigo",
        ])
        telecom_interruption = any(w in t for w in [
            "sin internet", "sin fibra", "corte de internet", "corte de fibra",
            "interrupcion", "cortad", "se cayo internet", "caida de internet", "averia de internet",
            "internet no funciona", "fibra no funciona", "estuve sin internet",
        ])
        banking = any(w in t for w in [
            "banco", "bancaria", "bancario", "cuenta", "tarjeta", "transferencia",
            "operacion de pago", "cargo", "bizum", "pago", "adeudo",
        ])
        explicit_unauthorized_payment = any(w in t for w in [
            "no autorice", "no he autorizado", "no reconozco", "operacion no autorizada",
            "cargo no autorizado", "pago no autorizado", "transferencia no autorizada",
        ])
        unauthorized_payment = explicit_unauthorized_payment or any(w in t for w in [
            "me han cargado", "me cargaron", "me han quitado dinero",
        ])
        authorized_direct_debit = any(w in t for w in [
            "adeudo domiciliado", "recibo domiciliado", "devolver un recibo",
            "devolucion del recibo", "devolucion de un recibo",
        ])
        banking_fee = any(w in t for w in [
            "comision bancaria", "comision del banco", "me han cobrado una comision",
            "me cobraron una comision", "me cobran una comision", "comision que no pedi",
            "comision por un servicio que no solicite", "comision por servicio no prestado",
            "comision sin servicio",
        ])
        rental = any(w in t for w in [
            "alquiler", "arrendamiento", "arrendador", "casero", "inquilino",
            "piso alquilado", "local alquilado", "entrega de llaves",
        ])
        rental_deposit = any(w in t for w in [
            "fianza", "no me devuelve la fianza", "no me devuelven la fianza",
            "devolver la fianza", "devolucion de la fianza", "retiene la fianza",
            "se queda con la fianza",
        ])
        insurance = any(w in t for w in [
            "seguro", "aseguradora", "asegurador", "poliza", "siniestro",
            "indemnizacion del seguro", "compania de seguros",
        ])
        insurance_nonpayment = any(w in t for w in [
            "no me paga", "no me la paga", "no me han pagado", "no me ha pagado",
            "no paga la indemnizacion", "no paga el siniestro",
            "pago minimo", "importe minimo", "cantidad minima", "40 dias", "cuarenta dias",
            "cantidad reconocida", "importe reconocido", "ha reconocido una cantidad",
        ])
        insurance_nonrenewal = any(w in t for w in [
            "no renovar el seguro", "no quiero renovar", "no quiero que se renueve",
            "cancelar la renovacion", "evitar la renovacion", "oponerme a la renovacion",
            "oposicion a la prorroga", "dar de baja al vencimiento",
            "que no se prorrogue", "que no me renueven el seguro",
        ])
        automotive = any(w in t for w in [
            "coche", "vehiculo", "automovil", "taller", "mecanico", "reparacion del coche",
            "reparacion del vehiculo", "garaje mecanico",
        ])
        automotive_repair_failure = any(w in t for w in [
            "repararon y volvio a fallar", "repararon y vuelve a fallar",
            "averia despues de reparar", "averia tras la reparacion",
            "reparacion fallida", "garantia del taller", "garantia de la reparacion",
            "misma averia despues de reparar", "fallo en la pieza reparada",
            "volvio a fallar", "vuelve a fallar",
        ])
        travel = any(w in t for w in [
            "vuelo", "aerolinea", "aeropuerto", "billete de avion", "pasajero",
            "ryanair", "iberia", "vueling", "easyjet", "air europa", "volotea",
        ])
        denied_boarding = any(w in t for w in [
            "denegaron el embarque", "denegacion de embarque", "no me dejaron embarcar",
            "no me dejaron subir", "me dejaron en tierra", "overbooking", "sobreventa",
            "me impidieron embarcar",
        ])
        flight_delay = any(w in t for w in [
            "vuelo retrasado", "retraso del vuelo", "retraso de vuelo",
            "vuelo lleva", "vuelo tiene retraso", "demora del vuelo",
            "cinco horas de retraso", "5 horas de retraso",
        ])
        flight_cancellation = any(w in t for w in [
            "vuelo cancelado", "cancelaron el vuelo", "cancelaron mi vuelo",
            "me ha cancelado el vuelo", "me han cancelado el vuelo",
            "ha cancelado el vuelo", "han cancelado el vuelo",
            "aerolinea cancelo", "aerolinea ha cancelado", "me cancelaron",
            "cancelacion del vuelo", "cancelacion de vuelo",
        ])
        purchase = any(w in t for w in ["compre", "comprado", "compra", "tienda", "vendedor", "producto", "pedido", "televisor", "tv", "movil", "telefono", "ordenador", "portatil", "lavadora", "nevera", "electrodomestico"])
        conformity = any(w in t for w in ["garantia", "defecto", "defectuoso", "averia", "averiado", "roto", "no funciona", "dejo de funcionar", "rechazan la garantia"])
        repair_followup = any(w in t for w in [
            "ya lo repararon", "ya la repararon", "despues de reparar", "tras la reparacion",
            "volvio a fallar", "sigue fallando", "otra vez falla", "segunda reparacion",
            "lleva en reparacion", "sigue en reparacion", "reparacion fallida",
        ])
        mismatch = any(w in t for w in [
            "producto equivocado", "me enviaron otro", "me mandaron otro", "no corresponde con lo comprado", "no coincide con lo comprado",
            "distinto a lo anunciado", "distinto de lo anunciado", "no es como se anunciaba", "no es lo que pedi",
            "incompleto", "faltan piezas", "faltan accesorios", "falta una pieza", "cantidad incorrecta", "vino otro modelo",
        ])
        non_delivery = any(w in t for w in [
            "no ha llegado", "no me ha llegado", "no nos ha llegado", "no llego", "no llega",
            "no recibido", "no he recibido", "no lo he recibido", "no la he recibido", "no hemos recibido",
            "no lo recibi", "no me entregan", "no me lo entregan", "no entregado", "sin entregar",
            "pedido perdido", "pedido no entregado", "sigue sin llegar", "sigue sin entregar",
        ])
        distance = any(w in t for w in ["online", "internet", "web", "a distancia", "por telefono", "pedido"])
        withdrawal = any(w in t for w in ["desist", "quiero devolver", "quiero devolverlo", "me arrepenti", "devolver la compra", "derecho de devolucion", "14 dias"])

        if electricity and unauthorized_switch:
            return {"vertical": "electricity", "family": "E03", "confidence": 0.96}
        if electricity and termination_penalty:
            return {"vertical": "electricity", "family": "E05", "confidence": 0.95}
        if electricity and pricing_mismatch:
            return {"vertical": "electricity", "family": "E01", "confidence": 0.95}
        if electricity and contract_change:
            return {"vertical": "electricity", "family": "E07", "confidence": 0.94}
        if electricity and reading_regularization:
            return {"vertical": "electricity", "family": "E06", "confidence": 0.93}
        if electricity and duplicate:
            return {"vertical": "electricity", "family": "E02-B", "confidence": 0.96}
        if electricity and overbill:
            return {"vertical": "electricity", "family": "E02-A", "confidence": 0.91}
        if maintenance and electricity and never:
            return {"vertical": "electricity", "family": "E04-A", "confidence": 0.94}
        if maintenance and switch and electricity:
            return {"vertical": "electricity", "family": "E04-B", "confidence": 0.95}
        if automotive and automotive_repair_failure:
            return {"vertical": "automotive", "family": "A01", "confidence": 0.96}
        if insurance and insurance_nonrenewal:
            return {"vertical": "insurance", "family": "S02", "confidence": 0.96}
        if insurance and insurance_nonpayment:
            return {"vertical": "insurance", "family": "S01", "confidence": 0.94}
        if rental and rental_deposit:
            return {"vertical": "rentals", "family": "R01", "confidence": 0.96}
        if banking and banking_fee:
            return {"vertical": "banking", "family": "B03", "confidence": 0.95}
        if authorized_direct_debit and not explicit_unauthorized_payment:
            return {"vertical": "banking", "family": "B02", "confidence": 0.96}
        if banking and unauthorized_payment:
            return {"vertical": "banking", "family": "B01", "confidence": 0.96}
        if travel and denied_boarding:
            return {"vertical": "travel", "family": "V03", "confidence": 0.96}
        if travel and flight_cancellation:
            return {"vertical": "travel", "family": "V01", "confidence": 0.96}
        if travel and flight_delay:
            return {"vertical": "travel", "family": "V02", "confidence": 0.95}
        if telecom and telecom_interruption:
            return {"vertical": "telecom", "family": "T01", "confidence": 0.95}
        if telecom and contract_change:
            return {"vertical": "telecom", "family": "T02", "confidence": 0.94}
        if purchase and non_delivery:
            return {"vertical": "purchases", "family": "C04", "confidence": 0.94}
        if purchase and distance and withdrawal:
            return {"vertical": "purchases", "family": "C05", "confidence": 0.93}
        if purchase and repair_followup:
            return {"vertical": "purchases", "family": "C02", "confidence": 0.94}
        if purchase and mismatch:
            return {"vertical": "purchases", "family": "C03", "confidence": 0.94}
        if purchase and conformity:
            return {"vertical": "purchases", "family": "C01", "confidence": 0.90}
        return {"vertical": None, "family": None, "confidence": 0.2}

    def extract(self, text: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        amounts = re.findall(r"(?<!\d)(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:€|euros?)", text, flags=re.I)
        if amounts:
            out["mentioned_amounts"] = [float(x.replace(",", ".")) for x in amounts]
        return out

    def analyze_response(self, text: str) -> dict[str, Any]:
        t = _normalized(text)
        # Mixed concessions must be classified before broad acceptance keywords. This is
        # deliberately conservative: "aceptamos una parte" or "devolvemos una parte"
        # cannot close the whole expediente as if every requested remedy had been accepted.
        negated = bool(_NEGATED_ACCEPTANCE.search(t))
        rejected = bool(_EXPLICIT_REJECTION.search(t))
        refused_remedy = bool(_REMEDY_REFUSAL.search(t))
        affirmative_text = _NEGATED_ACCEPTANCE.sub(" ", t)
        if any(x in affirmative_text for x in [
            "aceptamos una parte", "aceptamos parte", "aceptamos parcialmente",
            "devolvemos una parte", "devolvemos parte", "estimamos parcialmente",
        ]):
            return {"type": "PARTIAL", "arguments": []}
        # A substring match on a promise is unsafe in a negated sentence. Strip
        # the negated spans before looking for a genuine affirmative promise;
        # contradictory responses require a human instead of a favorable state.
        affirmative = any(x in affirmative_text for x in _ACCEPTANCE_PHRASES)
        if (negated or rejected or refused_remedy) and affirmative:
            return {"type": "UNKNOWN", "arguments": []}
        if affirmative:
            return {"type": "ACCEPTANCE", "arguments": []}
        if "independiente" in t and any(x in t for x in ["contrato", "servicio", "mantenimiento"]):
            return {"type": "DENIAL", "arguments": ["INDEPENDENT_ADDON_CONTRACT"]}
        if any(x in t for x in ["solicito mantener", "pidio mantener"]):
            return {"type": "DENIAL", "arguments": ["EXPRESS_KEEP_REQUEST"]}
        if any(x in t for x in ["consta su consentimiento", "acepto el servicio", "consentimiento expreso", "acepto el cambio", "grabacion de consentimiento"]):
            return {"type": "DENIAL", "arguments": ["CONSENT_EVIDENCE"]}
        if any(x in t for x in ["el cups es correcto", "cups correcto", "corresponde a su cups", "cups coincide"]):
            return {"type": "DENIAL", "arguments": ["CUPS_CORRECT_ASSERTED"]}
        if any(x in t for x in ["el precio coincide con el contrato", "precio coincide con contrato", "tarifa coincide con contrato", "descuento aplicado correctamente", "promocion aplicada correctamente"]):
            return {"type": "DENIAL", "arguments": ["PRICING_MATCHES_CONTRACT_ASSERTED"]}
        if any(x in t for x in ["la estimacion era procedente", "estimacion permitida", "no fue posible acceder al contador", "no pudimos acceder al contador"]):
            return {"type": "DENIAL", "arguments": ["ESTIMATE_ALLOWED_ASSERTED"]}
        if any(x in t for x in ["se aviso con un mes", "avisamos con un mes", "notificado con un mes", "preaviso de un mes"]):
            return {"type": "DENIAL", "arguments": ["NOTICE_COMPLIANT_ASSERTED"]}
        if any(x in t for x in ["revision prevista en el contrato", "formula prevista en el contrato", "clausula de revision"]):
            return {"type": "DENIAL", "arguments": ["CONTRACTUAL_PRICE_FORMULA_ASSERTED"]}
        if any(x in t for x in ["importe correcto", "facturacion correcta"]):
            return {"type": "DENIAL", "arguments": ["CORRECT_AMOUNT_DISPUTED"]}
        if any(x in t for x in ["cargos distintos", "facturas distintas", "recibos distintos"]):
            return {"type": "DENIAL", "arguments": ["DIFFERENT_DEBTS"]}
        if any(x in t for x in ["contrato a precio fijo", "precio fijo"]) and any(x in t for x in ["primer ano", "primera anualidad", "primera prorroga", "antes de la renovacion"]):
            return {"type": "DENIAL", "arguments": ["FIXED_PRICE_FIRST_YEAR_ASSERTED"]}
        if any(x in t for x in ["mal uso", "golpe", "humedad", "dano accidental", "manipulacion"]):
            return {"type": "DENIAL", "arguments": ["MISUSE_OR_ACCIDENTAL_DAMAGE"]}
        if any(x in t for x in ["fuera de garantia", "garantia vencida"]):
            return {"type": "DENIAL", "arguments": ["OUTSIDE_LEGAL_GUARANTEE"]}
        if any(x in t for x in ["contacte con el fabricante", "dirijase al fabricante", "hable con el fabricante"]):
            return {"type": "DENIAL", "arguments": ["REFER_TO_MANUFACTURER"]}
        if any(x in t for x in ["coincide con lo pedido", "coincide con el pedido", "corresponde con lo comprado", "producto correcto", "articulo correcto"]):
            return {"type": "DENIAL", "arguments": ["GOODS_MATCH_CONTRACT_ASSERTED"]}
        if any(x in t for x in ["consta como entregado", "pedido entregado", "entrega realizada", "figura entregado"]):
            return {"type": "DENIAL", "arguments": ["DELIVERY_PROOF_ASSERTED"]}
        if any(x in t for x in [
            "vehiculo manipulado por otro taller", "vehiculo fue manipulado por otro taller",
            "fue manipulado por otro taller", "manipulado por un tercero",
            "reparado por otro taller despues", "intervencion de otro taller",
        ]):
            return {"type": "DENIAL", "arguments": ["AUTOMOTIVE_THIRD_PARTY_MANIPULATION_ASSERTED"]}
        if any(x in t for x in [
            "oposicion fuera de plazo", "comunicacion fuera de plazo",
            "comunicacion de no renovacion fuera de plazo",
            "comunicacion de no renovacion esta fuera de plazo",
            "aviso de no renovacion fuera de plazo", "aviso de no renovacion esta fuera de plazo",
            "no renovacion fuera de plazo", "no renovacion esta fuera de plazo",
            "no se comunico con un mes de antelacion",
        ]):
            return {"type": "DENIAL", "arguments": ["INSURANCE_NONRENEWAL_LATE_ASSERTED"]}
        if any(x in t for x in [
            "importe minimo ya pagado", "cantidad minima ya pagada",
            "ya abonamos el importe minimo", "minimo ya abonado",
        ]):
            return {"type": "DENIAL", "arguments": ["INSURANCE_MINIMUM_PAYMENT_PAID_ASSERTED"]}
        if any(x in t for x in [
            "deduccion de la fianza", "deducimos de la fianza", "descontamos de la fianza",
            "danos en la vivienda", "danos en el inmueble", "rentas pendientes",
            "suministros pendientes", "deudas pendientes del alquiler",
        ]):
            return {"type": "DENIAL", "arguments": ["RENT_DEPOSIT_DEDUCTIONS_ASSERTED"]}
        if (
            any(x in t for x in ["servicio solicitado", "servicio fue solicitado", "servicio aceptado"])
            and any(x in t for x in ["servicio prestado", "efectivamente prestado", "gasto habido", "gasto incurrido"])
        ):
            return {"type": "DENIAL", "arguments": ["BANK_FEE_REQUESTED_AND_PROVIDED_ASSERTED"]}
        if (
            any(x in t for x in ["consentimiento", "consentido", "consintio", "autorizo directamente"])
            and any(x in t for x in ["cuatro semanas", "4 semanas", "aviso previo"])
        ):
            return {"type": "DENIAL", "arguments": ["ARTICLE_48_4_EXCEPTION_ASSERTED"]}
        if any(x in t for x in ["la operacion fue autenticada", "operacion autenticada correctamente", "pago autenticado correctamente"]):
            return {"type": "DENIAL", "arguments": ["PAYMENT_AUTHENTICATED_ASSERTED"]}
        if any(x in t for x in ["compensacion por denegacion ya pagada", "compensacion por denegacion ya fue pagada", "ya pagamos la compensacion por denegacion", "compensacion por overbooking abonada"]):
            return {"type": "DENIAL", "arguments": ["DENIED_BOARDING_COMPENSATION_PAID_ASSERTED"]}
        if any(x in t for x in ["reembolso ya realizado", "billete ya reembolsado", "ya hemos reembolsado el billete", "reembolso abonado"]):
            return {"type": "DENIAL", "arguments": ["FLIGHT_REFUND_ALREADY_PAID_ASSERTED"]}
        if any(x in t for x in ["compensacion ya aplicada", "ya aplicamos la compensacion", "compensacion abonada"]):
            return {"type": "DENIAL", "arguments": ["INTERNET_INTERRUPTION_COMPENSATION_APPLIED_ASSERTED"]}
        if any(x in t for x in ["desistimiento fuera de plazo", "fuera del plazo de desistimiento", "plazo para desistir vencido"]):
            return {"type": "DENIAL", "arguments": ["WITHDRAWAL_LATE_ASSERTED"]}
        if any(x in t for x in ["excluido del desistimiento", "no admite desistimiento", "producto personalizado", "por razones de higiene"]):
            return {"type": "DENIAL", "arguments": ["WITHDRAWAL_EXCEPTION_ASSERTED"]}
        if negated or rejected or refused_remedy:
            return {"type": "DENIAL", "arguments": []}
        return {"type": "UNKNOWN", "arguments": []}
