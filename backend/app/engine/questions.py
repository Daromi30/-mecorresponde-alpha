from __future__ import annotations

from datetime import date, timedelta

from ..calendar_clock import spain_today
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


def _c02_question(facts: dict[str, FactValue]) -> dict:
    common = [
        ("purchase.buyer_is_consumer", "¿Compraste el producto como particular, no para una actividad profesional o empresa?", "boolean"),
        ("purchase.seller_is_business", "¿Lo compraste a una tienda, empresa o vendedor profesional?", "boolean"),
        ("purchase.product_name", "¿Qué producto es?", "text"),
        ("purchase.delivery_date", "¿Qué día te entregaron el producto?", "date"),
        ("purchase.price", "¿Cuánto pagaste por el producto?", "money"),
        ("purchase.conformity_attempts", "¿Cuántos intentos de reparación o sustitución ha realizado ya el vendedor?", "integer"),
    ]
    for key, question, input_type in common:
        if key not in facts:
            return _ask(key, question, input_type)

    try:
        attempts = int(_value(facts, "purchase.conformity_attempts", 0) or 0)
    except (TypeError, ValueError):
        attempts = 0
    if attempts < 1:
        return {"done": True, "question": None, "field": None}

    if "purchase.lack_after_conformity_attempt" not in facts:
        return _ask(
            "purchase.lack_after_conformity_attempt",
            "Después del intento de reparación o sustitución, ¿el producto volvió a presentar una falta o sigue sin estar conforme?",
            "boolean",
        )

    lack_after = _value(facts, "purchase.lack_after_conformity_attempt")
    if lack_after is False and "purchase.repair_still_pending" not in facts:
        return _ask(
            "purchase.repair_still_pending",
            "¿La reparación o sustitución sigue todavía pendiente de terminar?",
            "boolean",
        )

    if "purchase.seller_declared_will_not_conform" not in facts:
        return _ask(
            "purchase.seller_declared_will_not_conform",
            "¿El vendedor te ha dicho claramente que no va a reparar, sustituir o terminar de poner el producto en conformidad?",
            "boolean",
        )

    pending = _value(facts, "purchase.repair_still_pending")
    refusal = _value(facts, "purchase.seller_declared_will_not_conform")
    if lack_after is False and pending is True:
        if "purchase.repair_started_date" not in facts:
            return _ask(
                "purchase.repair_started_date",
                "¿En qué fecha entregaste o pusiste el producto a disposición para esta reparación?",
                "date",
            )
        return {"done": True, "question": None, "field": None}

    if lack_after is True:
        if "purchase.same_origin_after_repair" not in facts:
            return _ask(
                "purchase.same_origin_after_repair",
                "¿El fallo que ha reaparecido parece ser el mismo o tener el mismo origen que el que se intentó reparar?",
                "boolean",
            )
        if _value(facts, "purchase.same_origin_after_repair") is True and "purchase.repair_return_date" not in facts:
            return _ask(
                "purchase.repair_return_date",
                "¿Qué día te devolvieron el producto después de aquella reparación o sustitución?",
                "date",
            )

    if (lack_after is True or refusal is True) and "purchase.preferred_secondary_remedy" not in facts:
        return _ask(
            "purchase.preferred_secondary_remedy",
            "Con el problema actual, ¿prefieres pedir la resolución de la compra, una reducción proporcional del precio o todavía no lo tienes decidido?",
            "choice:termination|price_reduction|undecided",
        )

    if _value(facts, "purchase.preferred_secondary_remedy") == "termination" and "purchase.defect_material" not in facts:
        return _ask(
            "purchase.defect_material",
            "¿El problema afecta de forma relevante al uso, funcionamiento o valor del producto, más allá de un detalle de escasa importancia?",
            "boolean",
        )
    return {"done": True, "question": None, "field": None}


