from __future__ import annotations

from . import services_v2 as svc
from .energy_billing_contract_extensions import install_energy_billing_contract_extensions
from .energy_extensions import install_energy_extensions
from .energy_pricing_extensions import install_energy_pricing_extensions
from .family_manifest import FAMILY_MANIFEST, supported_family_codes
from .purchase_extensions import install_purchase_extensions

_INSTALLED = False


def install_all_families() -> tuple[str, ...]:
    """Install every supported resolution family and fail fast if the runtime registry drifts.

    The legacy extension modules still provide some family-specific renderers/questions,
    but startup has a single entry point and a single manifest. New verticals should be
    added through this boundary instead of adding imports to ``main.py``.
    """
    global _INSTALLED
    if not _INSTALLED:
        install_purchase_extensions()
        install_energy_extensions()
        install_energy_billing_contract_extensions()
        install_energy_pricing_extensions()
        _INSTALLED = True

    expected = set(supported_family_codes())
    evaluators = set(svc.EVALUATORS)
    rule_families = set(svc.FAMILY_RULES)

    missing_evaluators = sorted(expected - evaluators)
    missing_rule_maps = sorted(expected - rule_families)
    unexpected = sorted((evaluators | rule_families) - expected)

    if missing_evaluators or missing_rule_maps or unexpected:
        raise RuntimeError(
            "Family registry drift: "
            f"missing_evaluators={missing_evaluators}, "
            f"missing_rule_maps={missing_rule_maps}, "
            f"unexpected={unexpected}"
        )

    for code, entry in FAMILY_MANIFEST.items():
        actual_rules = tuple(svc.FAMILY_RULES.get(code, []))
        if actual_rules != entry.rule_ids:
            raise RuntimeError(
                f"Family rule drift for {code}: manifest={entry.rule_ids}, runtime={actual_rules}"
            )

    return tuple(sorted(expected))
