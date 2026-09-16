from __future__ import annotations

from datetime import datetime, timezone

from . import services_v2 as svc
from .engine.guarded_gateway import GuardedModelGateway
from .family_manifest import FAMILY_MANIFEST, supported_family_codes
from .legal_source_registry import reconcile_legal_sources

_INSTALLED = False


def install_all_families() -> tuple[str, ...]:
    """Install every supported resolution family and fail fast on registry drift.

    Imports are deliberately lazy and sequential. The current extension modules wrap
    functions from ``services_v2`` at import time, so importing every extension before
    installing the previous one would make them all capture the same base functions and
    break the wrapper chain. This boundary preserves the current behaviour while giving
    startup a single multivertical entry point. New families should ultimately register
    directly here instead of adding another wrapper layer.
    """
    global _INSTALLED
    if not _INSTALLED:
        # Any present or future model provider must pass through the strict structured
        # intelligence boundary before its output can reach the resolution engine.
        if not isinstance(svc.gateway, GuardedModelGateway):
            svc.gateway = GuardedModelGateway(svc.gateway)

        from .purchase_extensions import install_purchase_extensions

        install_purchase_extensions()

        from .energy_extensions import install_energy_extensions

        install_energy_extensions()

        from .energy_billing_contract_extensions import install_energy_billing_contract_extensions

        install_energy_billing_contract_extensions()

        from .energy_pricing_extensions import install_energy_pricing_extensions

        install_energy_pricing_extensions()

        # Extension modules have now built the final seed wrapper chain. Add provenance
        # reconciliation last so corrections to official source metadata are also applied
        # to databases that already contain the source rows.
        previous_seed = svc.seed_legal

        def seed_with_reviewed_provenance(db):
            rules = previous_seed(db)
            reconcile_legal_sources(db)
            return rules

        svc.seed_legal = seed_with_reviewed_provenance

        # Claim-package rendering is also installed at the final multivertical boundary.
        # Existing renderers remain untouched; missing families are served by the registry.
        # The wrapper additionally makes package preparation idempotent and closes the
        # diagnostic action that preceded a successfully prepared submission package.
        from .claim_packages import EXTENDED_CLAIM_FAMILIES, prepare_extended_claim_package
        from .models import Action

        previous_prepare_claim = svc.prepare_claim_package

        def prepare_claim_for_all_families(db, case):
            current = db.get(Action, case.current_action_id) if case.current_action_id else None
            if (
                current is not None
                and current.case_id == case.id
                and current.type == "SUBMIT_INITIAL_CLAIM"
                and current.status == "READY"
            ):
                return {"action_id": current.id, **(current.payload_json or {})}

            if (case.family or "") in EXTENDED_CLAIM_FAMILIES:
                return prepare_extended_claim_package(db, case)

            preceding = current
            result = previous_prepare_claim(db, case)
            if (
                preceding is not None
                and preceding.id != result.get("action_id")
                and preceding.status != "COMPLETED"
            ):
                preceding.status = "COMPLETED"
                preceding.completed_at = datetime.now(timezone.utc)
                db.commit()
            return result

        svc.prepare_claim_package = prepare_claim_for_all_families
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