def _c03_question(facts: dict[str, FactValue]) -> dict:
    common = [
        ("purchase.buyer_is_consumer", "¿Compraste como particular, no para una actividad profesional o empresa?", "boolean"),
        ("purchase.seller_is_business", "¿Compraste a una tienda, empresa o vendedor profesional?", "boolean"),
        ("purchase.product_name", "¿Qué producto compraste?", "text"),
        ("purchase.delivery_date", "¿Qué día recibiste el producto?", "date"),
        ("purchase.price", "¿Cuánto pagaste por el producto?", "money"),
        ("purchase.mismatch_confirmed", "¿Confirmas que lo recibido es distinto, incompleto o no coincide con lo contratado/anunciado?", "boolean"),
        ("purchase.contract_description", "Describe qué compraste o qué características/cantidad/accesorios estaban incluidos en el contrato o anuncio.", "text"),
        ("purchase.received_description", "Describe qué recibiste realmente y qué diferencia concreta existe.", "text"),
        ("purchase.seller_denied_conformity", "¿El vendedor ya se ha negado a corregir, completar o sustituir lo recibido?", "boolean"),
        ("purchase.mismatch_material", "¿La diferencia afecta de forma relevante al uso, cantidad, calidad o valor, y no es solo un detalle menor?", "boolean"),
    ]
    for key, question, input_type in common:
        if key not in facts:
            return _ask(key, question, input_type)
    return {"done": True, "question": None, "field": None}


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
    today = spain_today()
    immediate = _value(facts, "purchase.seller_refused_delivery") is True or (
        _value(facts, "purchase.delivery_date_essential") is True and due_date and today > due_date
    )

    if due_date and today > due_date and not immediate:
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



def _t01_question(facts: dict[str, FactValue]) -> dict:
    order = [
        ("telecom.subscriber_has_contract", "¿Eres titular o abonado del contrato del servicio de internet afectado?", "boolean"),
        ("telecom.service_kind", "¿La interrupción afectó a internet fijo/fibra o a internet móvil?", "choice:fixed_internet|mobile_internet"),
    ]
    for key, question, input_type in order:
        if key not in facts:
            return _ask(key, question, input_type)

    if _value(facts, "telecom.service_kind") != "fixed_internet":
        return {"done": True, "question": None, "field": None}

    if "telecom.service_restored" not in facts:
        return _ask("telecom.service_restored", "¿El servicio ya se ha restablecido?", "boolean")
    if _value(facts, "telecom.service_restored") is False:
        return {"done": True, "question": None, "field": None}

    fixed = [
        ("telecom.interruption_duration_hours", "¿Cuántas horas duró en total la interrupción?", "number"),
        ("telecom.affected_hours_8_22", "De esas horas, ¿cuántas transcurrieron entre las 8:00 y las 22:00?", "number"),
        ("telecom.interruption_due_to_serious_subscriber_breach", "¿La operadora atribuye el corte a un incumplimiento grave del contrato por tu parte?", "boolean"),
        ("telecom.interruption_due_to_nonconforming_terminal_damage", "¿La operadora atribuye el corte a daños de red causados por un equipo terminal tuyo no conforme?", "boolean"),
        ("telecom.internet_fee_identified", "¿La factura o contrato identifica cuánto de la cuota fija corresponde específicamente al acceso a internet?", "boolean"),
    ]
    for key, question, input_type in fixed:
        if key not in facts:
            return _ask(key, question, input_type)

    if _value(facts, "telecom.internet_fee_identified") is True:
        if "telecom.monthly_internet_fixed_fee" not in facts:
            return _ask("telecom.monthly_internet_fixed_fee", "¿Cuál es la cuota fija mensual identificada para internet?", "money")
    else:
        if "telecom.bundle_total_monthly_price" not in facts:
            return _ask("telecom.bundle_total_monthly_price", "¿Cuál es el precio fijo mensual total del paquete?", "money")
        if "telecom.operator_sells_services_separately" not in facts:
            return _ask(
                "telecom.operator_sells_services_separately",
                "¿La operadora comercializa por separado los servicios incluidos en ese paquete?",
                "boolean",
            )
        if _value(facts, "telecom.operator_sells_services_separately") is True:
            return {"done": True, "question": None, "field": None}

    if "telecom.billing_period_days" not in facts:
        return _ask("telecom.billing_period_days", "¿Cuántos días comprende el período de facturación de esa cuota?", "number")
    if "telecom.compensation_already_applied" not in facts:
        return _ask("telecom.compensation_already_applied", "¿La operadora ya aplicó alguna compensación por este corte?", "boolean")
    if _value(facts, "telecom.compensation_already_applied") is True and "telecom.compensation_received_amount" not in facts:
        return _ask("telecom.compensation_received_amount", "¿Qué importe de compensación te aplicó?", "money")
    return {"done": True, "question": None, "field": None}



