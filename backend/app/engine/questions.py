from __future__ import annotations
from .common import FactValue


def next_question(facts: dict[str, FactValue], family: str | None) -> dict:
    orders = {
        "E04-B": [
            ("electricity.supply_end_date", "¿Cuál fue la fecha efectiva aproximada en que terminó el suministro con la antigua comercializadora?", "date"),
            ("electricity.addon.identity", "¿Cómo aparece llamado el mantenimiento o servicio adicional?", "text"),
            ("electricity.addon.ever_contracted", "¿Reconoces haber contratado alguna vez ese mantenimiento?", "boolean"),
            ("electricity.addon.contracted_with_supply", "¿Ese mantenimiento se contrató junto con la tarifa eléctrica?", "boolean"),
            ("electricity.addon.keep_requested", "¿Pediste expresamente conservar el mantenimiento después del cambio?", "boolean"),
            ("electricity.addon.charges", "Añade los cargos indicando importe y período al que corresponde cada uno.", "charges"),
        ],
        "E04-A": [
            ("electricity.addon.identity", "¿Cómo aparece llamado el servicio que dices no haber contratado?", "text"),
            ("electricity.addon.ever_contracted", "¿Estás diciendo que nunca aceptaste contratar ese servicio?", "boolean"),
            ("electricity.addon.charges", "Añade los cargos de ese servicio que puedas acreditar.", "charges"),
        ],
        "E02-A": [
            ("electricity.billing.invoice_date", "¿De qué fecha es la factura que consideras incorrecta?", "date"),
            ("electricity.billing.billed_amount", "¿Qué importe te facturaron?", "money"),
            ("electricity.billing.correct_amount", "¿Qué importe debería haberse facturado según los datos que tienes?", "money"),
        ],
        "E02-B": [
            ("electricity.billing.same_debt", "¿Los dos cargos corresponden a la misma factura o deuda?", "boolean"),
            ("electricity.billing.duplicate_charges", "Añade los dos cargos que consideras duplicados.", "charges"),
        ],
    }
    order = orders.get(family)
    if not order:
        return {"done": True, "question": None, "field": None, "message": "Este caso todavía no está automatizado en la alpha."}
    for key, q, typ in order:
        if key not in facts:
            return {"done": False, "question": q, "field": key, "input_type": typ}
    return {"done": True, "question": None, "field": None}
