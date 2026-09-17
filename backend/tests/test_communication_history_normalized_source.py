from datetime import date, datetime, timezone

from app.models import AuditEvent, Case, Communication


def test_communication_history_prefers_normalized_records_over_stale_audit_metadata(client, db):
    created = client.post(
        "/api/cases",
        json={"message": "Compré una cafetera online y no me ha llegado el pedido"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    case = db.get(Case, case_id)
    assert case is not None

    outbound = Communication(
        case_id=case_id,
        direction="OUTBOUND",
        channel="web_form",
        body=None,
        occurred_on=date(2026, 9, 10),
        reference_number="NORMAL-OUT",
    )
    inbound = Communication(
        case_id=case_id,
        direction="INBOUND",
        channel="email",
        body="Respuesta real de la empresa",
        occurred_on=date(2026, 9, 14),
        received_at=datetime.now(timezone.utc),
        reference_number="NORMAL-IN",
    )
    db.add_all([outbound, inbound])
    db.flush()

    db.add_all(
        [
            AuditEvent(
                case_id=case_id,
                event_type="CLAIM_SUBMITTED",
                payload_json={
                    "submitted_on": "2026-01-01",
                    "channel": "stale_channel",
                    "reference": "STALE-OUT",
                },
            ),
            AuditEvent(
                case_id=case_id,
                event_type="COMPANY_RESPONSE_RECORDED",
                payload_json={
                    "communication_id": inbound.id,
                    "received_on": "2026-01-02",
                    "channel": "stale_channel",
                    "reference": "STALE-IN",
                },
            ),
        ]
    )
    db.commit()

    history = client.get(f"/api/cases/{case_id}/communications")
    assert history.status_code == 200, history.text
    items = history.json()["communications"]
    assert len(items) == 2

    sent, received = items
    assert sent["direction"] == "OUTBOUND"
    assert sent["channel"] == "web_form"
    assert sent["reference_number"] == "NORMAL-OUT"
    assert sent["occurred_on"] == "2026-09-10"
    assert sent["recorded_at"] is not None

    assert received["direction"] == "INBOUND"
    assert received["channel"] == "email"
    assert received["reference_number"] == "NORMAL-IN"
    assert received["occurred_on"] == "2026-09-14"
    assert received["body"] == "Respuesta real de la empresa"
    assert received["recorded_at"] is not None


def test_communication_history_uses_audit_date_only_as_legacy_fallback(client, db):
    created = client.post(
        "/api/cases",
        json={"message": "Compré una cafetera online y no me ha llegado el pedido"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]

    inbound = Communication(
        case_id=case_id,
        direction="INBOUND",
        channel="email",
        body="Respuesta histórica",
        occurred_on=None,
        received_at=datetime.now(timezone.utc),
        reference_number="LEGACY-IN",
    )
    db.add(inbound)
    db.flush()
    db.add(
        AuditEvent(
            case_id=case_id,
            event_type="COMPANY_RESPONSE_RECORDED",
            payload_json={
                "communication_id": inbound.id,
                "received_on": "2026-09-12",
                "channel": "email",
                "reference": "LEGACY-IN",
            },
        )
    )
    db.commit()

    history = client.get(f"/api/cases/{case_id}/communications")
    assert history.status_code == 200, history.text
    item = history.json()["communications"][0]
    assert item["occurred_on"] == "2026-09-12"
    assert item["channel"] == "email"
    assert item["reference_number"] == "LEGACY-IN"