def _t02_question(facts: dict[str, FactValue]) -> dict:
    if "telecom.final_user_contract" not in facts:
        return _ask(
            "telecom.final_user_contract",
            "¿Eres usuario final o titular del contrato de telecomunicaciones cuyas condiciones cambian?",
            "boolean",
        )
    if _value(facts, "telecom.final_user_contract") is False:
        return {"done": True, "question": None, "field": None}

    if "telecom.change_notice_received" not in facts:
        return _ask(
            "telecom.change_notice_received",
            "¿La operadora te comunicó el cambio de precio o condiciones?",
            "boolean",
        )
    if _value(facts, "telecom.change_notice_received") is False:
        return {"done": True, "question": None, "field": None}

    if "telecom.change_exception_type" not in facts:
        return _ask(
            "telecom.change_exception_type",
            "¿Qué tipo de cambio te comunicaron?",
            "choice:adverse_or_other|benefit_only|administrative_no_negative|legally_required|unknown",
        )
    if _value(facts, "telecom.change_exception_type") != "adverse_or_other":
        return {"done": True, "question": None, "field": None}

    order = [
        ("telecom.change_notice_date", "¿Qué día recibiste la comunicación del cambio?", "date"),
        ("telecom.change_effective_date", "¿Desde qué día indica la operadora que aplicará el cambio?", "date"),
        ("telecom.notice_informed_free_termination_right", "¿La comunicación te informó de que podías resolver el contrato sin coste adicional si no aceptabas el cambio?", "boolean"),
        ("telecom.notice_clear_and_durable", "¿Conservas la comunicación en un soporte duradero, por ejemplo email, PDF, carta o área descargable, y resulta clara?", "boolean"),
        ("telecom.contract_contains_valid_change_reason", "¿El contrato identifica un motivo concreto que permita a la operadora modificar unilateralmente esas condiciones?", "boolean_unknown"),
        ("telecom.user_wants_to_terminate", "¿Quieres resolver el contrato por este cambio en lugar de aceptarlo?", "boolean"),
    ]
    for key, question, input_type in order:
        if key not in facts:
            return _ask(key, question, input_type)

    if _value(facts, "telecom.user_wants_to_terminate") is True and "telecom.retains_subsidized_terminal" not in facts:
        return _ask(
            "telecom.retains_subsidized_terminal",
            "¿El contrato incluye un móvil, router u otro terminal subvencionado que quieras conservar al terminar el contrato?",
            "boolean",
        )
    return {"done": True, "question": None, "field": None}



def _v01_question(facts: dict[str, FactValue]) -> dict:
    order = [
        (
            "travel.flight_cancelled_by_operating_carrier",
            "¿La aerolínea canceló el vuelo que tenías reservado?",
            "boolean",
        ),
    ]
    for key, question, input_type in order:
        if key not in facts:
            return _ask(key, question, input_type)
    if _value(facts, "travel.flight_cancelled_by_operating_carrier") is False:
        return {"done": True, "question": None, "field": None}

    fixed = [
        ("travel.cancellation_notified_date", "¿Qué día te comunicaron la cancelación?", "date"),
        ("travel.departure_airport_in_eu", "¿El vuelo salía de un aeropuerto situado en un país de la Unión Europea?", "boolean"),
        ("travel.confirmed_reservation", "¿Tenías una reserva confirmada para ese vuelo?", "boolean"),
        (
            "travel.fare_status",
            "¿Cómo obtuviste el billete?",
            "choice:public_fare|frequent_flyer_program|nonpublic_free_or_reduced|unknown",
        ),
        ("travel.package_trip", "¿El vuelo formaba parte de un viaje combinado o paquete turístico?", "boolean"),
        (
            "travel.booking_scope",
            "¿La reserva y el precio que vas a indicar corresponden a un único vuelo, sin ida y vuelta ni otros tramos?",
            "choice:single_flight|multi_segment_or_round_trip",
        ),
        (
            "travel.passenger_choice",
            "Tras la cancelación, ¿qué opción quieres ejercer?",
            "choice:refund|rerouting_soonest|rerouting_later|unknown",
        ),
    ]
    for key, question, input_type in fixed:
        if key not in facts:
            return _ask(key, question, input_type)

    if _value(facts, "travel.passenger_choice") != "refund":
        return {"done": True, "question": None, "field": None}
    if _value(facts, "travel.departure_airport_in_eu") is False:
        return {"done": True, "question": None, "field": None}
    if _value(facts, "travel.confirmed_reservation") is False:
        return {"done": True, "question": None, "field": None}
    if _value(facts, "travel.package_trip") is True:
        return {"done": True, "question": None, "field": None}
    if _value(facts, "travel.booking_scope") != "single_flight":
        return {"done": True, "question": None, "field": None}
    if _value(facts, "travel.fare_status") not in {"public_fare", "frequent_flyer_program"}:
        return {"done": True, "question": None, "field": None}

    if "travel.documented_ticket_price" not in facts:
        return _ask(
            "travel.documented_ticket_price",
            "¿Qué precio del vuelo cancelado consta en tu billete o confirmación de reserva?",
            "money",
        )
    if "travel.refund_received" not in facts:
        return _ask("travel.refund_received", "¿La aerolínea ya te ha devuelto algún importe por ese vuelo?", "boolean")
    if _value(facts, "travel.refund_received") is True and "travel.refund_received_amount" not in facts:
        return _ask("travel.refund_received_amount", "¿Qué importe te ha reembolsado ya?", "money")
    return {"done": True, "question": None, "field": None}



