"""
Populate Neo4j graph database with Cortellis deals and companies.

This script syncs data from the Cortellis PostgreSQL database to Neo4j
for graph-based relationship queries.
"""
import sys
sys.path.insert(0, '/app')

from sqlalchemy import text
from unified_api.config import settings
from unified_api.services.database import get_cortellis_session
from unified_api.services.graph_sync import get_graph_sync_service


def populate_neo4j(batch_size: int = 1000, max_deals: int = None):
    """
    Populate Neo4j with Cortellis data.

    Args:
        batch_size: Number of records to process per batch
        max_deals: Maximum deals to sync (None = all)
    """
    graph_service = get_graph_sync_service()

    # Initialize schema (idempotent)
    print("Initializing Neo4j schema...")
    graph_service.initialize_schema()

    with get_cortellis_session() as session:
        # 1. Sync Companies
        print("\n=== Syncing Companies ===")
        count_result = session.execute(text("SELECT COUNT(*) FROM companies")).scalar()
        print(f"Total companies in Cortellis: {count_result}")

        offset = 0
        companies_synced = 0

        while True:
            result = session.execute(text("""
                SELECT id, name, company_type, hq_location
                FROM companies
                ORDER BY id
                LIMIT :limit OFFSET :offset
            """), {"limit": batch_size, "offset": offset})

            rows = result.fetchall()
            if not rows:
                break

            for row in rows:
                graph_service.create_company_node(
                    company_id=row.id,
                    name=row.name,
                    source="cortellis",
                    company_type=row.company_type,
                    hq_location=row.hq_location,
                )
                companies_synced += 1

            offset += batch_size
            print(f"  Synced {companies_synced} companies...")

        print(f"Total companies synced: {companies_synced}")

        # 2. Sync Deals
        print("\n=== Syncing Deals ===")
        deal_limit = f"LIMIT {max_deals}" if max_deals else ""
        count_result = session.execute(text(f"SELECT COUNT(*) FROM deals {deal_limit.replace('LIMIT', 'LIMIT 1 OFFSET') if deal_limit else ''}")).scalar()
        if max_deals:
            print(f"Syncing {max_deals} deals (of {count_result} total)")
        else:
            print(f"Total deals in Cortellis: {count_result}")

        offset = 0
        deals_synced = 0

        while True:
            if max_deals and offset >= max_deals:
                break

            result = session.execute(text(f"""
                SELECT d.id, d.title, d.deal_type, d.status, d.date_start::text as date_start,
                       f.total_projected_current_amount as total_value
                FROM deals d
                LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
                  AND f.total_projected_current_currency = 'USD'
                  AND f.total_projected_current_unit = 'Million'
                ORDER BY d.id
                LIMIT :limit OFFSET :offset
            """), {"limit": batch_size, "offset": offset})

            rows = result.fetchall()
            if not rows:
                break

            for row in rows:
                graph_service.create_deal_node(
                    deal_id=row.id,
                    source="cortellis",
                    deal_type=row.deal_type,
                    title=row.title,
                    announced_at=row.date_start,
                    status=row.status,
                    total_value=row.total_value,
                )
                deals_synced += 1

            offset += batch_size
            print(f"  Synced {deals_synced} deals...")

        print(f"Total deals synced: {deals_synced}")

        # 3. Create Deal-Company Relationships
        print("\n=== Creating Deal-Company Relationships ===")
        count_result = session.execute(text("SELECT COUNT(*) FROM deal_companies")).scalar()
        print(f"Total relationships to create: {count_result}")

        offset = 0
        rels_created = 0

        while True:
            result = session.execute(text("""
                SELECT deal_id, company_id, role
                FROM deal_companies
                ORDER BY deal_id, company_id
                LIMIT :limit OFFSET :offset
            """), {"limit": batch_size, "offset": offset})

            rows = result.fetchall()
            if not rows:
                break

            for row in rows:
                graph_service.create_deal_relationship(
                    deal_id=row.deal_id,
                    company_id=row.company_id,
                    role=row.role,
                    deal_source="cortellis",
                    company_source="cortellis",
                )
                rels_created += 1

            offset += batch_size
            if offset % (batch_size * 10) == 0:
                print(f"  Created {rels_created} relationships...")

        print(f"Total relationships created: {rels_created}")

    # Verify graph state
    print("\n=== Graph Summary ===")
    driver = graph_service._get_driver()
    with driver.session() as neo_session:
        result = neo_session.run("""
            MATCH (n)
            RETURN labels(n)[0] as label, count(*) as count
            ORDER BY count DESC
        """)
        for row in result:
            print(f"  {row['label']}: {row['count']} nodes")

        result = neo_session.run("""
            MATCH ()-[r]->()
            RETURN type(r) as rel_type, count(*) as count
            ORDER BY count DESC
        """)
        for row in result:
            print(f"  {row['rel_type']}: {row['count']} relationships")

    graph_service.close()
    print("\nDone!")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--max-deals", type=int, default=None, help="Limit deals to sync (for testing)")
    args = parser.parse_args()

    populate_neo4j(batch_size=args.batch_size, max_deals=args.max_deals)
