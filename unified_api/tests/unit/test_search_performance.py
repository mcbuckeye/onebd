"""Startup coordination for search-performance schema changes."""

import unified_api.services.search_performance as search_performance
from unified_api.routers.search import CONTRACT_FULLTEXT_SQL


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class _Connection:
    def __init__(self, acquired):
        self.acquired = acquired
        self.statements = []

    def execution_options(self, **_options):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append((sql, params))
        if "pg_try_advisory_lock" in sql:
            return _ScalarResult(self.acquired)
        raise AssertionError(f"unexpected SQL after lock contention: {sql}")


class _Engine:
    def __init__(self, connection):
        self.connection = connection

    def connect(self):
        return self.connection


def test_non_owner_worker_does_not_block_or_run_schema_changes(monkeypatch):
    connection = _Connection(acquired=False)
    monkeypatch.setattr(
        search_performance,
        "get_cortellis_engine",
        lambda: _Engine(connection),
    )

    search_performance.ensure_search_performance_schema()

    assert len(connection.statements) == 1
    sql, params = connection.statements[0]
    assert "pg_try_advisory_lock" in sql
    assert params == {"lock_id": search_performance.ADVISORY_LOCK_ID}


def test_contract_search_indexes_are_part_of_current_schema_version():
    statements = "\n".join(search_performance.INDEX_STATEMENTS)

    assert search_performance.SEARCH_SCHEMA_VERSION >= 4
    assert "contract_chunks USING ivfflat" in statements
    assert "embedding vector_cosine_ops" in statements
    assert "contract_chunks USING gin" in statements
    assert "to_tsvector('english', content)" in statements


def test_contract_fulltext_bounds_candidates_before_ranking():
    matched_cte = CONTRACT_FULLTEXT_SQL.split("), diverse AS", 1)[0]

    assert "LIMIT :candidate_limit" in matched_cte
    assert "ORDER BY rank" not in matched_cte
    assert "ORDER BY cc.rank DESC" in CONTRACT_FULLTEXT_SQL
