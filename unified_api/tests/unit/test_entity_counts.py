"""Exact entity-count cache behavior."""

from datetime import datetime, timezone

from unified_api.services.entity_counts import get_entity_counts


class _Result:
    def __init__(self, *, first=None, one=None):
        self._first = first
        self._one = one

    def mappings(self):
        return self

    def first(self):
        return self._first

    def one(self):
        return self._one


class _CachedSession:
    def __init__(self):
        self.sql = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.sql.append(sql)
        if "FROM api_entity_counts" in sql:
            return _Result(
                first={
                    "deals": 172643,
                    "companies": 67177,
                    "assets": 33912,
                    "deal_linked_assets": 33896,
                    "refreshed_at": datetime(2026, 7, 15, tzinfo=timezone.utc),
                }
            )
        return _Result()


def test_fresh_entity_counts_do_not_scan_source_tables():
    session = _CachedSession()

    result = get_entity_counts(session)

    assert result["deals"] == 172643
    assert result["assets"] == 33912
    assert result["deal_linked_assets"] == 33896
    assert result["cache_hit"] is True
    assert result["root_population"] == "cortellis_deals"
    assert not any("COUNT(*) FROM deals" in sql for sql in session.sql)
