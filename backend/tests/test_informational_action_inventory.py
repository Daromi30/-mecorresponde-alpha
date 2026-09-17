from __future__ import annotations

import inspect
import re

from app import services_v2 as svc
from app.action_contract import action_kind


_ACTION_LITERAL = re.compile(r"next_action\s*=\s*[\"']([A-Z0-9_]+)[\"']")


def test_inventory_informational_actions_before_terminal_lifecycle_contract():
    inventory = {
        family: sorted(
            action
            for action in set(_ACTION_LITERAL.findall(inspect.getsource(evaluator)))
            if action_kind(action) == "informational"
        )
        for family, evaluator in sorted(svc.EVALUATORS.items())
    }
    inventory = {family: actions for family, actions in inventory.items() if actions}
    assert not inventory, f"INFORMATIONAL_ACTION_INVENTORY={inventory}"
