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
        "C01": [
            ("purchase.buyer_is_consumer", "¿Compraste el producto como particular, no para una actividad profesional o empresa?", "boolean"),
            ("purchase.seller_is_business", "¿Lo compraste a una tienda, empresa o vendedor profesional?", "boolean"),
            ("purchase.second_hand", "¿El producto era de segunda mano?", "boolean"),
            ("purchase.product_name", "¿Qué producto es?", "text"),
            ("purchase.delivery_date", "¿Qué día te entregaron el producto?", "date"),
            ("purchase.defect_manifested_date", "¿Cuándo apareció el defecto o dejó de funcionar correctamente?", "date"),
            ("purchase.defect_description", "Describe brevemente qué falla o por qué no es conforme.", "text"),
            ("purchase.accidental_damage_or_misuse", "¿Hubo algún golpe, humedad, manipulación o mal uso que pueda explicar el defecto?", "boolean"),
            ("purchase.price", "¿Cuánto pagaste por el producto?", "money"),
            ("purchase.seller_denied_conformity", "¿El vendedor ya se ha negado a reparar o sustituir el producto?", "boolean"),
        ],
    }
    order = orders.get(family)
    if not order:
        return {"done": True, "question": None, "field": None, "message": "Este caso todavía no está automatizado en la alpha."}
    for key, question, input_type in order:
        if key not in facts:
            return {"done": False, "question": question, "field": key, "input_type": input_type}
    return {"done": True, "question": None, "field": None}
