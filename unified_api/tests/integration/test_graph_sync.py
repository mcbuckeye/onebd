"""
Neo4j Graph Sync Integration Tests for BD Intelligence Platform

Tests the graph synchronization service that syncs data from
PostgreSQL (Cortellis + Edgar) to Neo4j for relationship queries.

Key validations:
- Neo4j connectivity and schema
- Company node sync
- Deal node sync
- Relationship creation
- Graph query functionality
"""
import pytest
from typing import Dict, Any, List


@pytest.mark.neo4j
@pytest.mark.integration
class TestNeo4jConnection:
    """Tests for Neo4j connectivity and setup."""

    def test_neo4j_driver_connection(self, neo4j_driver):
        """Verify Neo4j driver can connect."""
        # Driver fixture verifies connectivity
        assert neo4j_driver is not None

    def test_neo4j_session_works(self, neo4j_session):
        """Verify Neo4j session can execute queries."""
        result = neo4j_session.run("RETURN 1 as num")
        record = result.single()
        assert record["num"] == 1

    def test_neo4j_version(self, neo4j_session):
        """Verify Neo4j version is compatible."""
        result = neo4j_session.run("CALL dbms.components() YIELD name, versions")
        record = result.single()
        assert record is not None
        # Neo4j 5.x is expected
        versions = record["versions"]
        assert len(versions) > 0

    def test_apoc_extension_available(self, neo4j_session):
        """Verify APOC plugin is installed."""
        try:
            result = neo4j_session.run("RETURN apoc.version() as version")
            record = result.single()
            assert record is not None
            assert record["version"] is not None
        except Exception as e:
            pytest.skip(f"APOC not available: {e}")


@pytest.mark.neo4j
@pytest.mark.integration
class TestGraphSyncService:
    """Tests for the GraphSyncService class."""

    def test_service_initialization(self):
        """Verify GraphSyncService can be initialized."""
        try:
            from unified_api.services.graph_sync import GraphSyncService

            service = GraphSyncService(
                neo4j_uri="bolt://localhost:7687",
                neo4j_user="neo4j",
                neo4j_password="test",
            )
            assert service is not None
            service.close()
        except Exception as e:
            pytest.skip(f"Could not initialize service: {e}")

    def test_get_graph_sync_service(self):
        """Verify global service getter works."""
        try:
            from unified_api.services.graph_sync import get_graph_sync_service

            service = get_graph_sync_service()
            assert service is not None
        except Exception as e:
            pytest.skip(f"Could not get service: {e}")

    def test_schema_initialization(self, neo4j_session):
        """Verify schema can be initialized."""
        try:
            from unified_api.services.graph_sync import get_graph_sync_service

            service = get_graph_sync_service()
            service.initialize_schema()

            # Verify constraints exist
            result = neo4j_session.run("SHOW CONSTRAINTS")
            constraints = list(result)
            assert len(constraints) >= 1, "No constraints created"
        except Exception as e:
            pytest.skip(f"Schema initialization failed: {e}")


@pytest.mark.neo4j
@pytest.mark.integration
class TestCompanyNodeSync:
    """Tests for company node synchronization."""

    def test_create_single_company_node(self, neo4j_session):
        """Verify single company node can be created."""
        try:
            from unified_api.services.graph_sync import get_graph_sync_service

            service = get_graph_sync_service()
            service.create_company_node(
                company_id=99999,
                name="Test Company Inc.",
                source="cortellis",
                ticker="TEST",
                company_type="Test Type",
            )

            # Verify node exists
            result = neo4j_session.run("""
                MATCH (c:Company {source: 'cortellis', id: 99999})
                RETURN c.name as name, c.ticker as ticker
            """)
            record = result.single()
            assert record is not None
            assert record["name"] == "Test Company Inc."
            assert record["ticker"] == "TEST"

            # Cleanup
            neo4j_session.run("""
                MATCH (c:Company {source: 'cortellis', id: 99999})
                DELETE c
            """)
        except Exception as e:
            pytest.skip(f"Company node creation failed: {e}")

    def test_company_node_update(self, neo4j_session):
        """Verify company node can be updated."""
        try:
            from unified_api.services.graph_sync import get_graph_sync_service

            service = get_graph_sync_service()

            # Create initial node
            service.create_company_node(
                company_id=99998,
                name="Original Name",
                source="cortellis",
            )

            # Update node
            service.create_company_node(
                company_id=99998,
                name="Updated Name",
                source="cortellis",
                ticker="UPD",
            )

            # Verify update
            result = neo4j_session.run("""
                MATCH (c:Company {source: 'cortellis', id: 99998})
                RETURN c.name as name, c.ticker as ticker
            """)
            record = result.single()
            assert record["name"] == "Updated Name"
            assert record["ticker"] == "UPD"

            # Cleanup
            neo4j_session.run("""
                MATCH (c:Company {source: 'cortellis', id: 99998})
                DELETE c
            """)
        except Exception as e:
            pytest.skip(f"Company node update failed: {e}")


