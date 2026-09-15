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
    """No LLM. Lets us validate the product/rules pipeline before adding a provider."""

    def classify(self, text: str) -> dict[str, Any]:
        t = text.lower()
        maintenance = any(w in t for w in ["mantenimiento", "servicio", "protección", "proteccion"])
        switch = any(w in t for w in ["cambié", "cambie", "cambiar", "cambio", "baja", "me fui", "otra compañía", "otra compania"])
        electricity = any(w in t for w in ["luz", "electric", "comercializadora", "endesa", "iberdrola", "naturgy", "repsol"])
        never = any(w in t for w in ["nunca contrat", "no contraté", "no contrate"])
        if maintenance and electricity and never:
            return {"vertical": "electricity", "family": "E04-A", "confidence": 0.91}
        if maintenance and switch and electricity:
            return {"vertical": "electricity", "family": "E04-B", "confidence": 0.95}
        return {"vertical": None, "family": None, "confidence": 0.2}

    def extract(self, text: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        amounts = re.findall(r"(?<!\d)(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:€|euros?)", text, flags=re.I)
        if amounts:
            out["mentioned_amounts"] = [float(x.replace(",", ".")) for x in amounts]
        return out

    def analyze_response(self, text: str) -> dict[str, Any]:
        t = text.lower()
        if any(x in t for x in ["aceptamos", "estimamos su reclamación", "estimamos la reclamacion", "devolveremos", "procedemos a devolver"]):
            return {"type": "ACCEPTANCE", "arguments": []}
        if "independiente" in t and any(x in t for x in ["contrato", "servicio", "mantenimiento"]):
            return {"type": "DENIAL", "arguments": ["INDEPENDENT_ADDON_CONTRACT"]}
        if any(x in t for x in ["solicitó mantener", "solicito mantener", "pidió mantener", "pidio mantener"]):
            return {"type": "DENIAL", "arguments": ["EXPRESS_KEEP_REQUEST"]}
        if any(x in t for x in ["parcial", "parte del importe", "devolvemos una"]):
            return {"type": "PARTIAL", "arguments": []}
        return {"type": "UNKNOWN", "arguments": []}
