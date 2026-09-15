from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol


class ModelGateway(Protocol):
    def classify(self, text: str) -> dict[str, Any]: ...
    def extract(self, text: str) -> dict[str, Any]: ...
    def analyze_response(self, text: str) -> dict[str, Any]: ...


@dataclass
class DeterministicAlphaGateway:
    """No LLM. Validates routing/rules/workflow before a model provider is added."""

    def classify(self, text: str) -> dict[str, Any]:
        t = text.lower()
        electricity = any(w in t for w in ["luz", "electric", "comercializadora", "endesa", "iberdrola", "naturgy", "repsol", "factura eléctrica", "factura electrica", "cups"])
        maintenance = any(w in t for w in ["mantenimiento", "servicio", "protección", "proteccion", "asistencia"])
        switch = any(w in t for w in ["cambié", "cambie", "cambiar", "cambio", "baja", "me fui", "otra compañía", "otra compania"])
        never = any(w in t for w in ["nunca contrat", "no contraté", "no contrate", "sin contratar", "no lo pedí", "no lo pedi"])
        duplicate = any(w in t for w in ["dos veces", "duplicado", "duplicada", "doble cargo", "doble cobro", "me lo han cobrado dos"])
        overbill = any(w in t for w in ["cobrado de más", "cobrado de mas", "facturado de más", "facturado de mas", "factura incorrecta", "importe incorrecto", "me cobran más", "me cobran mas"])
        unauthorized_switch = any(w in t for w in [
            "me cambiaron de compañía", "me cambiaron de compania", "me han cambiado de compañía", "me han cambiado de compania",
            "cambio sin permiso", "cambio sin mi permiso", "sin consentimiento", "no autoricé el cambio", "no autorice el cambio",
            "no acepté cambiar", "no acepte cambiar", "comercializadora que no contraté", "comercializadora que no contrate",
            "cups incorrecto", "cups equivocado", "cambio de comercializadora no solicitado",
        ])
        termination_penalty = any(w in t for w in [
            "penalización", "penalizacion", "permanencia", "penalidad", "rescisión", "rescision",
            "cancelación anticipada", "cancelacion anticipada", "por darme de baja", "por irme de la compañía", "por irme de la compania",
            "me cobran por cambiarme", "cargo por cancelar", "cargo por baja",
        ])
        purchase = any(w in t for w in ["compré", "compre", "comprado", "compra", "tienda", "vendedor", "producto", "pedido", "televisor", "tv", "móvil", "movil", "teléfono", "telefono", "ordenador", "portátil", "portatil", "lavadora", "nevera", "electrodoméstico", "electrodomestico"])
        conformity = any(w in t for w in ["garantía", "garantia", "defecto", "defectuoso", "avería", "averia", "averiado", "roto", "no funciona", "dejó de funcionar", "dejo de funcionar", "rechazan la garantía", "rechazan la garantia"])
        repair_followup = any(w in t for w in [
            "ya lo repararon", "ya la repararon", "después de reparar", "despues de reparar", "tras la reparación", "tras la reparacion",
            "volvió a fallar", "volvio a fallar", "sigue fallando", "otra vez falla", "segunda reparación", "segunda reparacion",
            "lleva en reparación", "lleva en reparacion", "sigue en reparación", "sigue en reparacion", "reparación fallida", "reparacion fallida",
        ])
        mismatch = any(w in t for w in [
            "producto equivocado", "me enviaron otro", "me mandaron otro", "no corresponde con lo comprado", "no coincide con lo comprado",
            "distinto a lo anunciado", "distinto de lo anunciado", "no es como se anunciaba", "no es lo que pedí", "no es lo que pedi",
            "incompleto", "faltan piezas", "faltan accesorios", "falta una pieza", "cantidad incorrecta", "vino otro modelo",
        ])
        non_delivery = any(w in t for w in [
            "no ha llegado", "no me ha llegado", "no nos ha llegado", "no llegó", "no llego", "no llega",
            "no recibido", "no he recibido", "no lo he recibido", "no la he recibido", "no hemos recibido",
            "no lo recibí", "no lo recibi", "no me entregan", "no me lo entregan", "no entregado", "sin entregar",
            "pedido perdido", "pedido no entregado", "sigue sin llegar", "sigue sin entregar",
        ])
        distance = any(w in t for w in ["online", "internet", "web", "a distancia", "por teléfono", "por telefono", "pedido"])
        withdrawal = any(w in t for w in ["desist", "quiero devolver", "quiero devolverlo", "me arrepentí", "me arrepenti", "devolver la compra", "derecho de devolución", "derecho de devolucion", "14 días", "14 dias"])

        if electricity and unauthorized_switch:
            return {"vertical": "electricity", "family": "E03", "confidence": 0.96}
        if electricity and termination_penalty:
            return {"vertical": "electricity", "family": "E05", "confidence": 0.94}
        if electricity and duplicate:
            return {"vertical": "electricity", "family": "E02-B", "confidence": 0.96}
        if electricity and overbill:
            return {"vertical": "electricity", "family": "E02-A", "confidence": 0.91}
        if maintenance and electricity and never:
            return {"vertical": "electricity", "family": "E04-A", "confidence": 0.94}
        if maintenance and switch and electricity:
            return {"vertical": "electricity", "family": "E04-B", "confidence": 0.95}
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
        t = text.lower()
        if any(x in t for x in ["aceptamos", "estimamos su reclamación", "estimamos la reclamacion", "devolveremos", "procedemos a devolver", "procedemos a reparar", "procedemos a sustituir", "restableceremos su contrato anterior"]):
            return {"type": "ACCEPTANCE", "arguments": []}
        if "independiente" in t and any(x in t for x in ["contrato", "servicio", "mantenimiento"]):
            return {"type": "DENIAL", "arguments": ["INDEPENDENT_ADDON_CONTRACT"]}
        if any(x in t for x in ["solicitó mantener", "solicito mantener", "pidió mantener", "pidio mantener"]):
            return {"type": "DENIAL", "arguments": ["EXPRESS_KEEP_REQUEST"]}
        if any(x in t for x in ["consta su consentimiento", "aceptó el servicio", "acepto el servicio", "consentimiento expreso", "aceptó el cambio", "acepto el cambio", "grabación de consentimiento", "grabacion de consentimiento"]):
            return {"type": "DENIAL", "arguments": ["CONSENT_EVIDENCE"]}
        if any(x in t for x in ["el cups es correcto", "cups correcto", "corresponde a su cups", "cups coincide"]):
            return {"type": "DENIAL", "arguments": ["CUPS_CORRECT_ASSERTED"]}
        if any(x in t for x in ["precio fijo", "antes de la primera prórroga", "antes de la primera prorroga", "pérdida económica", "perdida economica", "5% de la energía", "5% de la energia"]):
            return {"type": "DENIAL", "arguments": ["EARLY_TERMINATION_EXCEPTION_ASSERTED"]}
        if any(x in t for x in ["importe correcto", "facturación correcta", "facturacion correcta"]):
            return {"type": "DENIAL", "arguments": ["CORRECT_AMOUNT_DISPUTED"]}
        if any(x in t for x in ["cargos distintos", "facturas distintas", "recibos distintos"]):
            return {"type": "DENIAL", "arguments": ["DIFFERENT_DEBTS"]}
        if any(x in t for x in ["mal uso", "golpe", "humedad", "daño accidental", "dano accidental", "manipulación", "manipulacion"]):
            return {"type": "DENIAL", "arguments": ["MISUSE_OR_ACCIDENTAL_DAMAGE"]}
        if any(x in t for x in ["fuera de garantía", "fuera de garantia", "garantía vencida", "garantia vencida"]):
            return {"type": "DENIAL", "arguments": ["OUTSIDE_LEGAL_GUARANTEE"]}
        if any(x in t for x in ["contacte con el fabricante", "diríjase al fabricante", "dirijase al fabricante", "hable con el fabricante"]):
            return {"type": "DENIAL", "arguments": ["REFER_TO_MANUFACTURER"]}
        if any(x in t for x in ["coincide con lo pedido", "coincide con el pedido", "corresponde con lo comprado", "producto correcto", "artículo correcto", "articulo correcto"]):
            return {"type": "DENIAL", "arguments": ["GOODS_MATCH_CONTRACT_ASSERTED"]}
        if any(x in t for x in ["consta como entregado", "pedido entregado", "entrega realizada", "figura entregado"]):
            return {"type": "DENIAL", "arguments": ["DELIVERY_PROOF_ASSERTED"]}
        if any(x in t for x in ["desistimiento fuera de plazo", "fuera del plazo de desistimiento", "plazo para desistir vencido"]):
            return {"type": "DENIAL", "arguments": ["WITHDRAWAL_LATE_ASSERTED"]}
        if any(x in t for x in ["excluido del desistimiento", "no admite desistimiento", "producto personalizado", "por razones de higiene"]):
            return {"type": "DENIAL", "arguments": ["WITHDRAWAL_EXCEPTION_ASSERTED"]}
        if any(x in t for x in ["parcial", "parte del importe", "devolvemos una"]):
            return {"type": "PARTIAL", "arguments": []}
        return {"type": "UNKNOWN", "arguments": []}