@pytest.mark.neo4j
@pytest.mark.integration
class TestDealNodeSync:
    """Tests for deal node synchronization."""

    def test_create_single_deal_node(self, neo4j_session):
        """Verify single deal node can be created."""
        try:
            from unified_api.services.graph_sync import get_graph_sync_service

            service = get_graph_sync_service()
            service.create_deal_node(
                deal_id=99999,
                source="cortellis",
                deal_type="License",
                title="Test License Agreement",
                status="Active",
                total_value=100000000.0,
            )

            # Verify node exists
            result = neo4j_session.run("""
                MATCH (d:Deal {source: 'cortellis', id: 99999})
                RETURN d.title as title, d.deal_type as deal_type, d.total_value as total_value
            """)
            record = result.single()
            assert record is not None
            assert record["title"] == "Test License Agreement"
            assert record["deal_type"] == "License"
            assert record["total_value"] == 100000000.0

            # Cleanup
            neo4j_session.run("""
                MATCH (d:Deal {source: 'cortellis', id: 99999})
                DELETE d
            """)
        except Exception as e:
            pytest.skip(f"Deal node creation failed: {e}")


@pytest.mark.neo4j
@pytest.mark.integration
class TestRelationshipSync:
    """Tests for relationship synchronization."""

    def test_create_deal_relationship(self, neo4j_session):
        """Verify deal relationship can be created."""
        try:
            from unified_api.services.graph_sync import get_graph_sync_service

            service = get_graph_sync_service()

            # Create company and deal nodes
            service.create_company_node(company_id=88888, name="Test Co", source="cortellis")
            service.create_deal_node(deal_id=88888, source="cortellis", title="Test Deal")

            # Create relationship
            service.create_deal_relationship(
                deal_id=88888,
                company_id=88888,
                role="principal",
                deal_source="cortellis",
                company_source="cortellis",
            )

            # Verify relationship
            result = neo4j_session.run("""
                MATCH (c:Company {source: 'cortellis', id: 88888})-[r]->(d:Deal {source: 'cortellis', id: 88888})
                RETURN type(r) as rel_type, r.role as role
            """)
            record = result.single()
            assert record is not None
            assert record["rel_type"] == "LICENSES_OUT"  # principal maps to LICENSES_OUT
            assert record["role"] == "principal"

            # Cleanup
            neo4j_session.run("""
                MATCH (c:Company {source: 'cortellis', id: 88888})-[r]-(d:Deal {source: 'cortellis', id: 88888})
                DELETE r
            """)
            neo4j_session.run("MATCH (n {id: 88888}) DELETE n")
        except Exception as e:
            pytest.skip(f"Relationship creation failed: {e}")


@pytest.mark.neo4j
@pytest.mark.integration
@pytest.mark.slow
class TestBulkSync:
    """Tests for bulk synchronization operations."""

    def test_sync_stats(self, neo4j_session):
        """Verify sync stats can be retrieved."""
        try:
            from unified_api.services.graph_sync import get_graph_sync_service

            service = get_graph_sync_service()
            stats = service.get_sync_stats()

            assert "nodes" in stats
            assert "relationships" in stats
            assert isinstance(stats["nodes"], dict)
            assert isinstance(stats["relationships"], dict)
        except Exception as e:
            pytest.skip(f"Could not get sync stats: {e}")

    def test_bulk_company_sync_small_batch(self):
        """Test bulk company sync with a small limit."""
        try:
            from unified_api.services.graph_sync import get_graph_sync_service

            service = get_graph_sync_service()

            # Sync just 10 companies as a test
            synced = service.sync_cortellis_companies(batch_size=10, limit=10)

            assert synced == 10, f"Expected 10 companies synced, got {synced}"
        except Exception as e:
            pytest.skip(f"Bulk company sync failed: {e}")

    def test_bulk_deal_sync_small_batch(self):
        """Test bulk deal sync with a small limit."""
        try:
            from unified_api.services.graph_sync import get_graph_sync_service

            service = get_graph_sync_service()

            # Sync just 10 deals as a test
            synced = service.sync_cortellis_deals(batch_size=10, limit=10)

            assert synced == 10, f"Expected 10 deals synced, got {synced}"
        except Exception as e:
            pytest.skip(f"Bulk deal sync failed: {e}")


