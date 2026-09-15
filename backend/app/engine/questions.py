from __future__ import annotations

from datetime import date, timedelta

from .common import FactValue


def _value(facts: dict[str, FactValue], key: str, default=None):
    return facts[key].value if key in facts else default


def _ask(key: str, question: str, input_type: str) -> dict:
    return {"done": False, "question": question, "field": key, "input_type": input_type}


def _date(value):
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _c04_question(facts: dict[str, FactValue]) -> dict:
    common = [
        ("purchase.buyer_is_consumer", "¿Hiciste el pedido como particular, no para una actividad profesional o empresa?", "boolean"),
        ("purchase.seller_is_business", "¿Compraste a una tienda, empresa o vendedor profesional?", "boolean"),
        ("purchase.product_name", "¿Qué producto o pedido no has recibido?", "text"),
        ("purchase.order_date", "¿Qué día hiciste el pedido?", "date"),
        ("purchase.amount_paid", "¿Cuánto pagaste por el pedido?", "money"),
        ("purchase.delivered", "¿El pedido ha llegado finalmente?", "boolean"),
        ("purchase.delivery_date_was_agreed", "¿El vendedor acordó contigo una fecha concreta de entrega?", "boolean"),
    ]
    for key, question, input_type in common:
        if key not in facts:
            return _ask(key, question, input_type)

    if _value(facts, "purchase.delivered") is True:
        return {"done": True, "question": None, "field": None}

    if _value(facts, "purchase.delivery_date_was_agreed") is True and "purchase.agreed_delivery_date" not in facts:
        return _ask("purchase.agreed_delivery_date", "¿Cuál era la fecha de entrega acordada?", "date")

    for key, question in [
        ("purchase.seller_refused_delivery", "¿El vendedor te ha dicho claramente que no va a entregar el pedido?"),
        ("purchase.delivery_date_essential", "¿Era esencial recibirlo en esa fecha concreta y eso se dejó claro al comprar?"),
    ]:
        if key not in facts:
            return _ask(key, question, "boolean")

    order_date = _date(_value(facts, "purchase.order_date"))
    agreed_date = _date(_value(facts, "purchase.agreed_delivery_date"))
    due_date = agreed_date if _value(facts, "purchase.delivery_date_was_agreed") and agreed_date else (order_date + timedelta(days=30) if order_date else None)
    immediate = _value(facts, "purchase.seller_refused_delivery") is True or (
        _value(facts, "purchase.delivery_date_essential") is True and due_date and date.today() > due_date
    )

    if due_date and date.today() > due_date and not immediate:
        if "purchase.additional_delivery_period_requested" not in facts:
            return _ask(
                "purchase.additional_delivery_period_requested",
                "Después de vencer la entrega, ¿diste al vendedor un plazo adicional para que cumpliera?",
                "boolean",
            )
        if _value(facts, "purchase.additional_delivery_period_requested") is True and "purchase.additional_delivery_period_deadline" not in facts:
            return _ask(
                "purchase.additional_delivery_period_deadline",
                "¿Hasta qué fecha le diste ese plazo adicional?",
                "date",
            )
    return {"done": True, "question": None, "field": None}


def _c05_question(facts: dict[str, FactValue]) -> dict:
    common = [
        ("purchase.buyer_is_consumer", "¿Compraste como particular, no para una actividad profesional o empresa?", "boolean"),
        ("purchase.seller_is_business", "¿Compraste a una tienda, empresa o vendedor profesional?", "boolean"),
        ("purchase.distance_contract", "¿La compra se hizo por internet, teléfono u otro medio a distancia?", "boolean"),
        ("purchase.product_name", "¿Qué producto quieres devolver?", "text"),
        ("purchase.received_date", "¿Qué día recibiste el producto?", "date"),
        ("purchase.amount_paid", "¿Cuánto pagaste en total por la compra?", "money"),
        ("purchase.premium_delivery_extra", "Si elegiste un envío más caro que el ordinario, ¿cuánto fue ese extra? Si no, indica 0.", "money"),
        ("purchase.withdrawal_exception_possible", "¿Es un producto personalizado, perecedero, precintado por higiene ya abierto u otro producto con condiciones especiales de devolución?", "boolean"),
        ("purchase.withdrawal_information_provided", "¿El vendedor te informó del derecho y plazo de desistimiento?", "boolean"),
    ]
    for key, question, input_type in common:
        if key not in facts:
            return _ask(key, question, input_type)

    if _value(facts, "purchase.withdrawal_exception_possible") is True:
        return {"done": True, "question": None, "field": None}

    if _value(facts, "purchase.withdrawal_information_provided") is False and "purchase.withdrawal_information_later_date" not in facts:
        return _ask(
            "purchase.withdrawal_information_later_date",
            "Si te informaron del desistimiento más tarde, indica la fecha. Si nunca te informaron, puedes marcar «No lo sé/no ocurrió».",
            "date_optional",
        )

    if "purchase.withdrawal_sent" not in facts:
        return _ask("purchase.withdrawal_sent", "¿Ya comunicaste al vendedor de forma clara que querías desistir/devolver la compra?", "boolean")
    if _value(facts, "purchase.withdrawal_sent") is True and "purchase.withdrawal_sent_date" not in facts:
        return _ask("purchase.withdrawal_sent_date", "¿Qué día enviaste esa comunicación?", "date")
    if _value(facts, "purchase.withdrawal_sent") is False:
        return {"done": True, "question": None, "field": None}

    if "purchase.refund_received" not in facts:
        return _ask("purchase.refund_received", "¿Ya has recibido el reembolso completo?", "boolean")
    if _value(facts, "purchase.refund_received") is True and "purchase.refund_received_amount" not in facts:
        return _ask("purchase.refund_received_amount", "¿Qué importe te han reembolsado?", "money")

    if _value(facts, "purchase.refund_received") is not True:
        if "purchase.seller_offered_collection" not in facts:
            return _ask("purchase.seller_offered_collection", "¿El vendedor se ofreció a recoger él mismo el producto?", "boolean")
        if _value(facts, "purchase.seller_offered_collection") is False:
            if "purchase.return_sent" not in facts:
                return _ask("purchase.return_sent", "¿Ya devolviste o enviaste de vuelta el producto?", "boolean")
            if _value(facts, "purchase.return_sent") is True and "purchase.return_proof_available" not in facts:
                return _ask("purchase.return_proof_available", "¿Tienes justificante o seguimiento que pruebe la devolución?", "boolean")
    return {"done": True, "question": None, "field": None}


def next_question(facts: dict[str, FactValue], family: str | None) -> dict:
    if family == "C04":
        return _c04_question(facts)
    if family == "C05":
        return _c05_question(facts)

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
            return _ask(key, question, input_type)
    return {"done": True, "question": None, "field": None}
