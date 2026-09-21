from __future__ import annotations

import inspect
import re

from app import services_v2 as svc
from app.action_contract import action_kind


_ACTION_LITERAL = re.compile(r"next_action\s*=\s*[\"']([A-Z0-9_]+)[\"']")
_EXPECTED_INFORMATIONAL_ACTIONS = {
    "B01": ["EXPLAIN_B01_ALREADY_REFUNDED", "EXPLAIN_B01_AUTHORIZED_OPERATION_OTHER_ROUTE"],
    "B02": ["EXPLAIN_B02_ALREADY_REFUNDED"],
    "C01": ["EXPLAIN_NO_CONFORMITY_BASIS", "EXPLAIN_OUTSIDE_MANIFESTATION_PERIOD"],
    "C05": ["EXPLAIN_LATE_WITHDRAWAL", "EXPLAIN_WITHDRAWAL_PERIOD_EXPIRED"],
    "E01": ["EXPLAIN_DISCOUNT_APPLIED_AS_AGREED", "EXPLAIN_NO_PRICING_MISMATCH"],
    "E02-A": ["EXPLAIN_NO_OVERBILLING"],
    "E02-B": ["EXPLAIN_NO_DUPLICATE"],
    "E03": ["EXPLAIN_VALID_CONSENT"],
    "E04-A": ["EXPLAIN_CONSENT_EVIDENCE"],
    "E04-B": ["EXPLAIN_NO_CLAIMABLE_CHARGE", "EXPLAIN_NO_E04B_BASIS"],
    "E05": ["NO_MONETARY_PENALTY_TO_CHALLENGE"],
    "E06": ["EXPLAIN_ESTIMATION_ALLOWED", "EXPLAIN_REGULARIZATION_PERIOD_WITHIN_LIMIT"],
    "E07": ["EXPLAIN_PROCEDURALLY_COMPLIANT_PRICE_REVIEW", "EXPLAIN_VALID_NOTICE_AND_EXIT_RIGHT"],
    "T01": ["EXPLAIN_T01_ALREADY_COMPENSATED", "EXPLAIN_T01_STATUTORY_EXCLUSION"],
    "T02": ["EXPLAIN_T02_EXCLUDED_CHANGE", "EXPLAIN_T02_FREE_TERMINATION_OPTION"],
    "V01": [
        "EXPLAIN_V01_ALREADY_REFUNDED",
        "EXPLAIN_V01_NONPUBLIC_FARE_EXCLUSION",
        "EXPLAIN_V01_NO_CARRIER_CANCELLATION",
        "EXPLAIN_V01_NO_CONFIRMED_RESERVATION",
        "EXPLAIN_V01_REROUTING_CHOICE",
    ],
    "V02": [
        "EXPLAIN_V02_ALREADY_REFUNDED",
        "EXPLAIN_V02_DELAY_BELOW_FIVE_HOURS",
        "EXPLAIN_V02_NONPUBLIC_FARE_EXCLUSION",
        "EXPLAIN_V02_NO_CONFIRMED_RESERVATION",
        "EXPLAIN_V02_REFUND_OPTION_NOT_SELECTED",
    ],
    "V03": [
        "EXPLAIN_V03_ALREADY_COMPENSATED",
        "EXPLAIN_V03_NONPUBLIC_FARE_EXCLUSION",
        "EXPLAIN_V03_PRESENTATION_SCOPE_NOT_MET",
        "EXPLAIN_V03_REASONABLE_GROUND_EXCLUSION",
        "EXPLAIN_V03_VOLUNTARY_SURRENDER",
    ],
}


def test_informational_action_inventory_is_explicit_and_reviewed():
    inventory = {
        family: sorted(
            action
            for action in set(_ACTION_LITERAL.findall(inspect.getsource(evaluator)))
            if action_kind(action) == "informational"
        )
        for family, evaluator in sorted(svc.EVALUATORS.items())
    }
    inventory = {family: actions for family, actions in inventory.items() if actions}
    assert inventory == _EXPECTED_INFORMATIONAL_ACTIONS


def test_every_inventory_entry_uses_the_informational_contract():
    assert all(
        action_kind(action) == "informational"
        for actions in _EXPECTED_INFORMATIONAL_ACTIONS.values()
        for action in actions
    )
