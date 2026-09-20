from sqlalchemy.dialects import postgresql, sqlite

from app.case_locking import case_for_update_statement


def test_case_mutation_lock_compiles_for_postgresql_but_remains_sqlite_compatible():
    statement = case_for_update_statement("case-123")

    postgres_sql = str(statement.compile(dialect=postgresql.dialect()))
    sqlite_sql = str(statement.compile(dialect=sqlite.dialect()))

    assert "FOR UPDATE" in postgres_sql
    assert "FOR UPDATE" not in sqlite_sql
    assert "cases.id" in postgres_sql
    assert "cases.id" in sqlite_sql
