from pathlib import Path

from sqlalchemy.dialects import postgresql, sqlite

from app.case_locking import case_for_update_statement


ROOT = Path(__file__).parents[1] / "app" / "routers"


def _function_source(path: str, name: str) -> str:
    source = (ROOT / path).read_text(encoding="utf-8")
    markers = (f"def {name}(", f"async def {name}(")
    starts = [source.find(marker) for marker in markers if source.find(marker) >= 0]
    assert starts, f"{name} missing from {path}"
    start = min(starts)
    next_route = source.find("\n@router.", start)
    return source[start:] if next_route < 0 else source[start:next_route]


def test_case_mutation_lock_compiles_for_postgresql_but_remains_sqlite_compatible():
    statement = case_for_update_statement("case-123")

    postgres_sql = str(statement.compile(dialect=postgresql.dialect()))
    sqlite_sql = str(statement.compile(dialect=sqlite.dialect()))

    assert "FOR UPDATE" in postgres_sql
    assert "FOR UPDATE" not in sqlite_sql
    assert "cases.id" in postgres_sql
    assert "cases.id" in sqlite_sql


def test_claimant_case_mutations_lock_the_case_before_state_changes():
    for name in (
        "fact",
        "charges",
        "documents",
        "document_fact",
        "run_diagnosis",
        "prepare_claim",
        "submission",
        "response",
        "complete_review",
        "outcome",
    ):
        assert "case_for_update_or_404(db, case_id)" in _function_source("cases_v2.py", name)


def test_cross_router_case_mutations_share_the_same_locking_contract():
    checks = {
        "quality.py": ("evidenced_company_response", "evidenced_outcome"),
        "wait_resume.py": ("resume_wait",),
        "account_cases.py": ("claim_case",),
        "admin_review_resolution.py": (
            "reclassify_unsupported_review",
            "escalate_post_response_review_to_professional",
            "resolve_structured_review",
        ),
        "case_deletion.py": ("delete_case",),
    }
    for path, names in checks.items():
        for name in names:
            assert "lock_case_for_update(db," in _function_source(path, name)
