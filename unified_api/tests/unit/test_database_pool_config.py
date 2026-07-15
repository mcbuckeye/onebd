"""Role-configurable SQLAlchemy pool bounds."""

from unified_api.services import database


def test_database_engines_use_configured_pool_bounds(monkeypatch):
    database.close_all_connections()
    monkeypatch.setattr(database.settings, "db_pool_size", 2)
    monkeypatch.setattr(database.settings, "db_max_overflow", 1)
    monkeypatch.setattr(database.settings, "db_pool_timeout_seconds", 17)

    cortellis = database.get_cortellis_engine()
    edgar = database.get_edgar_source_engine()
    try:
        for engine in (cortellis, edgar):
            assert engine.pool.size() == 2
            assert engine.pool._max_overflow == 1
            assert engine.pool._timeout == 17
    finally:
        database.close_all_connections()
