# Technical legal-rule governance

MECORRESPONDE keeps technical execution and professional legal approval as separate states.

- `technical_draft` may be executed only in `SYNTHETIC` cases so the product can be built and tested end to end.
- Neither `approved` nor legacy free-text `reviewed_by` constitutes verifiable professional approval.
- Any non-synthetic case fails closed. Operational case-release approval remains a separate control and never approves a rule globally or substitutes for professional legal evidence.
- Participant-facing substantive output uses one central gate. It binds the current, non-invalidated decision to the current facts and operational review, then verifies every exact rule version against professional evidence. Because no such verifiable professional-evidence model exists yet, the gate is always closed for real cases.
- `SYNTHETIC` is the only mode with implicit participant-output authority. Unknown or future modes inherit no authority: participant detail, exports, sources, quality, timeline, communications, handoff and substantive actions all fail closed until explicitly governed.
- Completing operational review returns `OPERATIONAL_REVIEW_APPROVED`, never `RELEASED`, while substantive approval is absent. Case detail, account export, legal sources, quality, timeline, handoff, claim preparation and submission remain fail-closed; the participant's own factual inputs remain accessible.
- A future professional workflow must bind authenticated authority and verifiable evidence to the exact rule-version id. It is intentionally not activated by this batch.
- Public SEO pages only cite professionally approved rules.
- Internal readiness reports technical catalog completeness separately from professional approval. A complete synthetic catalog does not make the product ready for real data.

Migration downgrade preserves `technical_draft`; it never recreates an `approved` value that cannot be evidenced. This control changes no substantive rule, deadline, remedy, probability, or legal interpretation. `LEGAL_APPROVAL` remains `PENDING`, and `REAL_BETA` remains closed.
