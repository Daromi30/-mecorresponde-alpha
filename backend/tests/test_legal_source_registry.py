from datetime import date

from sqlalchemy import select

from app.legal_source_registry import OFFICIAL_LEGAL_SOURCES
from app.models import LegalRuleVersion, LegalSource
from app.services_v2 import seed_legal


def test_reviewed_official_source_metadata_is_seeded_exactly(db):
    for source_id, expected in OFFICIAL_LEGAL_SOURCES.items():
        source = db.get(LegalSource, source_id)
        assert source is not None
        assert source.authority == expected.authority
        assert source.title == expected.title
        assert source.official_url == expected.official_url
        assert source.publication_date == expected.publication_date
        assert source.jurisdiction == "ES"
        assert source.status == "active"
        assert source.official_url.startswith("https://www.boe.es/")


def test_seed_repairs_stale_source_metadata_without_rewriting_rule_versions(db):
    source = db.get(LegalSource, "RD88_2026")
    assert source is not None
    source.publication_date = date(2026, 2, 11)
    source.official_url = "https://example.invalid/stale"

    rule = db.scalar(
        select(LegalRuleVersion).where(
            LegalRuleVersion.rule_id == "ELEC_ADDON_END_WITH_SUPPLY",
            LegalRuleVersion.version == 1,
        )
    )
    assert rule is not None
    rule_id_before = rule.id
    db.commit()

    seed_legal(db)
    db.commit()

    repaired = db.get(LegalSource, "RD88_2026")
    assert repaired is not None
    assert repaired.publication_date == date(2026, 2, 12)
    assert repaired.official_url == "https://www.boe.es/eli/es/rd/2026/02/11/88"

    same_rule = db.scalar(
        select(LegalRuleVersion).where(
            LegalRuleVersion.rule_id == "ELEC_ADDON_END_WITH_SUPPLY",
            LegalRuleVersion.version == 1,
        )
    )
    assert same_rule is not None
    assert same_rule.id == rule_id_before


def test_audited_rd88_rule_effect_dates_match_the_regulation(db):
    immediate = {
        "ELEC_ADDON_END_WITH_SUPPLY": date(2026, 2, 12),
        "ELEC_SWITCH_EXPRESS_CONSENT": date(2026, 2, 12),
    }
    delayed_four_months = {
        "ELEC_PRICING_TERMS_CURRENT": date(2026, 6, 12),
        "ELEC_OVERBILL_REFUND": date(2026, 6, 12),
        "ELEC_TERMINATION_PENALTY_CURRENT": date(2026, 6, 12),
        "ELEC_READING_BILLING_CURRENT": date(2026, 6, 12),
        "ELEC_CONTRACT_CHANGE_NOTICE_CURRENT": date(2026, 6, 12),
    }

    for rule_id, expected_date in {**immediate, **delayed_four_months}.items():
        rule = db.scalar(
            select(LegalRuleVersion).where(
                LegalRuleVersion.rule_id == rule_id,
                LegalRuleVersion.version == 1,
            )
        )
        assert rule is not None, rule_id
        assert rule.valid_from == expected_date, rule_id
        assert rule.source_id == "RD88_2026", rule_id
