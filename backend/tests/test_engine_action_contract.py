from __future__ import annotations

import inspect
import re

from app import services_v2 as svc
from app.action_contract import action_kind, known_workflow_actions
from app.external_action_followup_policy import known_external_followup_actions


_ACTION_LITERAL = re.compile(r"next_action\s*=\s*[\"']([A-Z0-9_]+)[\"']")
_DIAGNOSED_KINDS = {
    "prepare_outbound",
    "guided_input",
    "evidence_input",
    "wait",
    "human_review",
    "reclassify",
    "assisted_redirect",
    "informational",
    "external_step",
    "terminal_resolution",
}


def _literal_actions(evaluator) -> set[str]:
    return set(_ACTION_LITERAL.findall(inspect.getsource(evaluator)))


def test_every_registered_evaluator_action_has_an_operational_contract():
    unknown: dict[str, list[str]] = {}
    families_without_literal_actions: list[str] = []

    for family, evaluator in sorted(svc.EVALUATORS.items()):
        actions = _literal_actions(evaluator)
        if not actions:
            families_without_literal_actions.append(family)
            continue
        unclassified = sorted(action for action in actions if action_kind(action) == "unknown")
        if unclassified:
            unknown[family] = unclassified

    assert not families_without_literal_actions, (
        "Every registered evaluator must expose literal next_action contracts so CI can audit them: "
        f"{families_without_literal_actions}"
    )
    assert not unknown, (
        "New Motor actions require an explicit operational class before they can ship. "
        f"Unclassified actions: {unknown}"
    )


def test_evaluator_actions_only_use_diagnosed_product_behaviors():
    unexpected: dict[str, dict[str, str]] = {}
    for family, evaluator in sorted(svc.EVALUATORS.items()):
        for action in sorted(_literal_actions(evaluator)):
            kind = action_kind(action)
            if kind not in _DIAGNOSED_KINDS:
                unexpected.setdefault(family, {})[action] = kind
    assert not unexpected, f"Evaluator actions escaped diagnosed-action behaviors: {unexpected}"


def test_every_external_step_has_a_resumable_followup_contract():
    evaluator_external_steps = {
        action
        for evaluator in svc.EVALUATORS.values()
        for action in _literal_actions(evaluator)
        if action_kind(action) == "external_step"
    }
    registered = set(known_external_followup_actions())

    assert evaluator_external_steps == registered, (
        "Every external Motor step must declare exactly how the claimant returns to the "
        "guided flow after doing it. Missing or stale follow-up registrations: "
        f"evaluator={sorted(evaluator_external_steps)}, registered={sorted(registered)}"
    )
    assert all(action_kind(action) == "external_step" for action in registered)


def test_workflow_actions_have_explicit_non_diagnostic_contracts():
    expected = {
        "SUBMIT_INITIAL_CLAIM": "workflow_submit",
        "WAIT_FOR_RESPONSE": "workflow_wait_response",
        "VERIFY_EXECUTION": "workflow_verify_execution",
        "HUMAN_REVIEW": "human_review",
    }
    assert set(known_workflow_actions()) == set(expected)
    assert {action: action_kind(action) for action in expected} == expected