def _v02_question(facts: dict[str, FactValue]) -> dict:
    if "travel.departure_delay_hours" not in facts:
        return _ask(
            "travel.departure_delay_hours",
            "¿Cuántas horas alcanzó el retraso respecto de la salida prevista?",
            "number",
        )
    delay = _value(facts, "travel.departure_delay_hours")
    try:
        if float(delay) < 5:
            return {"done": True, "question": None, "field": None}
    except (TypeError, ValueError):
        return {"done": True, "question": None, "field": None}

    fixed = [
        ("travel.departure_airport_in_eu", "¿El vuelo salía de un aeropuerto situado en un país de la Unión Europea?", "boolean"),
        ("travel.confirmed_reservation", "¿Tenías una reserva confirmada para ese vuelo?", "boolean"),
        (
            "travel.fare_status",
            "¿Cómo obtuviste el billete?",
            "choice:public_fare|frequent_flyer_program|nonpublic_free_or_reduced|unknown",
        ),
        ("travel.package_trip", "¿El vuelo formaba parte de un viaje combinado o paquete turístico?", "boolean"),
        (
            "travel.booking_scope",
            "¿La reserva y el precio corresponden a un único vuelo, sin ida y vuelta ni otros tramos?",
            "choice:single_flight|multi_segment_or_round_trip",
        ),
        ("travel.delay_refund_requested", "¿Quieres dejar de viajar en ese vuelo y solicitar el reembolso del billete?", "boolean"),
        ("travel.passenger_took_delayed_flight", "¿Finalmente utilizaste el vuelo retrasado?", "boolean"),
    ]
    for key, question, input_type in fixed:
        if key not in facts:
            return _ask(key, question, input_type)

    if _value(facts, "travel.delay_refund_requested") is not True:
        return {"done": True, "question": None, "field": None}
    if _value(facts, "travel.passenger_took_delayed_flight") is True:
        return {"done": True, "question": None, "field": None}
    if _value(facts, "travel.departure_airport_in_eu") is False:
        return {"done": True, "question": None, "field": None}
    if _value(facts, "travel.confirmed_reservation") is False:
        return {"done": True, "question": None, "field": None}
    if _value(facts, "travel.package_trip") is True:
        return {"done": True, "question": None, "field": None}
    if _value(facts, "travel.booking_scope") != "single_flight":
        return {"done": True, "question": None, "field": None}
    if _value(facts, "travel.fare_status") not in {"public_fare", "frequent_flyer_program"}:
        return {"done": True, "question": None, "field": None}

    if "travel.documented_ticket_price" not in facts:
        return _ask(
            "travel.documented_ticket_price",
            "¿Qué precio de ese vuelo consta en el billete o confirmación de reserva?",
            "money",
        )
    if "travel.refund_received" not in facts:
        return _ask("travel.refund_received", "¿La aerolínea ya te ha devuelto algún importe por ese vuelo?", "boolean")
    if _value(facts, "travel.refund_received") is True and "travel.refund_received_amount" not in facts:
        return _ask("travel.refund_received_amount", "¿Qué importe te ha reembolsado ya?", "money")
    return {"done": True, "question": None, "field": None}



