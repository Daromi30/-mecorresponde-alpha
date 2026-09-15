from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class FactValue:
    value: Any
    state: str = "asserted"
    user_confirmed: bool = False


@dataclass
class EngineResult:
    viability: str
    scope_status: str
    claimable_amount: float | None
    worth_pursuing: str
    reasoning_summary: str
    counterarguments: list[dict[str, Any]]
    missing_facts: list[str]
    next_action: str
    rule_result: str
    failed_conditions: list[str]
    calculation: dict[str, Any] | None
    sources: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def raw(facts: dict[str, FactValue], key: str, default=None):
    return facts.get(key).value if key in facts else default


def verified(facts: dict[str, FactValue], key: str) -> bool:
    f = facts.get(key)
    return bool(f and (f.state == "confirmed" or f.user_confirmed))
