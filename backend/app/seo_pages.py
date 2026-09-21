from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeoProblemPage:
    family: str
    vertical: str
    vertical_slug: str
    slug: str
    title: str
    description: str
    intro: str
    evidence_examples: tuple[str, ...]

    @property
    def path(self) -> str:
        return f"/reclamar/{self.vertical_slug}/{self.slug}"


SEO_PROBLEM_PAGES: tuple[SeoProblemPage, ...] = (
    SeoProblemPage(
        "E01", "electricity", "luz", "precio-luz-distinto-contratado",
        "Precio de la luz distinto de lo contratado: qué comprobar",
        "Comprueba qué datos y documentos conviene reunir si tu tarifa, precio o descuento eléctrico no coincide con lo contratado.",
        "Un precio distinto, una tarifa diferente o un descuento que no aparece pueden tener causas distintas. El primer paso es separar lo prometido, lo aplicado y lo que puede acreditarse.",
        ("Contrato, oferta o condiciones que aceptaste", "Facturas afectadas", "Comunicaciones donde consten precio, tarifa o descuento"),
    ),
    SeoProblemPage(
        "E02-A", "electricity", "luz", "sobrefacturacion-luz",
        "Sobrefacturación de luz: cómo ordenar el caso",
        "Qué revisar y qué documentación reunir si sospechas que una factura eléctrica incluye importes superiores a los debidos.",
        "Antes de concluir que existe una cantidad reclamable hay que identificar qué concepto se discute, qué periodo afecta y con qué documentación puede contrastarse.",
        ("Factura o facturas discutidas", "Lecturas y periodos de consumo disponibles", "Contrato o condiciones económicas aplicables"),
    ),
    SeoProblemPage(
        "E02-B", "electricity", "luz", "cobro-duplicado-factura-luz",
        "Cobro duplicado de una factura de luz: qué revisar",
        "Ordena las pruebas necesarias para comprobar si se ha pagado dos veces la misma deuda eléctrica.",
        "Dos cargos parecidos no siempre corresponden a la misma deuda. Conviene comparar referencias, periodos, importes y movimientos bancarios antes de tratarlo como duplicado.",
        ("Factura o referencia de la deuda", "Dos movimientos o justificantes de pago", "Fechas, importes y conceptos de ambos cargos"),
    ),
    SeoProblemPage(
        "E03", "electricity", "luz", "cambio-compania-luz-sin-consentimiento",
        "Cambio de compañía de luz sin consentimiento: qué comprobar",
        "Qué información reunir si aparece un cambio de comercializadora eléctrica que no reconoces o cuyo consentimiento discutes.",
        "El análisis depende de identificar el suministro afectado, cuándo se produjo el cambio y qué prueba de consentimiento existe o falta.",
        ("Datos del suministro y comercializadoras implicadas", "Fecha efectiva del cambio", "Contrato, grabación, correo o cualquier prueba sobre el consentimiento"),
    ),
    SeoProblemPage(
        "E04-A", "electricity", "luz", "servicio-mantenimiento-luz-no-contratado",
        "Servicio de mantenimiento de luz no contratado: cómo documentarlo",
        "Qué revisar si te cobran un mantenimiento, seguro u otro servicio adicional que no recuerdas haber contratado.",
        "Para distinguir un servicio no solicitado de uno válidamente contratado hay que localizar el alta, el consentimiento y los cargos concretos discutidos.",
        ("Factura donde aparece el servicio", "Contrato o condiciones del servicio adicional", "Grabaciones, emails o documentos de contratación disponibles"),
    ),
    SeoProblemPage(
        "E04-B", "electricity", "luz", "mantenimiento-despues-cambiar-compania-luz",
        "Mantenimiento cobrado después de cambiar de compañía de luz",
        "Qué comprobar si siguen cobrando un servicio adicional después de terminar el suministro con la comercializadora anterior.",
        "La fecha de fin del suministro, la identidad del servicio adicional y los cargos posteriores son hechos distintos que conviene acreditar por separado.",
        ("Documento o factura que acredite el fin del suministro", "Contrato o identificación del servicio adicional", "Facturas o cargos posteriores al cambio"),
    ),
    SeoProblemPage(
        "E05", "electricity", "luz", "penalizacion-permanencia-cancelar-luz",
        "Penalización o permanencia al cancelar la luz: qué revisar",
        "Organiza los datos necesarios para analizar una penalización cobrada al cancelar o cambiar un contrato eléctrico.",
        "No todas las penalizaciones parten del mismo tipo de contrato ni del mismo momento de cancelación. El análisis debe empezar por esos hechos antes de valorar el cargo.",
        ("Contrato y cláusula de permanencia o penalización", "Fecha de cancelación o cambio", "Factura o cargo donde aparece la penalización"),
    ),
    SeoProblemPage(
        "E06", "electricity", "luz", "lectura-estimada-regularizacion-luz",
        "Lectura estimada o regularización de luz: qué comprobar",
        "Qué datos reunir si una factura eléctrica usa lecturas estimadas o incluye una regularización de consumo que quieres revisar.",
        "Para reconstruir el caso conviene separar lecturas reales, lecturas estimadas, periodos facturados y cualquier regularización posterior.",
        ("Facturas del periodo afectado", "Lecturas reales o fotografías del contador si existen", "Comunicaciones sobre regularización o revisión de consumo"),
    ),
    SeoProblemPage(
        "E07", "electricity", "luz", "cambio-precio-condiciones-luz",
        "Cambio de precio o condiciones de la luz: qué revisar",
        "Qué información comparar si tu comercializadora modifica el precio u otras condiciones del contrato eléctrico.",
        "La cuestión principal es reconstruir qué condiciones había antes, qué cambió, cuándo se comunicó y desde qué fecha se aplicó.",
        ("Contrato o condiciones anteriores", "Comunicación del cambio", "Primera factura donde se aplican las nuevas condiciones"),
    ),
    SeoProblemPage(
        "C01", "purchases", "compras", "producto-defectuoso-garantia-rechazada",
        "Producto defectuoso o garantía rechazada: qué reunir",
        "Qué datos y documentos conviene ordenar cuando un producto presenta un defecto y el vendedor rechaza la solución solicitada.",
        "El tipo de defecto, la fecha de entrega, cuándo apareció el problema y qué respuesta dio el vendedor son piezas distintas del expediente.",
        ("Ticket, factura o justificante de compra", "Pruebas del defecto", "Respuesta del vendedor, servicio técnico o garantía"),
    ),
    SeoProblemPage(
        "C02", "purchases", "compras", "reparacion-fallida-repetida-demora",
        "Reparación fallida, repetida o demorada: cómo documentarla",
        "Ordena el historial de reparaciones de un producto cuando el problema persiste, se repite o la solución se demora.",
        "Un expediente útil debe mostrar qué defecto existía, qué intentos de reparación se hicieron y cuál fue el resultado de cada uno.",
        ("Justificante de compra", "Partes de reparación o entradas en servicio técnico", "Fechas y resultado de cada intervención"),
    ),
    SeoProblemPage(
        "C03", "purchases", "compras", "producto-equivocado-incompleto-distinto",
        "Producto equivocado, incompleto o distinto de lo comprado",
        "Qué comparar si recibes un producto diferente, incompleto o que no coincide con la descripción contratada.",
        "La comparación debe hacerse entre lo ofrecido o contratado y lo realmente entregado, conservando pruebas de ambos extremos.",
        ("Pedido, anuncio o descripción del producto", "Factura o confirmación de compra", "Fotografías y detalle de lo recibido"),
    ),
    SeoProblemPage(
        "C04", "purchases", "compras", "pedido-no-entregado",
        "Pedido no entregado: qué comprobar antes de reclamar",
        "Qué fechas, pruebas de pago y comunicaciones conviene reunir cuando un pedido no llega.",
        "Para decidir el siguiente paso hay que saber qué fecha de entrega se pactó o comunicó, si hubo intentos de entrega y qué respuesta ha dado el vendedor.",
        ("Confirmación del pedido y pago", "Fecha o plazo de entrega comunicado", "Seguimiento y comunicaciones con vendedor o transportista"),
    ),
    SeoProblemPage(
        "C05", "purchases", "compras", "desistimiento-devolucion-compra-online",
        "Desistimiento y devolución de una compra online: qué revisar",
        "Ordena fechas y documentos para analizar una devolución o desistimiento en una compra a distancia.",
        "El análisis cambia según el tipo de producto o servicio, las fechas y lo que se comunicó al vendedor. Conviene registrar esos hechos antes de asumir que un plazo o reembolso concreto aplica al caso.",
        ("Confirmación de compra", "Fecha de entrega o de contratación", "Comunicación de desistimiento y prueba de devolución si existe"),
    ),
    SeoProblemPage(
        "T01", "telecom", "telecomunicaciones", "corte-internet-compensacion",
        "Corte de internet: qué comprobar para calcular una compensación",
        "Ordena duración, cuota fija y datos del contrato cuando has sufrido una interrupción temporal del acceso a internet.",
        "La existencia y cuantía de una compensación depende de hechos verificables como la duración del corte, el tipo de servicio y la cuota fija atribuible a internet. El Motor no presume daños adicionales.",
        ("Factura o contrato donde conste la cuota del servicio", "Fechas y duración de la interrupción", "Incidencia, aviso o comunicación de la operadora"),
    ),
    SeoProblemPage(
        "T02", "telecom", "telecomunicaciones", "cambio-precio-condiciones-operadora",
        "Cambio de precio o condiciones de tu operadora: qué revisar",
        "Comprueba la comunicación, las fechas y el contrato si tu operadora anuncia una subida de precio u otro cambio de condiciones.",
        "No todo cambio contractual produce el mismo efecto. Conviene separar qué cambia, por qué, cuándo se comunicó y si la comunicación informa del derecho a resolver sin coste.",
        ("Contrato y condiciones vigentes", "Comunicación del cambio", "Fecha prevista de aplicación y cualquier información sobre baja o permanencia"),
    ),
)

SEO_BY_PATH = {(page.vertical_slug, page.slug): page for page in SEO_PROBLEM_PAGES}
SEO_BY_FAMILY = {page.family: page for page in SEO_PROBLEM_PAGES}
