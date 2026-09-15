from __future__ import annotations
from .e04b import FactValue


def next_question(facts: dict[str, FactValue], family: str | None) -> dict:
    if family != "E04-B":
        return {"done": True, "question": None, "field": None, "message": "Este alpha solo implementa E04-B de extremo a extremo."}
    order = [
        ("electricity.supply_end_date", "¿Cuál fue la fecha efectiva aproximada en que terminó el suministro con la antigua comercializadora?", "date"),
        ("electricity.addon.identity", "¿Cómo aparece llamado el mantenimiento o servicio adicional?", "text"),
        ("electricity.addon.ever_contracted", "¿Reconoces haber contratado alguna vez ese mantenimiento?", "boolean"),
        ("electricity.addon.contracted_with_supply", "¿Ese mantenimiento se contrató junto con la tarifa eléctrica?", "boolean"),
        ("electricity.addon.keep_requested", "¿Pediste expresamente conservar el mantenimiento después del cambio?", "boolean"),
        ("electricity.addon.charges", "Añade los cargos indicando importe y período al que corresponde cada uno.", "charges"),
    ]
    for key, q, typ in order:
        if key not in facts:
            return {"done": False, "question": q, "field": key, "input_type": typ}
    return {"done": True, "question": None, "field": None}