def _v03_question(facts: dict[str, FactValue]) -> dict:
    if "travel.denied_boarding_involuntary" not in facts:
        return _ask(
            "travel.denied_boarding_involuntary",
            "¿La aerolínea te impidió embarcar contra tu voluntad?",
            "boolean",
        )
    if _value(facts, "travel.denied_boarding_involuntary") is False:
        return {"done": True, "question": None, "field": None}

    fixed = [
        ("travel.departure_airport_in_eu", "¿El vuelo salía de un aeropuerto situado en la Unión Europea?", "boolean"),
        ("travel.confirmed_reservation", "¿Tenías una reserva confirmada?", "boolean"),
        ("travel.presentation_requirement_met", "¿Te presentaste para embarcar cumpliendo la hora y condiciones exigidas?", "boolean"),
        (
            "travel.fare_status",
            "¿Cómo obtuviste el billete?",
            "choice:public_fare|frequent_flyer_program|nonpublic_free_or_reduced|unknown",
        ),
        (
            "travel.denied_boarding_reason",
            "¿Qué motivo dio la aerolínea para impedirte embarcar?",
            "choice:operational_or_no_reason|health|safety_security|inadequate_travel_documents|unclear",
        ),
        (
            "travel.distance_band",
            "¿En qué banda está la distancia del vuelo?",
            "choice:le_1500|intra_eu_gt_1500|other_1500_3500|other_gt_3500|unknown",
        ),
        ("travel.rerouted_to_final_destination", "¿La aerolínea te llevó al destino final en otro vuelo?", "boolean"),
    ]
    for key, question, input_type in fixed:
        if key not in facts:
            return _ask(key, question, input_type)

    if _value(facts, "travel.rerouted_to_final_destination") is True and "travel.rerouting_arrival_delay_hours" not in facts:
        return _ask(
            "travel.rerouting_arrival_delay_hours",
            "¿Cuántas horas más tarde llegaste al destino final respecto de la hora prevista?",
            "number",
        )
    if "travel.compensation_received" not in facts:
        return _ask(
            "travel.compensation_received",
            "¿La aerolínea ya te ha pagado alguna compensación por la denegación de embarque?",
            "boolean",
        )
    if _value(facts, "travel.compensation_received") is True and "travel.compensation_received_amount" not in facts:
        return _ask("travel.compensation_received_amount", "¿Qué importe te ha pagado ya?", "money")
    return {"done": True, "question": None, "field": None}



def _b01_question(facts: dict[str, FactValue]) -> dict:
    fixed = [
        (
            "bank.user_scope",
            "¿Actúas como consumidor o como microempresa en relación con esta cuenta o medio de pago?",
            "choice:consumer|microenterprise|other",
        ),
        ("bank.payer_provider_in_spain", "¿La cuenta o medio de pago lo presta una entidad/proveedor situado en España?", "boolean"),
        ("bank.operation_unauthorized", "¿Niega haber autorizado esta operación de pago?", "boolean"),
    ]
    for key, question, input_type in fixed:
        if key not in facts:
            return _ask(key, question, input_type)

    if _value(facts, "bank.operation_unauthorized") is False:
        return {"done": True, "question": None, "field": None}

    rest = [
        ("bank.debit_date", "¿Qué día se cargó la operación en la cuenta?", "date"),
        ("bank.awareness_date", "¿Qué día viste o conociste la operación no autorizada?", "date"),
        ("bank.notification_date", "¿Qué día la comunicaste a tu entidad o proveedor de pago?", "date"),
        ("bank.provider_supplied_operation_info", "¿La entidad te había facilitado o puesto a disposición la información de esa operación?", "boolean"),
        ("bank.payment_initiation_provider_involved", "¿La operación se inició mediante un proveedor externo de iniciación de pagos?", "boolean"),
        (
            "bank.instrument_status",
            "¿La operación está relacionada con una tarjeta o instrumento perdido, robado o apropiado por un tercero?",
            "choice:not_lost_stolen_or_misappropriated|lost_stolen_or_misappropriated|unknown",
        ),
        ("bank.provider_alleges_fraud_or_gross_negligence", "¿La entidad te acusa de fraude o negligencia grave en la custodia o uso del medio de pago?", "boolean"),
        (
            "bank.provider_fraud_suspicion_status",
            "¿La entidad afirma haber retenido la devolución por sospecha razonable de fraude comunicada al Banco de España?",
            "choice:none|reported_to_bde|unknown",
        ),
    ]
    for key, question, input_type in rest:
        if key not in facts:
            return _ask(key, question, input_type)

    if "bank.documented_operation_amount" not in facts:
        return _ask("bank.documented_operation_amount", "¿Qué importe exacto figura cargado en la operación?", "money")
    if "bank.refund_received" not in facts:
        return _ask("bank.refund_received", "¿La entidad ya te ha devuelto algún importe de esa operación?", "boolean")
    if _value(facts, "bank.refund_received") is True and "bank.refund_received_amount" not in facts:
        return _ask("bank.refund_received_amount", "¿Qué importe te ha devuelto ya?", "money")
    return {"done": True, "question": None, "field": None}



