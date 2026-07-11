"""Remove only proven-equivalent legacy EDGAR indexes without blocking writes."""

from sqlalchemy import text

from unified_api.services.database import get_edgar_source_engine


def main() -> int:
    engine = get_edgar_source_engine()
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT ci.relname AS index_name,
                   pg_get_expr(i.indexprs, i.indrelid) AS expression,
                   i.indclass::text AS operator_classes
            FROM pg_index i
            JOIN pg_class ci ON ci.oid = i.indexrelid
            WHERE ci.relname IN ('chunks_text_search_idx', 'idx_chunks_text_search')
            ORDER BY ci.relname
        """)).mappings().all()

    by_name = {row["index_name"]: row for row in rows}
    legacy = by_name.get("chunks_text_search_idx")
    retained = by_name.get("idx_chunks_text_search")
    if legacy is None:
        print("EDGAR indexes already optimized")
        return 0
    if retained is None:
        raise RuntimeError("Refusing to remove the only EDGAR full-text index")
    if (
        legacy["expression"] != retained["expression"]
        or legacy["operator_classes"] != retained["operator_classes"]
    ):
        raise RuntimeError("Refusing to remove non-equivalent EDGAR indexes")

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("DROP INDEX CONCURRENTLY chunks_text_search_idx"))
    print("Removed duplicate chunks_text_search_idx; retained idx_chunks_text_search")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
