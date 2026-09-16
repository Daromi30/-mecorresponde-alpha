from __future__ import annotations


# These namespaces are produced by trusted application components, not by a claimant.
# Keep this deny-list generic so future user-facing verticals do not need code changes.
RESERVED_USER_FACT_PREFIXES = (
    "system.",
    "legal.",
    "rule.",
    "decision.",
    "action.",
    "company.",
    "human.",
    "ai.",
    "internal.",
)


def normalize_user_fact_key(value: str) -> str:
    key = value.strip()
    if len(key) < 3 or len(key) > 160:
        raise ValueError("Fact key must contain between 3 and 160 characters")
    if "." not in key:
        raise ValueError("Fact key must use a namespaced form")
    folded = key.casefold()
    if folded.startswith(RESERVED_USER_FACT_PREFIXES):
        raise ValueError("Reserved fact namespace cannot be supplied by the case user")
    return key