def _r01_question(facts: dict[str, FactValue]) -> dict:
    order = [
        (
            "rental.contract_type",
            "¿Qué tipo de alquiler terminó?",
            "choice:dwelling|other_urban_use|room_only|tourist_or_hospitality|unknown",
        ),
        ("rental.lease_ended", "¿El arrendamiento ya ha terminado?", "boolean"),
    ]
    for key, question, input_type in order:
        if key not in facts:
            return _ask(key, question, input_type)

    if _value(facts, "rental.contract_type") not in {"dwelling", "other_urban_use"}:
        return {"done": True, "question": None, "field": None}
    if _value(facts, "rental.lease_ended") is not True:
        return {"done": True, "question": None, "field": None}

    fixed = [
        ("rental.keys_delivered_date", "¿Qué día entregaste las llaves al arrendador?", "date"),
        ("rental.keys_delivery_proof_available", "¿Tienes una prueba de la fecha de entrega de llaves?", "boolean"),
        (
            "rental.deposit_type",
            "Según el contrato o recibo, ¿el importe reclamado es la fianza legal en metálico o una garantía adicional?",
            "choice:statutory_cash_deposit|additional_guarantee|mixed_or_unknown",
        ),
        (
            "rental.refundable_balance_status",
            "¿Está documentado o reconocido por el arrendador el saldo de fianza que debe devolverte?",
            "choice:confirmed_amount|deductions_or_amount_disputed|unknown",
        ),
    ]
    for key, question, input_type in fixed:
        if key not in facts:
            return _ask(key, question, input_type)

    if _value(facts, "rental.keys_delivery_proof_available") is not True:
        return {"done": True, "question": None, "field": None}
    if _value(facts, "rental.deposit_type") != "statutory_cash_deposit":
        return {"done": True, "question": None, "field": None}
    if _value(facts, "rental.refundable_balance_status") != "confirmed_amount":
        return {"done": True, "question": None, "field": None}

    if "rental.confirmed_refundable_balance" not in facts:
        return _ask(
            "rental.confirmed_refundable_balance",
            "¿Qué saldo exacto de la fianza consta como pendiente de devolución?",
            "money",
        )
    if "rental.refund_received" not in facts:
        return _ask("rental.refund_received", "¿El arrendador ya te ha devuelto alguna parte de ese saldo?", "boolean")
    if _value(facts, "rental.refund_received") is True and "rental.refund_received_amount" not in facts:
        return _ask("rental.refund_received_amount", "¿Qué importe te ha devuelto ya?", "money")
    return {"done": True, "question": None, "field": None}



