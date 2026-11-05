# RB-031 dependency hardening

RB-031 makes the Python dependency baseline reproducible without changing any
runtime feature flag or enabling the real beta.

## Enforced baseline

- `backend/requirements.txt` remains the human-maintained direct dependency
  policy.
- `backend/requirements.lock` contains the fully resolved dependency graph with
  exact versions and SHA-256 hashes.
- GitHub Actions and Render install only the lock with `--require-hashes` and
  run `pip check` after installation.
- Third-party GitHub Actions are pinned to immutable commit SHAs, with their
  reviewed major versions retained as comments.
- The Render service remains on the free plan and all runtime gates keep their
  closed defaults.

The inventory review on 2026-10-30 found that the former `pypdf>=5.9,<6`
constraint forced a version with known vulnerabilities. The direct policy now
requires `pypdf>=6.21.2,<7`; the existing PDF reader behavior is covered by
regression tests. `pip-audit 2.10.1` reported no known vulnerabilities in the
resulting complete lock at the time of review.

## Controlled update procedure

1. Change only the necessary direct constraint in `requirements.txt`.
2. Regenerate the lock with `pip-compile --upgrade --generate-hashes
   --strip-extras --no-emit-index-url --no-emit-trusted-host`.
3. Review the resolved diff and run `pip-audit` against the lock.
4. Install the lock with `--require-hashes`, run `pip check`, and execute the
   full relevant test suite before review.

No credentials, connection strings, private documentation, real data, provider
configuration, or automatic secret rotation belong in this process.