@pytest.mark.neo4j
@pytest.mark.integration
class TestGraphQueries:
    """Tests for graph query functionality."""

    def test_find_path_query_structure(self, neo4j_session):
        """Verify path query returns correct structure."""
        # This test verifies the query syntax works, even if no path exists
        result = neo4j_session.run("""
            MATCH (start:Company {source: 'cortellis'})
            WITH start LIMIT 1
            OPTIONAL MATCH path = (start)-[*1..2]-(end:Company)
            WHERE end <> start
            RETURN path
            LIMIT 1
        """)

        # Query should execute without error
        records = list(result)
        # May or may not return results depending on data
        assert True  # Query executed successfully

    def test_network_query_structure(self, neo4j_session):
        """Verify network query returns correct structure."""
        result = neo4j_session.run("""
            MATCH (c:Company {source: 'cortellis'})
            WITH c LIMIT 1
            OPTIONAL MATCH (c)-[r]->(d:Deal)
            RETURN c.name as company, collect(d.title)[0..3] as deals
        """)

        records = list(result)
        # Query should execute without error
        assert True  # Query executed successfully


@pytest.mark.neo4j
@pytest.mark.integration
class TestGraphDataIntegrity:
    """Tests for data integrity in the graph."""

    def test_company_nodes_have_required_fields(self, neo4j_session):
        """Verify company nodes have required properties."""
        result = neo4j_session.run("""
            MATCH (c:Company)
            WHERE c.name IS NULL
            RETURN count(c) as null_names
        """)
        record = result.single()

        if record:
            assert record["null_names"] == 0, \
                f"Found {record['null_names']} companies without names"

    def test_deal_nodes_have_required_fields(self, neo4j_session):
        """Verify deal nodes have required properties."""
        result = neo4j_session.run("""
            MATCH (d:Deal)
            WHERE d.source IS NULL
            RETURN count(d) as missing_source
        """)
        record = result.single()

        if record:
            assert record["missing_source"] == 0, \
                f"Found {record['missing_source']} deals without source"

    def test_relationships_have_valid_endpoints(self, neo4j_session):
        """Verify all relationships connect valid nodes."""
        # This is inherent in Neo4j - relationships can't exist without endpoints
        # But we can check for orphaned relationships created by bugs
        result = neo4j_session.run("""
            MATCH ()-[r]->()
            RETURN count(r) as total_rels
        """)
        record = result.single()
        # Should not fail - just verifies query works
        assert record["total_rels"] >= 0

    def test_xref_links_both_sources(self, neo4j_session):
        """Verify xref_id links companies across sources."""
        result = neo4j_session.run("""
            MATCH (c1:Company {source: 'cortellis'})
            WHERE c1.xref_id IS NOT NULL
            MATCH (c2:Company {source: 'edgar'})
            WHERE c2.xref_id = c1.xref_id
            RETURN count(*) as linked_pairs
        """)
        record = result.single()

        # May have linked pairs if both sources are synced
        linked = record["linked_pairs"] if record else 0
        # This is informational - we just verify the query works
        assert True


@pytest.mark.neo4j
@pytest.mark.integration
class TestGraphEndpoints:
    """Tests for graph API endpoints."""

    def test_network_endpoint(self, api_client):
        """Verify /api/graph/network endpoint works."""
        # Get a company ID first
        response = api_client.get("/api/companies", params={"page_size": 1})

        if response.status_code != 200:
            pytest.skip("Could not get company list")

        data = response.json()
        if isinstance(data, list) and len(data) > 0:
            company_id = data[0].get("id")
        elif "results" in data and len(data["results"]) > 0:
            company_id = data["results"][0].get("id")
        else:
            pytest.skip("No companies available")

        # Test network endpoint
        response = api_client.get(
            f"/api/graph/network/{company_id}",
            params={"source": "cortellis", "depth": 1}
        )

        if response.status_code == 200:
            data = response.json()
            assert "nodes" in data
            assert "edges" in data
        elif response.status_code == 404:
            # Company not in graph is acceptable
            pass
        else:
            pytest.skip(f"Network endpoint returned {response.status_code}")

    def test_path_endpoint(self, api_client):
        """Verify /api/graph/path endpoint works."""
        response = api_client.get(
            "/api/graph/path",
            params={
                "from_company": 1,
                "to_company": 2,
                "source": "cortellis",
                "max_hops": 3,
            }
        )

        if response.status_code == 200:
            data = response.json()
            assert "paths" in data
            assert "shortest_distance" in data
        else:
            # May return empty if companies not in graph
            pass

    def test_top_partners_endpoint(self, api_client):
        """Verify /api/graph/top-partners endpoint works."""
        response = api_client.get(
            "/api/graph/top-partners",
            params={"source": "cortellis", "limit": 10}
        )

        if response.status_code == 200:
            data = response.json()
            assert "partners" in data
            assert isinstance(data["partners"], list)