def _s01_question(facts: dict[str, FactValue]) -> dict:
    order = [
        (
            "insurance.claimant_role",
            "¿Qué relación tienes con el seguro?",
            "choice:policyholder|insured|beneficiary|third_party|other_or_unknown",
        ),
        (
            "insurance.counterparty_type",
            "¿A quién reclamas el pago?",
            "choice:insurer|consortium|broker|third_party|other_or_unknown",
        ),
        (
            "insurance.claim_declaration_received_by_insurer",
            "¿La aseguradora recibió ya la declaración o parte del siniestro?",
            "boolean",
        ),
    ]
    for key, question, input_type in order:
        if key not in facts:
            return _ask(key, question, input_type)

    if _value(facts, "insurance.claimant_role") not in {"policyholder", "insured", "beneficiary"}:
        return {"done": True, "question": None, "field": None}
    if _value(facts, "insurance.counterparty_type") != "insurer":
        return {"done": True, "question": None, "field": None}
    if _value(facts, "insurance.claim_declaration_received_by_insurer") is not True:
        return {"done": True, "question": None, "field": None}

    fixed = [
        (
            "insurance.claim_declaration_received_date",
            "¿Qué día consta que la aseguradora recibió la declaración del siniestro?",
            "date",
        ),
        (
            "insurance.claim_declaration_receipt_evidence",
            "¿Tienes una prueba de esa fecha de recepción (acuse, email, número de parte o documento equivalente)?",
            "boolean",
        ),
        (
            "insurance.insurer_acknowledged_minimum_amount",
            "¿La aseguradora ha reconocido o cuantificado por escrito una cantidad mínima que admite deber por este siniestro?",
            "boolean",
        ),
    ]
    for key, question, input_type in fixed:
        if key not in facts:
            return _ask(key, question, input_type)

    if _value(facts, "insurance.claim_declaration_receipt_evidence") is not True:
        return {"done": True, "question": None, "field": None}
    if _value(facts, "insurance.insurer_acknowledged_minimum_amount") is not True:
        return {"done": True, "question": None, "field": None}

    if "insurance.acknowledged_minimum_amount" not in facts:
        return _ask(
            "insurance.acknowledged_minimum_amount",
            "¿Qué cantidad mínima exacta reconoce por escrito la aseguradora?",
            "money",
        )
    if "insurance.minimum_payment_received" not in facts:
        return _ask(
            "insurance.minimum_payment_received",
            "¿La aseguradora ya te ha pagado alguna parte de esa cantidad mínima?",
            "boolean",
        )
    if _value(facts, "insurance.minimum_payment_received") is True and "insurance.minimum_payment_received_amount" not in facts:
        return _ask(
            "insurance.minimum_payment_received_amount",
            "¿Qué importe de esa cantidad mínima te ha pagado ya?",
            "money",
        )
    return {"done": True, "question": None, "field": None}



def _s02_question(facts: dict[str, FactValue]) -> dict:
    order = [
        (
            "insurance.contract_role",
            "¿Eres el tomador que figura como parte contratante de la póliza?",
            "choice:policyholder|insured_only|beneficiary_only|other_or_unknown",
        ),
        (
            "insurance.policy_kind",
            "¿Qué tipo de póliza es?",
            "choice:non_life|life|unknown",
        ),
        (
            "insurance.automatic_renewal_provided",
            "¿La póliza prevé que se renueve o prorrogue automáticamente al terminar el período actual?",
            "boolean",
        ),
        (
            "insurance.policyholder_wants_nonrenewal",
            "¿Quieres impedir la próxima renovación y finalizar la póliza al terminar el período actual?",
            "boolean",
        ),
    ]
    for key, question, input_type in order:
        if key not in facts:
            return _ask(key, question, input_type)

    if _value(facts, "insurance.contract_role") != "policyholder":
        return {"done": True, "question": None, "field": None}
    if _value(facts, "insurance.policy_kind") != "non_life":
        return {"done": True, "question": None, "field": None}
    if _value(facts, "insurance.automatic_renewal_provided") is not True:
        return {"done": True, "question": None, "field": None}
    if _value(facts, "insurance.policyholder_wants_nonrenewal") is not True:
        return {"done": True, "question": None, "field": None}

    if "insurance.current_period_end_date" not in facts:
        return _ask(
            "insurance.current_period_end_date",
            "¿Qué día termina el período de seguro actualmente en curso según la póliza?",
            "date",
        )
    if "insurance.current_period_end_date_evidence" not in facts:
        return _ask(
            "insurance.current_period_end_date_evidence",
            "¿Tienes la póliza o un documento que acredite esa fecha de finalización?",
            "boolean",
        )
    return {"done": True, "question": None, "field": None}


def next_question(facts: dict[str, FactValue], family: str | None) -> dict:
    if family == "S02":
        return _s02_question(facts)
    if family == "S01":
        return _s01_question(facts)
    if family == "R01":
        return _r01_question(facts)
    if family == "B01":
        return _b01_question(facts)
    if family == "V01":
        return _v01_question(facts)
    if family == "V02":
        return _v02_question(facts)
    if family == "V03":
        return _v03_question(facts)
    if family == "T01":
        return _t01_question(facts)
    if family == "T02":
        return _t02_question(facts)
    if family == "C02":
        return _c02_question(facts)
    if family == "C03":
        return _c03_question(facts)
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
