from app.config import settings


def create_case(client):
    r=client.post("/api/cases",json={"message":"Me cambié de compañía de luz y me siguen cobrando un mantenimiento"}); assert r.status_code==200
    return r.json()["id"]

def put_fact(client,cid,key,value):
    r=client.post(f"/api/cases/{cid}/facts",json={"key":key,"value":value,"state":"confirmed","user_confirmed":True}); assert r.status_code==200

def complete(client,cid):
    put_fact(client,cid,"electricity.supply_end_date","2026-06-03")
    put_fact(client,cid,"electricity.addon.identity","Protección Hogar")
    put_fact(client,cid,"electricity.addon.ever_contracted",True)
    put_fact(client,cid,"electricity.addon.contracted_with_supply",True)
    put_fact(client,cid,"electricity.addon.keep_requested",False)
    r=client.post(f"/api/cases/{cid}/charges",json={"charges":[
      {"amount":8.99,"service_period_start":"2026-06-04","service_period_end":"2026-07-03","evidence_verified":True},
      {"amount":8.99,"service_period_start":"2026-07-04","service_period_end":"2026-08-03","evidence_verified":True}
    ]}); assert r.status_code==200

def prepare(client,cid):
    r=client.post(f"/api/cases/{cid}/diagnose"); assert r.status_code==200
    r=client.post(f"/api/cases/{cid}/prepare-claim"); assert r.status_code==200

def submit(client,cid,submitted_on="2026-09-01"):
    r=client.post(f"/api/cases/{cid}/submission",json={"submitted_on":submitted_on,"channel":"web_form"}); assert r.status_code==200, r.text
    return r

def submitted_case(client,submitted_on="2026-09-01"):
    cid=create_case(client); complete(client,cid); prepare(client,cid); submit(client,cid,submitted_on)
    return cid

def evidenced_response(client,cid,text,received_on="2026-09-02"):
    return client.post(f"/api/cases/{cid}/responses/evidenced",json={"text":text,"received_on":received_on,"channel":"email"})

def test_full_diagnosis_api(client):
    cid=create_case(client); complete(client,cid)
    r=client.post(f"/api/cases/{cid}/diagnose"); assert r.status_code==200
    body=r.json(); assert body["viability"]=="HIGH"; assert body["claimable_amount"]==17.98
    r=client.get(f"/api/cases/{cid}"); assert r.json()["status"]=="DIAGNOSED"

def test_submission_exposes_verified_legal_period_without_inventing_calendar_date(client):
    cid=create_case(client); complete(client,cid); prepare(client,cid)
    r=submit(client,cid); body=r.json()
    assert body["deadline"] is None
    assert body["deadline_status"]=="LEGAL_PERIOD_ONLY"
    assert body["legal_response_period_business_days"]==15
    assert body["legal_basis"]["article"]=="55.3"
    assert body["legal_basis"]["official_url"].startswith("https://www.boe.es/")
    assert "no calcula una fecha exacta" in body["warning"]


def test_submission_never_treats_a_partial_holiday_list_as_proof_of_exact_due_date(client, monkeypatch):
    monkeypatch.setattr(settings, "legal_holidays_csv", "2026-10-12,2026-12-08")
    cid=create_case(client); complete(client,cid); prepare(client,cid)
    r=submit(client,cid); assert r.json()["deadline"] is None
    assert r.json()["deadline_status"]=="LEGAL_PERIOD_ONLY"

def test_response_analysis(client):
    cid=submitted_case(client)
    r=evidenced_response(client,cid,"Denegamos la devolución porque el contrato de mantenimiento es independiente.")
    assert r.status_code==200; assert "INDEPENDENT_ADDON_CONTRACT" in r.json()["analysis"]["arguments"]

def test_prepare_claim_package(client):
    cid=create_case(client); complete(client,cid); client.post(f"/api/cases/{cid}/diagnose")
    r=client.post(f"/api/cases/{cid}/prepare-claim"); assert r.status_code==200
    body=r.json(); assert body["amount"]==17.98; assert "artículo 32.4" in body["text"]
    assert "REFUND_VERIFIED_POST_TERMINATION_CHARGES" in body["remedies"]


def test_company_assertion_reopens_contradictor_and_lowers_to_medium(client):
    cid=submitted_case(client)
    r=evidenced_response(client,cid,"Denegamos la devolución porque el contrato de mantenimiento es independiente.")
    assert r.status_code==200
    updated=r.json()["updated_diagnosis"]
    assert updated["viability"]=="MEDIUM"
    assert any(x["type"]=="INDEPENDENT_ADDON_CONTRACT" and x["status"]=="open" for x in updated["counterarguments"])


def test_unknown_company_response_routes_to_human_review(client):
    cid=submitted_case(client)
    r=evidenced_response(client,cid,"Su solicitud ha sido gestionada con referencia 12345.")
    assert r.status_code==200; assert r.json()["analysis"]["type"]=="UNKNOWN"
    assert r.json()["case_status"]=="HUMAN_REVIEW"


def test_outcome_requires_user_verification_to_close(client):
    cid=submitted_case(client,submitted_on="2026-09-01")
    accepted=evidenced_response(client,cid,"Aceptamos su reclamación y procederemos a devolver el importe.",received_on="2026-09-02")
    assert accepted.status_code==200; assert accepted.json()["case_status"]=="RESOLVED_PENDING_EXECUTION"
    r=client.post(f"/api/cases/{cid}/outcome/evidenced",json={"result_type":"FAVORABLE","amount_recovered":26.97,"verified_by_user":False})
    assert r.status_code==200; assert r.json()["case_status"]=="RESOLVED_PENDING_EXECUTION"
    r=client.post(f"/api/cases/{cid}/outcome/evidenced",json={"result_type":"FAVORABLE","amount_recovered":26.97,"verified_by_user":True,"remaining_material_commitments":"none","resolved_on":"2026-09-03","resolution_channel":"bank_or_card_refund"})
    assert r.status_code==200; assert r.json()["case_status"]=="RESOLVED"


def test_demo_frontend_is_served(client):
    r=client.get("/demo/"); assert r.status_code==200; assert "Cuéntame qué te ha pasado" in r.text
