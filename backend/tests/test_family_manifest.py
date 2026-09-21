from app import services_v2 as svc
from app.family_bootstrap import install_all_families
from app.family_manifest import FAMILY_MANIFEST, family_title


def test_family_bootstrap_matches_manifest():
    codes = install_all_families()
    assert set(codes) == set(FAMILY_MANIFEST)
    assert len(codes) == len(FAMILY_MANIFEST)
    assert set(svc.EVALUATORS) == set(FAMILY_MANIFEST)
    assert set(svc.FAMILY_RULES) == set(FAMILY_MANIFEST)


def test_every_family_has_a_customer_title_and_legal_rule_mapping():
    install_all_families()
    for code, entry in FAMILY_MANIFEST.items():
        assert entry.title
        assert family_title(code) == entry.title
        assert entry.vertical in {"electricity", "purchases", "telecom", "travel", "banking", "rentals", "insurance", "automotive"}
        assert entry.rule_ids
        assert tuple(svc.FAMILY_RULES[code]) == entry.rule_ids
