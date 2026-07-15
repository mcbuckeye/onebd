"""
PostgreSQL to Neo4j sync service

Syncs companies, deals, and relationships from both Cortellis and Edgar BD
databases to Neo4j graph database for relationship queries.

Imported from Edgar BD project and adapted for unified platform.
"""
from typing import Optional
import structlog

logger = structlog.get_logger(__name__)


class GraphSyncService:
    """Service for syncing PostgreSQL data to Neo4j"""

    def __init__(self, neo4j_uri: str, neo4j_user: str, neo4j_password: str):
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self._driver = None

        logger.info("GraphSyncService initialized", uri=neo4j_uri)

    def _get_driver(self):
        """Get or create Neo4j driver"""
        if self._driver is None:
            from neo4j import GraphDatabase
            self._driver = GraphDatabase.driver(
                self.neo4j_uri,
                auth=(self.neo4j_user, self.neo4j_password)
            )
        return self._driver

    def close(self):
        """Close the Neo4j driver connection"""
        if self._driver:
            self._driver.close()
            self._driver = None

    def initialize_schema(self):
        """Create indexes and constraints in Neo4j"""
        driver = self._get_driver()

        with driver.session() as session:
            # Company constraints and indexes
            session.run("""
                CREATE CONSTRAINT company_id IF NOT EXISTS
                FOR (c:Company) REQUIRE c.id IS UNIQUE
            """)
            session.run("""
                CREATE INDEX company_cik IF NOT EXISTS
                FOR (c:Company) ON (c.cik)
            """)
            session.run("""
                CREATE INDEX company_ticker IF NOT EXISTS
                FOR (c:Company) ON (c.ticker)
            """)

            # Deal constraints
            session.run("""
                CREATE CONSTRAINT deal_id IF NOT EXISTS
                FOR (d:Deal) REQUIRE (d.source, d.id) IS UNIQUE
            """)

            # Asset constraints
            session.run("""
                CREATE CONSTRAINT asset_id IF NOT EXISTS
                FOR (a:Asset) REQUIRE a.id IS UNIQUE
            """)

            # Indication constraints
            session.run("""
                CREATE CONSTRAINT indication_id IF NOT EXISTS
                FOR (i:Indication) REQUIRE i.id IS UNIQUE
            """)

            # Filing constraints (for Edgar documents)
            session.run("""
                CREATE CONSTRAINT filing_accession IF NOT EXISTS
                FOR (f:Filing) REQUIRE f.accession_no IS UNIQUE
            """)

        logger.info("Neo4j schema initialized")

    def create_company_node(
        self,
        company_id: int,
        name: str,
        source: str = "cortellis",
        ticker: Optional[str] = None,
        cik: Optional[str] = None,
        company_type: Optional[str] = None,
        hq_location: Optional[str] = None,
        xref_id: Optional[int] = None,
    ):
        """
        Create or update a company node in Neo4j

        Args:
            company_id: Company ID from source database
            name: Company name
            source: Source database ('cortellis' or 'edgar')
            ticker: Stock ticker
            cik: SEC CIK number
            company_type: Type of company
            hq_location: Headquarters location
            xref_id: Cross-reference ID linking both sources
        """
        driver = self._get_driver()

        with driver.session() as session:
            session.run("""
                MERGE (c:Company {source: $source, id: $company_id})
                SET c.name = $name,
                    c.ticker = $ticker,
                    c.cik = $cik,
                    c.company_type = $company_type,
                    c.hq_location = $hq_location,
                    c.xref_id = $xref_id,
                    c.updated_at = datetime()
            """, {
                "source": source,
                "company_id": company_id,
                "name": name,
                "ticker": ticker,
                "cik": cik,
                "company_type": company_type,
                "hq_location": hq_location,
                "xref_id": xref_id,
            })

        logger.debug("Company node created/updated", company_id=company_id, name=name, source=source)

    def create_deal_node(
        self,
        deal_id: int,
        source: str = "cortellis",
        deal_type: Optional[str] = None,
        title: Optional[str] = None,
        announced_at: Optional[str] = None,
        status: Optional[str] = None,
        total_value: Optional[float] = None,
    ):
        """
        Create or update a deal node in Neo4j

        Args:
            deal_id: Deal ID from source database
            source: Source database ('cortellis' or 'edgar')
            deal_type: Type of deal (M&A, License, etc.)
            title: Deal title
            announced_at: Announcement date (ISO format)
            status: Deal status
            total_value: Current projected total in USD millions, when disclosed
        """
        driver = self._get_driver()

        with driver.session() as session:
            session.run("""
                MERGE (d:Deal {source: $source, id: $deal_id})
                SET d.deal_type = $deal_type,
                    d.title = $title,
                    d.announced_at = $announced_at,
                    d.status = $status,
                    d.total_value = $total_value,
                    d.updated_at = datetime()
            """, {
                "source": source,
                "deal_id": deal_id,
                "deal_type": deal_type,
                "title": title,
                "announced_at": announced_at,
                "status": status,
                "total_value": total_value,
            })

        logger.debug("Deal node created/updated", deal_id=deal_id, source=source)

    def create_deal_relationship(
        self,
        deal_id: int,
        company_id: int,
        role: str,
        deal_source: str = "cortellis",
        company_source: str = "cortellis",
    ):
        """
        Create a relationship between a company and a deal

        Args:
            deal_id: Deal ID
            company_id: Company ID
            role: Relationship type (e.g., 'principal', 'partner', 'acquirer', 'target')
            deal_source: Source database for deal
            company_source: Source database for company
        """
        driver = self._get_driver()

        # Map roles to relationship types
        rel_type_map = {
            "principal": "LICENSES_OUT",
            "partner": "LICENSES_IN",
            "acquirer": "ACQUIRES",
            "target": "ACQUIRED_BY",
            "licensor": "LICENSES_OUT",
            "licensee": "LICENSES_IN",
        }

        rel_type = rel_type_map.get(role.lower(), "PARTICIPATES_IN")

        with driver.session() as session:
            session.run(f"""
                MATCH (c:Company {{source: $company_source, id: $company_id}})
                MATCH (d:Deal {{source: $deal_source, id: $deal_id}})
                MERGE (c)-[r:{rel_type}]->(d)
                SET r.role = $role, r.updated_at = datetime()
            """, {
                "company_source": company_source,
                "company_id": company_id,
                "deal_source": deal_source,
                "deal_id": deal_id,
                "role": role,
            })

        logger.debug(
            "Deal relationship created",
            company_id=company_id,
            deal_id=deal_id,
            role=role,
            rel_type=rel_type,
        )

    def create_filing_node(
        self,
        document_id: int,
        accession_no: str,
        company_id: int,
        form_type: str,
        filing_date: Optional[str] = None,
        url: Optional[str] = None,
    ):
        """
        Create a filing node (from Edgar BD)

        Args:
            document_id: Document ID from Edgar DB
            accession_no: SEC accession number
            company_id: Company ID
            form_type: Form type (8-K, 10-K, etc.)
            filing_date: Filing date (ISO format)
            url: URL to filing
        """
        driver = self._get_driver()

        with driver.session() as session:
            session.run("""
                MERGE (f:Filing {accession_no: $accession_no})
                SET f.document_id = $document_id,
                    f.form_type = $form_type,
                    f.filing_date = $filing_date,
                    f.url = $url,
                    f.updated_at = datetime()
            """, {
                "accession_no": accession_no,
                "document_id": document_id,
                "form_type": form_type,
                "filing_date": filing_date,
                "url": url,
            })

            # Link filing to company
            session.run("""
                MATCH (c:Company {source: 'edgar', id: $company_id})
                MATCH (f:Filing {accession_no: $accession_no})
                MERGE (c)-[:HAS_FILING]->(f)
            """, {
                "company_id": company_id,
                "accession_no": accession_no,
            })

        logger.debug("Filing node created", accession_no=accession_no, form_type=form_type)

    def link_deal_to_filing(
        self,
        deal_id: int,
        deal_source: str,
        accession_no: str,
    ):
        """
        Link a deal to an SEC filing

        Args:
            deal_id: Deal ID
            deal_source: Source database for deal
            accession_no: SEC accession number
        """
        driver = self._get_driver()

        with driver.session() as session:
            session.run("""
                MATCH (d:Deal {source: $deal_source, id: $deal_id})
                MATCH (f:Filing {accession_no: $accession_no})
                MERGE (d)-[:HAS_FILING]->(f)
            """, {
                "deal_source": deal_source,
                "deal_id": deal_id,
                "accession_no": accession_no,
            })

        logger.debug("Deal-filing link created", deal_id=deal_id, accession_no=accession_no)

    def get_company_network(
        self,
        company_id: int,
        source: str = "cortellis",
        depth: int = 1,
    ) -> dict:
        """
        Get partnership network for a company

        Args:
            company_id: Company ID
            source: Source database
            depth: Network depth (1-3)

        Returns:
            Dict with nodes and edges for visualization
        """
        driver = self._get_driver()

        with driver.session() as session:
            result = session.run("""
                MATCH (c:Company {source: $source, id: $company_id})
                CALL apoc.path.subgraphAll(c, {
                    relationshipFilter: ">|<",
                    maxLevel: $depth
                })
                YIELD nodes, relationships
                RETURN nodes, relationships
            """, {
                "source": source,
                "company_id": company_id,
                "depth": depth,
            })

            record = result.single()
            if not record:
                return {"nodes": [], "edges": []}

            nodes = []
            for node in record["nodes"]:
                nodes.append({
                    "id": f"{list(node.labels)[0]}_{node.get('id', node.id)}",
                    "label": list(node.labels)[0],
                    "name": node.get("name", node.get("title", "")),
                    "properties": dict(node),
                })

            edges = []
            for rel in record["relationships"]:
                edges.append({
                    "source": f"{list(rel.start_node.labels)[0]}_{rel.start_node.get('id', rel.start_node.id)}",
                    "target": f"{list(rel.end_node.labels)[0]}_{rel.end_node.get('id', rel.end_node.id)}",
                    "relationship": rel.type,
                    "properties": dict(rel),
                })

            return {"nodes": nodes, "edges": edges}

    def find_path_between_companies(
        self,
        from_company_id: int,
        to_company_id: int,
        from_source: str = "cortellis",
        to_source: str = "cortellis",
        max_hops: int = 3,
    ) -> list:
        """
        Find shortest path between two companies through deals

        Args:
            from_company_id: Starting company ID
            to_company_id: Ending company ID
            from_source: Source database for starting company
            to_source: Source database for ending company
            max_hops: Maximum path length

        Returns:
            List of paths (each path is a list of nodes/relationships)
        """
        driver = self._get_driver()

        with driver.session() as session:
            result = session.run("""
                MATCH (start:Company {source: $from_source, id: $from_company_id})
                MATCH (end:Company {source: $to_source, id: $to_company_id})
                MATCH path = shortestPath((start)-[*1..$max_hops]-(end))
                RETURN path
                LIMIT 5
            """, {
                "from_source": from_source,
                "from_company_id": from_company_id,
                "to_source": to_source,
                "to_company_id": to_company_id,
                "max_hops": max_hops,
            })

            paths = []
            for record in result:
                path = record["path"]
                path_data = []
                for item in path:
                    if hasattr(item, "labels"):
                        # Node
                        path_data.append({
                            "type": "node",
                            "label": list(item.labels)[0],
                            "properties": dict(item),
                        })
                    else:
                        # Relationship
                        path_data.append({
                            "type": "relationship",
                            "rel_type": item.type,
                            "properties": dict(item),
                        })
                paths.append(path_data)

            return paths


    def sync_cortellis_companies(self, batch_size: int = 1000, limit: Optional[int] = None):
        """
        Bulk sync Cortellis companies to Neo4j.

        Args:
            batch_size: Number of companies per batch
            limit: Maximum companies to sync (None for all)
        """
        from sqlalchemy import text
        from unified_api.services.database import get_cortellis_session

        driver = self._get_driver()
        total_synced = 0

        with get_cortellis_session() as session:
            # Get total count
            count_result = session.execute(text("SELECT COUNT(*) FROM companies"))
            total_count = count_result.scalar()

            if limit:
                total_count = min(total_count, limit)

            logger.info("Starting Cortellis company sync", total=total_count)

            offset = 0
            while offset < total_count:
                # Fetch batch
                result = session.execute(text("""
                    SELECT
                        c.id,
                        c.name,
                        c.company_type,
                        c.hq_location,
                        cx.id as xref_id,
                        COALESCE(cx.ticker, c.ticker) as ticker,
                        COALESCE(cx.cik, c.cik) as cik
                    FROM companies c
                    LEFT JOIN company_xref cx ON cx.cortellis_id = c.id
                    ORDER BY c.id
                    LIMIT :limit OFFSET :offset
                """), {"limit": batch_size, "offset": offset})

                companies = result.fetchall()
                if not companies:
                    break

                # Bulk insert to Neo4j
                with driver.session() as neo4j_session:
                    neo4j_session.run("""
                        UNWIND $companies as company
                        MERGE (c:Company {source: 'cortellis', id: company.id})
                        SET c.name = company.name,
                            c.company_type = company.company_type,
                            c.hq_location = company.hq_location,
                            c.xref_id = company.xref_id,
                            c.ticker = company.ticker,
                            c.cik = company.cik,
                            c.updated_at = datetime()
                    """, {"companies": [
                        {
                            "id": c.id,
                            "name": c.name,
                            "company_type": c.company_type,
                            "hq_location": c.hq_location,
                            "xref_id": c.xref_id,
                            "ticker": c.ticker,
                            "cik": c.cik,
                        }
                        for c in companies
                    ]})

                total_synced += len(companies)
                offset += batch_size
                logger.info("Company sync progress", synced=total_synced, total=total_count)

        logger.info("Cortellis company sync complete", total_synced=total_synced)
        return total_synced

    def sync_cortellis_deals(self, batch_size: int = 1000, limit: Optional[int] = None):
        """
        Bulk sync Cortellis deals to Neo4j.

        Args:
            batch_size: Number of deals per batch
            limit: Maximum deals to sync (None for all)
        """
        from sqlalchemy import text
        from unified_api.services.database import get_cortellis_session

        driver = self._get_driver()
        total_synced = 0

        with get_cortellis_session() as session:
            # Get total count
            count_result = session.execute(text("SELECT COUNT(*) FROM deals"))
            total_count = count_result.scalar()

            if limit:
                total_count = min(total_count, limit)

            logger.info("Starting Cortellis deal sync", total=total_count)

            offset = 0
            while offset < total_count:
                # Fetch batch of deals
                result = session.execute(text("""
                    SELECT
                        d.id,
                        d.title,
                        d.deal_type,
                        d.status,
                        d.date_start::text as announced_at,
                        f.total_projected_current_amount as total_value
                    FROM deals d
                    LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
                      AND f.total_projected_current_currency = 'USD'
                      AND f.total_projected_current_unit = 'Million'
                    ORDER BY d.id
                    LIMIT :limit OFFSET :offset
                """), {"limit": batch_size, "offset": offset})

                deals = result.fetchall()
                if not deals:
                    break

                # Bulk insert deals to Neo4j
                with driver.session() as neo4j_session:
                    neo4j_session.run("""
                        UNWIND $deals as deal
                        MERGE (d:Deal {source: 'cortellis', id: deal.id})
                        SET d.title = deal.title,
                            d.deal_type = deal.deal_type,
                            d.status = deal.status,
                            d.announced_at = deal.announced_at,
                            d.total_value = deal.total_value,
                            d.updated_at = datetime()
                    """, {"deals": [
                        {
                            "id": d.id,
                            "title": d.title,
                            "deal_type": d.deal_type,
                            "status": d.status,
                            "announced_at": d.announced_at,
                            "total_value": d.total_value,
                        }
                        for d in deals
                    ]})

                total_synced += len(deals)
                offset += batch_size
                logger.info("Deal sync progress", synced=total_synced, total=total_count)

        logger.info("Cortellis deal sync complete", total_synced=total_synced)
        return total_synced

    def sync_deal_relationships(self, batch_size: int = 5000, limit: Optional[int] = None):
        """
        Bulk sync deal-company relationships to Neo4j.

        Args:
            batch_size: Number of relationships per batch
            limit: Maximum relationships to sync (None for all)
        """
        from sqlalchemy import text
        from unified_api.services.database import get_cortellis_session

        driver = self._get_driver()
        total_synced = 0

        with get_cortellis_session() as session:
            # Get total count
            count_result = session.execute(text("SELECT COUNT(*) FROM deal_companies"))
            total_count = count_result.scalar()

            if limit:
                total_count = min(total_count, limit)

            logger.info("Starting deal relationship sync", total=total_count)

            offset = 0
            while offset < total_count:
                # Fetch batch
                result = session.execute(text("""
                    SELECT
                        dc.deal_id,
                        dc.company_id,
                        dc.role
                    FROM deal_companies dc
                    ORDER BY dc.deal_id, dc.company_id
                    LIMIT :limit OFFSET :offset
                """), {"limit": batch_size, "offset": offset})

                relationships = result.fetchall()
                if not relationships:
                    break

                # Group by role for efficient Neo4j queries
                role_groups = {}
                for rel in relationships:
                    role = rel.role.lower() if rel.role else "participant"
                    if role not in role_groups:
                        role_groups[role] = []
                    role_groups[role].append({
                        "deal_id": rel.deal_id,
                        "company_id": rel.company_id,
                    })

                # Create relationships for each role type
                with driver.session() as neo4j_session:
                    for role, rels in role_groups.items():
                        # Map roles to relationship types
                        rel_type = {
                            "principal": "LICENSES_OUT",
                            "partner": "LICENSES_IN",
                            "acquirer": "ACQUIRES",
                            "target": "ACQUIRED_BY",
                            "licensor": "LICENSES_OUT",
                            "licensee": "LICENSES_IN",
                        }.get(role, "PARTICIPATES_IN")

                        neo4j_session.run(f"""
                            UNWIND $rels as rel
                            MATCH (c:Company {{source: 'cortellis', id: rel.company_id}})
                            MATCH (d:Deal {{source: 'cortellis', id: rel.deal_id}})
                            MERGE (c)-[r:{rel_type}]->(d)
                            SET r.role = $role, r.updated_at = datetime()
                        """, {"rels": rels, "role": role})

                total_synced += len(relationships)
                offset += batch_size
                logger.info("Relationship sync progress", synced=total_synced, total=total_count)

        logger.info("Deal relationship sync complete", total_synced=total_synced)
        return total_synced

    def sync_edgar_companies(self, batch_size: int = 500, limit: Optional[int] = None):
        """
        Bulk sync Edgar companies to Neo4j.

        Args:
            batch_size: Number of companies per batch
            limit: Maximum companies to sync (None for all)
        """
        from sqlalchemy import text
        from unified_api.services.database import get_edgar_source_session, get_cortellis_session

        driver = self._get_driver()
        total_synced = 0

        # First get the xref mappings (by CIK since that's how we link to Edgar)
        xref_map = {}
        with get_cortellis_session() as session:
            result = session.execute(text("""
                SELECT cik, id as xref_id
                FROM company_xref
                WHERE cik IS NOT NULL
            """))
            for row in result:
                xref_map[row.cik] = row.xref_id

        with get_edgar_source_session() as session:
            # Get total count
            count_result = session.execute(text("SELECT COUNT(*) FROM companies"))
            total_count = count_result.scalar()

            if limit:
                total_count = min(total_count, limit)

            logger.info("Starting Edgar company sync", total=total_count)

            offset = 0
            while offset < total_count:
                result = session.execute(text("""
                    SELECT
                        id,
                        name,
                        cik,
                        ticker,
                        sector
                    FROM companies
                    ORDER BY id
                    LIMIT :limit OFFSET :offset
                """), {"limit": batch_size, "offset": offset})

                companies = result.fetchall()
                if not companies:
                    break

                # Bulk insert to Neo4j
                with driver.session() as neo4j_session:
                    neo4j_session.run("""
                        UNWIND $companies as company
                        MERGE (c:Company {source: 'edgar', id: company.id})
                        SET c.name = company.name,
                            c.cik = company.cik,
                            c.ticker = company.ticker,
                            c.sector = company.sector,
                            c.xref_id = company.xref_id,
                            c.updated_at = datetime()
                    """, {"companies": [
                        {
                            "id": c.id,
                            "name": c.name,
                            "cik": c.cik,
                            "ticker": c.ticker,
                            "sector": c.sector,
                            "xref_id": xref_map.get(c.cik) if c.cik else None,
                        }
                        for c in companies
                    ]})

                total_synced += len(companies)
                offset += batch_size
                logger.info("Edgar company sync progress", synced=total_synced, total=total_count)

        logger.info("Edgar company sync complete", total_synced=total_synced)
        return total_synced

    def full_sync(self, limit: Optional[int] = None):
        """
        Perform a full sync of all data to Neo4j.

        Args:
            limit: Optional limit for testing (applies to each entity type)

        Returns:
            Dict with sync statistics
        """
        logger.info("Starting full graph sync", limit=limit)

        # Initialize schema first
        self.initialize_schema()

        results = {
            "cortellis_companies": self.sync_cortellis_companies(limit=limit),
            "cortellis_deals": self.sync_cortellis_deals(limit=limit),
            "deal_relationships": self.sync_deal_relationships(limit=limit),
            "edgar_companies": self.sync_edgar_companies(limit=limit),
        }

        logger.info("Full graph sync complete", **results)
        return results

    def get_sync_stats(self) -> dict:
        """Get current counts of nodes and relationships in Neo4j."""
        driver = self._get_driver()

        stats = {}
        with driver.session() as session:
            # Count nodes by label
            result = session.run("""
                CALL db.labels() YIELD label
                CALL apoc.cypher.run('MATCH (n:`' + label + '`) RETURN count(n) as count', {})
                YIELD value
                RETURN label, value.count as count
            """)

            stats["nodes"] = {}
            for row in result:
                stats["nodes"][row["label"]] = row["count"]

            # Count relationships
            result = session.run("""
                CALL db.relationshipTypes() YIELD relationshipType
                CALL apoc.cypher.run('MATCH ()-[r:`' + relationshipType + '`]->() RETURN count(r) as count', {})
                YIELD value
                RETURN relationshipType, value.count as count
            """)

            stats["relationships"] = {}
            for row in result:
                stats["relationships"][row["relationshipType"]] = row["count"]

        return stats

    def clear_graph(self, confirm: bool = False):
        """
        Clear all nodes and relationships from Neo4j.

        Args:
            confirm: Must be True to actually delete

        WARNING: This is destructive!
        """
        if not confirm:
            raise ValueError("Must pass confirm=True to clear graph")

        driver = self._get_driver()

        with driver.session() as session:
            # Delete in batches to avoid memory issues
            session.run("""
                CALL apoc.periodic.iterate(
                    'MATCH (n) RETURN n',
                    'DETACH DELETE n',
                    {batchSize: 10000}
                )
            """)

        logger.warning("Graph cleared")


# Global service instance
_graph_sync_service: Optional[GraphSyncService] = None


def get_graph_sync_service() -> GraphSyncService:
    """Get or create the graph sync service"""
    global _graph_sync_service

    if _graph_sync_service is None:
        from unified_api.config import settings
        _graph_sync_service = GraphSyncService(
            neo4j_uri=settings.neo4j_uri,
            neo4j_user=settings.neo4j_user,
            neo4j_password=settings.neo4j_password,
        )

    return _graph_sync_service
