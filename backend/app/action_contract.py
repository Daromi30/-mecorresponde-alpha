from __future__ import annotations

from typing import Literal


ActionKind = Literal[
    "prepare_outbound",
    "guided_input",
    "wait",
    "human_review",
    "reclassify",
    "assisted_redirect",
    "informational",
    "external_step",
    "terminal_resolution",
    "workflow_submit",
    "workflow_wait_response",
    "workflow_verify_execution",
    "unknown",
]


_EXACT_KINDS: dict[str, ActionKind] = {
    "GIVE_ADDITIONAL_DELIVERY_PERIOD": "prepare_outbound",
    "SEND_WITHDRAWAL_NOTICE": "prepare_outbound",
    "RETURN_GOODS_WITH_PROOF": "external_step",
    "CHECK_BILL_AGAINST_REAL_READING": "external_step",
    "VERIFY_AND_CLOSE_WITHDRAWAL": "terminal_resolution",
    "SUBMIT_INITIAL_CLAIM": "workflow_submit",
    "WAIT_FOR_RESPONSE": "workflow_wait_response",
    "VERIFY_EXECUTION": "workflow_verify_execution",
    "HUMAN_REVIEW": "human_review",
}

_PREFIX_KINDS: tuple[tuple[str, ActionKind], ...] = (
    ("PREPARE_", "prepare_outbound"),
    ("ASK_", "guided_input"),
    ("REQUEST_", "guided_input"),
    ("CONFIRM_", "guided_input"),
    ("CORRECT_", "guided_input"),
    ("CHOOSE_", "guided_input"),
    ("WAIT_", "wait"),
    ("HUMAN_REVIEW_", "human_review"),
    ("RECLASSIFY_", "reclassify"),
    ("REDIRECT_", "assisted_redirect"),
    ("EXPLAIN_", "informational"),
    ("NO_", "informational"),
    # Monitoring is only useful if a later real-world change can be fed back into the
    # Motor. Treat every MONITOR_* action as an external step so CI requires an explicit
    # follow-up contract instead of allowing a passive dead-end card.
    ("MONITOR_", "external_step"),
    ("CHECK_", "informational"),
)


def action_kind(action_type: str | None) -> ActionKind:
    """Classify an action by the product behavior required to make it executable.

    The Motor may add new families without teaching the browser about every family code, but
    it may not add a new operational behavior silently. CI enumerates evaluator outputs and
    rejects every action that returns ``unknown`` here.
    """
    normalized = str(action_type or "").strip().upper()
    if not normalized:
        return "unknown"
    exact = _EXACT_KINDS.get(normalized)
    if exact is not None:
        return exact
    for prefix, kind in _PREFIX_KINDS:
        if normalized.startswith(prefix):
            return kind
    return "unknown"


def known_workflow_actions() -> tuple[str, ...]:
    """Actions created by workflow orchestration rather than a family evaluator."""
    return (
        "SUBMIT_INITIAL_CLAIM",
        "WAIT_FOR_RESPONSE",
        "VERIFY_EXECUTION",
        "HUMAN_REVIEW",
    )
