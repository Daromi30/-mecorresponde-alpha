from __future__ import annotations
from datetime import date
from sqlalchemy.orm import Session
from . import services_v2 as svc
from .engine.b01 import evaluate_b01
from .engine.b02 import evaluate_b02

_INSTALLED=False
_PREVIOUS_SEED=svc.seed_legal

def _seed_legal(db: Session):
    rules=_PREVIOUS_SEED(db)
    svc._ensure_source(db,"RDL19_2018","BOE / Jefatura del Estado","Real Decreto-ley 19/2018, de 23 de noviembre, de servicios de pago y otras medidas urgentes en materia financiera","https://www.boe.es/eli/es/rdl/2018/11/23/19/con",date(2018,11,24))
    rules["PAYMENT_UNAUTHORIZED_REFUND_CURRENT"]=svc._ensure_rule(db,"PAYMENT_UNAUTHORIZED_REFUND_CURRENT",1,date(2018,11,25),"RDL19_2018","34, 43, 44, 45 y 46",{"consumer_or_microenterprise":True,"unauthorized_payment":True,"notification_article_43_scope":True},{"provider_refund_rule":True,"provider_evidentiary_burden":True,"thirteen_month_general_notice_limit":True,"article_46_exceptions_require_facts":True},"Para una operación de pago no autorizada, los artículos 43 a 46 regulan notificación, prueba, reembolso y posibles responsabilidades del ordenante. B01 automatiza solo un supuesto estrecho sin controversia material.")
    rules["PAYMENT_AUTHORIZED_DIRECT_DEBIT_REFUND_CURRENT"]=svc._ensure_rule(db,"PAYMENT_AUTHORIZED_DIRECT_DEBIT_REFUND_CURRENT",1,date(2018,11,25),"RDL19_2018","34, 48 y 49",{"consumer_or_microenterprise":True,"authorized_payment":True,"article_48_2_direct_debit":True,"request_within_eight_weeks":True,"article_48_4_exception_absent":True},{"full_refund":True,"request_period_weeks":8,"provider_response_business_days":10,"article_48_4_contract_exception":True},"B02 automatiza solo un adeudo domiciliado autorizado confirmado dentro del artículo 48.2, solicitado dentro de ocho semanas y sin posible exclusión contractual del artículo 48.4.")
    return rules

def _b02_question(facts):
    def ask(k,q,t): return {"done":False,"question":q,"field":k,"input_type":t}
    v=lambda k: facts[k].value if k in facts else None
    order=[
      ("bank.user_scope","¿Actúas como consumidor o microempresa?","choice:consumer|microenterprise|other"),
      ("bank.payer_provider_in_spain","¿Tu proveedor de servicios de pago está situado en España?","boolean"),
      ("bank.operation_authorized","¿Habías autorizado este adeudo?","boolean"),
      ("bank.authorized_payment_type","¿Se trata de un adeudo domiciliado (recibo domiciliado)?","choice:direct_debit|other|unknown"),
      ("bank.direct_debit_article_48_2_confirmed","¿En el movimiento o mandato aparece identificado como adeudo directo SEPA o recibo SEPA en euros?","boolean"),
      ("bank.payment_scope_clear","¿Está claro el ámbito del pago y de los proveedores implicados?","boolean"),
      ("bank.debit_date","¿Qué día se cargó el adeudo?","date"),
      ("bank.refund_request_date","¿Qué día solicitaste o vas a solicitar la devolución?","date"),
      ("bank.contract_contains_article_48_4_waiver","¿Tu contrato marco contiene una cláusula que excluye la devolución de ciertos adeudos autorizados si se cumplen determinadas condiciones?","boolean"),
      ("bank.direct_consent_given_to_payment_provider","¿Diste el consentimiento para ejecutar ese adeudo directamente a tu banco o proveedor de servicios de pago?","boolean"),
      ("bank.future_operation_info_four_weeks_before","¿El banco o el beneficiario te facilitó la información de ese adeudo futuro al menos cuatro semanas antes del cargo?","boolean"),
      ("bank.documented_operation_amount","¿Qué importe exacto figura en el adeudo?","money"),
      ("bank.refund_received","¿La entidad ya te ha devuelto algún importe?","boolean"),
    ]
    for k,q,t in order:
        if k not in facts: return ask(k,q,t)
        if k=="bank.operation_authorized" and v(k) is False: return {"done":True,"question":None,"field":None}
    if v("bank.refund_received") is True and "bank.refund_received_amount" not in facts:
        return ask("bank.refund_received_amount","¿Qué importe te ha devuelto ya?","money")
    return {"done":True,"question":None,"field":None}

def install_banking_extensions():
    global _INSTALLED
    if _INSTALLED:return
    svc.EVALUATORS["B01"]=evaluate_b01; svc.FAMILY_RULES["B01"]=["PAYMENT_UNAUTHORIZED_REFUND_CURRENT"]
    svc.EVALUATORS["B02"]=evaluate_b02; svc.FAMILY_RULES["B02"]=["PAYMENT_AUTHORIZED_DIRECT_DEBIT_REFUND_CURRENT"]
    svc.seed_legal=_seed_legal
    previous_q=svc.next_question
    svc.next_question=lambda facts,family: _b02_question(facts) if family=="B02" else previous_q(facts,family)

    # Extend deterministic classification without confusing unauthorized B01 cases.
    inner=getattr(svc.gateway,"inner",svc.gateway); previous_classify=inner.classify
    def classify(text):
        import unicodedata
        t="".join(c for c in unicodedata.normalize("NFD",text.lower()) if unicodedata.category(c)!="Mn")
        unauthorized=any(x in t for x in ["no autorice","no he autorizado","no reconozco","no autorizado"])
        direct=any(x in t for x in ["adeudo domiciliado","recibo domiciliado","devolver un recibo","devolucion del recibo"])
        if direct and not unauthorized:return {"vertical":"banking","family":"B02","confidence":0.96}
        return previous_classify(text)
    inner.classify=classify
    previous_response=inner.analyze_response
    def analyze_response(text):
        import unicodedata
        t="".join(c for c in unicodedata.normalize("NFD",text.lower()) if unicodedata.category(c)!="Mn")
        consent=any(x in t for x in ["consentimiento", "consentido", "consintio", "consintio el adeudo", "autorizo directamente"])
        prior_notice=any(x in t for x in ["cuatro semanas", "4 semanas", "aviso previo"])
        if consent and prior_notice:
            return {"type":"DENIAL","arguments":["ARTICLE_48_4_EXCEPTION_ASSERTED"]}
        return previous_response(text)
    inner.analyze_response=analyze_response

    from . import claim_packages as cp
    cp.REGISTERED_EXTENSION_FAMILIES=frozenset(set(cp.REGISTERED_EXTENSION_FAMILIES)|{"B02"})
    def render_b02(ctx):
        if ctx.next_action!="PREPARE_B02_AUTHORIZED_DIRECT_DEBIT_REFUND": raise ValueError("B02 requires review rather than a refund request")
        amount=round(float(ctx.decision.claimable_amount or 0),2)
        if amount<=0: raise ValueError("No outstanding B02 refund")
        return {"claim_type":"B02_AUTHORIZED_DIRECT_DEBIT_REFUND","amount":amount,"text":f"Solicito la devolución pendiente de {amount:.2f} € del adeudo domiciliado autorizado, conforme a los artículos 48.2 y 49 del Real Decreto-ley 19/2018. La solicitud se formula dentro de ocho semanas desde el adeudo y el expediente no identifica una excepción contractual aplicable del artículo 48.4."}
    cp.RENDERERS["B02"]=render_b02

    _INSTALLED=True
