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
        electricity = any(w in t for w in ["luz", "electric", "comercializadora", "endesa", "iberdrola", "naturgy", "repsol", "factura eléctrica", "factura electrica"])
        maintenance = any(w in t for w in ["mantenimiento", "servicio", "protección", "proteccion", "asistencia"])
        switch = any(w in t for w in ["cambié", "cambie", "cambiar", "cambio", "baja", "me fui", "otra compañía", "otra compania"])
        never = any(w in t for w in ["nunca contrat", "no contraté", "no contrate", "sin contratar", "no lo pedí", "no lo pedi"])
        duplicate = any(w in t for w in ["dos veces", "duplicado", "duplicada", "doble cargo", "doble cobro", "me lo han cobrado dos"])
        overbill = any(w in t for w in ["cobrado de más", "cobrado de mas", "facturado de más", "facturado de mas", "factura incorrecta", "importe incorrecto", "me cobran más", "me cobran mas"])
        purchase = any(w in t for w in ["compré", "compre", "comprado", "compra", "tienda", "vendedor", "producto", "pedido", "televisor", "tv", "móvil", "movil", "teléfono", "telefono", "ordenador", "portátil", "portatil", "lavadora", "nevera", "electrodoméstico", "electrodomestico"])
        conformity = any(w in t for w in ["garantía", "garantia", "defecto", "defectuoso", "avería", "averia", "averiado", "roto", "no funciona", "dejó de funcionar", "dejo de funcionar", "rechazan la garantía", "rechazan la garantia"])

        if electricity and duplicate:
            return {"vertical": "electricity", "family": "E02-B", "confidence": 0.96}
        if electricity and overbill:
            return {"vertical": "electricity", "family": "E02-A", "confidence": 0.91}
        if maintenance and electricity and never:
            return {"vertical": "electricity", "family": "E04-A", "confidence": 0.94}
        if maintenance and switch and electricity:
            return {"vertical": "electricity", "family": "E04-B", "confidence": 0.95}
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
        if any(x in t for x in ["aceptamos", "estimamos su reclamación", "estimamos la reclamacion", "devolveremos", "procedemos a devolver", "procedemos a reparar", "procedemos a sustituir"]):
            return {"type": "ACCEPTANCE", "arguments": []}
        if "independiente" in t and any(x in t for x in ["contrato", "servicio", "mantenimiento"]):
            return {"type": "DENIAL", "arguments": ["INDEPENDENT_ADDON_CONTRACT"]}
        if any(x in t for x in ["solicitó mantener", "solicito mantener", "pidió mantener", "pidio mantener"]):
            return {"type": "DENIAL", "arguments": ["EXPRESS_KEEP_REQUEST"]}
        if any(x in t for x in ["consta su consentimiento", "aceptó el servicio", "acepto el servicio", "consentimiento expreso"]):
            return {"type": "DENIAL", "arguments": ["CONSENT_EVIDENCE"]}
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
        if any(x in t for x in ["parcial", "parte del importe", "devolvemos una"]):
            return {"type": "PARTIAL", "arguments": []}
        return {"type": "UNKNOWN", "arguments": []}
