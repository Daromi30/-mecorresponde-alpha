# Public auth registration boundary — synthetic-only demo

Status: implementation proposed for independent review. Base: GitHub `main=c5fa35eeebdde28e54cba9315015d5540a325798` (2026-09-30). This change does not authorize real beta, email delivery, new data capture, or a manual deployment.

## Architecture and decision

`POST /api/auth/register` now returns HTTP **503** with a generic message, without parsing credentials, taking a database dependency, or issuing a session. 503 describes temporary product unavailability rather than claiming the endpoint or all accounts no longer exist. This is a code-level, fail-closed boundary; there is no environment flag, header, query parameter, or test fixture exposed over HTTP that reopens it. Reopening requires a deliberate code change and review. Existing account records and sessions are untouched.

Only the `User` table is the account-creation source in the application. The remaining `issue_session` calls are for successful login and an existing account changing its password. The separate reviewer identity is a protected backoffice principal, not a public claimant account. The private real-beta invitation endpoint requires an already authenticated user and its independent gate remains closed. A future real-beta identity must be created or linked through a separately reviewed controlled admission flow, not by restoring generic public self-registration.

Tests that previously called public registration now seed **fictional historical accounts directly in their isolated test database** and authenticate through the real login endpoint. The helper is local to pytest's `TestClient`; it does not override or modify `/api/auth/register`. Public API tests call the actual closed route.

## Unknown-email minimization and threat model

Login first looks up the normalized email. For an absent account it performs the same 600,000-iteration PBKDF2 password work as a failed existing-account check and returns the same 401 JSON response. It no longer calls `login_throttle.fail`, so an unknown email cannot create a new `auth_throttle_state` row or other identity record. An existing account still gets the database-backed per-identity throttle and reaches 429 after the configured limit. No IP or replacement fingerprint is persisted. Old unknown-email digest rows, if any, are not migrated or bulk-deleted by this change; existing opportunistic throttle cleanup remains as before.

There is a deliberate residual tradeoff: once a **known** account is rate-limited, its 429 response differs from an **unknown** email's continuing 401 response. A reliable cross-worker 429 for unknown identities without storing a key or introducing another tracking mechanism conflicts with the no-new-unknown-fingerprint requirement. The immediate 401 path has matching public status/detail and comparable password computation, but this is **not** a claim of perfect enumeration resistance under repeated attack. WORK should review this tradeoff before merge. Throttling per existing account remains intact; this PR does not introduce IP tracking or weaken the configured identity limit.

`POST /api/auth/password-reset/request` and authenticated verification requests continue to return 503 before issuing email or tokens while transactional email is not operational. Existing valid confirmation tokens are not invalidated. If transactional email is enabled in a future separately reviewed block, the current reset-request throttle can retain an email-derived digest for an unknown email; that future surface requires its own minimization decision. This PR does not configure a provider.

## Preserved historical rights and limits

Existing fictional accounts remain able to login/logout, use `/me`, list own cases, export, change passwords, manage sessions, and delete the account and its associated records. Historical valid token confirmation paths remain in place. No migration, data rewrite, mass session revocation, email provider, Render setting, upload, payment, indexation, or Motor rule changes are included. The public closed-scenario demo remains separate.

Authentication of historical accounts still processes their email and credentials. Thus the service must **not** be described as globally unable to receive personal data. `PRIVATE_REAL_BETA` and real-data readiness remain **OFF / NOT READY**. All test identities are fictional; cost and real data introduced by this block are zero. Local untracked `storage/` is left untouched.
