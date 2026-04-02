"""
Graph endpoints for Neo4j relationship queries.
"""
from typing import Optional, List
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter()


class GraphNode(BaseModel):
    """A node in the graph."""
    id: str
    label: str
    name: str
    properties: dict = {}


class GraphEdge(BaseModel):
    """An edge in the graph."""
    source: str
    target: str
    relationship: str
    properties: dict = {}


class NetworkResponse(BaseModel):
    """Response containing graph network data."""
    nodes: List[GraphNode]
    edges: List[GraphEdge]


class PathResponse(BaseModel):
    """Response containing path between entities."""
    paths: List[List[dict]]
    shortest_distance: int


@router.get("/graph/network/{company_id}", response_model=NetworkResponse)
async def get_company_network(
    company_id: int,
    source: str = Query("cortellis", description="Source database"),
    depth: int = Query(1, ge=1, le=3),
    limit: int = Query(50, ge=1, le=200, description="Max partners to include"),
):
    """
    Get partnership network for a company.

    Returns nodes and edges representing:
    - Direct partners (depth=1)
    - Partners of partners (depth=2)
    - Extended network (depth=3)

    Perfect for D3.js/vis.js network visualization.
    """
    from unified_api.services.graph_sync import get_graph_sync_service

    logger.info(
        "Getting company network",
        company_id=company_id,
        depth=depth,
    )

    graph_service = get_graph_sync_service()
    driver = graph_service._get_driver()

    nodes = []
    edges = []
    seen_nodes = set()
    seen_edges = set()

    with driver.session() as session:
        # Get the central company
        result = session.run("""
            MATCH (c:Company {source: $source, id: $company_id})
            RETURN c.id as id, c.name as name, c.company_type as company_type
        """, {"source": source, "company_id": company_id})

        central = result.single()
        if not central:
            return NetworkResponse(nodes=[], edges=[])

        # Add central node
        central_node_id = f"company_{central['id']}"
        nodes.append(GraphNode(
            id=central_node_id,
            label="Company",
            name=central["name"],
            properties={"company_type": central["company_type"], "is_central": True}
        ))
        seen_nodes.add(central_node_id)

        # Get partners and deals based on depth
        if depth >= 1:
            # Direct partners - simplified query without window functions
            result = session.run("""
                MATCH (c:Company {source: $source, id: $company_id})-[r1]->(d:Deal)<-[r2]-(partner:Company)
                WHERE c.id <> partner.id
                WITH partner, d, type(r1) as rel1, type(r2) as rel2
                WITH partner, collect({deal: d, rel1: rel1, rel2: rel2}) as all_deals
                WITH partner, all_deals, size(all_deals) as deal_count
                ORDER BY deal_count DESC
                LIMIT $limit
                UNWIND all_deals[0..3] as deal_info
                RETURN partner.id as partner_id, partner.name as partner_name,
                       partner.company_type as partner_type, deal_info
            """, {"source": source, "company_id": company_id, "limit": limit})

            for row in result:
                partner_node_id = f"company_{row['partner_id']}"

                # Add partner node
                if partner_node_id not in seen_nodes:
                    nodes.append(GraphNode(
                        id=partner_node_id,
                        label="Company",
                        name=row["partner_name"],
                        properties={"company_type": row["partner_type"]}
                    ))
                    seen_nodes.add(partner_node_id)

                # Add deal node and edges
                deal_info = row["deal_info"]
                deal = deal_info["deal"]
                deal_node_id = f"deal_{deal['id']}"

                if deal_node_id not in seen_nodes:
                    nodes.append(GraphNode(
                        id=deal_node_id,
                        label="Deal",
                        name=deal.get("title", "Untitled Deal")[:100],
                        properties={
                            "deal_type": deal.get("deal_type"),
                            "status": deal.get("status"),
                            "total_value": deal.get("total_value"),
                        }
                    ))
                    seen_nodes.add(deal_node_id)

                # Central company -> Deal edge
                edge_key1 = f"{central_node_id}->{deal_node_id}"
                if edge_key1 not in seen_edges:
                    edges.append(GraphEdge(
                        source=central_node_id,
                        target=deal_node_id,
                        relationship=deal_info["rel1"],
                    ))
                    seen_edges.add(edge_key1)

                # Partner -> Deal edge
                edge_key2 = f"{partner_node_id}->{deal_node_id}"
                if edge_key2 not in seen_edges:
                    edges.append(GraphEdge(
                        source=partner_node_id,
                        target=deal_node_id,
                        relationship=deal_info["rel2"],
                    ))
                    seen_edges.add(edge_key2)

    return NetworkResponse(nodes=nodes, edges=edges)


@router.get("/graph/path")
async def find_path(
    from_company: int = Query(..., description="Starting company ID"),
    to_company: int = Query(..., description="Target company ID"),
    source: str = Query("cortellis", description="Source database"),
    max_hops: int = Query(4, ge=1, le=6, description="Maximum path length"),
):
    """
    Find shortest path between two companies.

    Returns the shortest path(s) connecting the companies through deals.
    Each hop goes: Company -> Deal -> Company
    """
    from unified_api.services.graph_sync import get_graph_sync_service

    logger.info(
        "Finding path",
        from_company=from_company,
        to_company=to_company,
        max_hops=max_hops,
    )

    graph_service = get_graph_sync_service()
    driver = graph_service._get_driver()

    paths = []
    shortest_distance = -1

    with driver.session() as session:
        # Find shortest path - use string interpolation for max_hops since Neo4j
        # doesn't support parameterized relationship length in shortestPath
        query = f"""
            MATCH (start:Company {{source: $source, id: $from_company}})
            MATCH (end:Company {{source: $source, id: $to_company}})
            MATCH path = shortestPath((start)-[*1..{max_hops}]-(end))
            RETURN path, length(path) as path_length
            LIMIT 5
        """
        result = session.run(query, {
            "source": source,
            "from_company": from_company,
            "to_company": to_company,
        })

        for row in result:
            path = row["path"]
            path_length = row["path_length"]

            if shortest_distance == -1 or path_length < shortest_distance:
                shortest_distance = path_length

            path_data = []
            for node in path.nodes:
                labels = list(node.labels)
                if "Company" in labels:
                    path_data.append({
                        "type": "company",
                        "id": node.get("id"),
                        "name": node.get("name"),
                    })
                elif "Deal" in labels:
                    path_data.append({
                        "type": "deal",
                        "id": node.get("id"),
                        "title": node.get("title", "")[:100],
                        "deal_type": node.get("deal_type"),
                    })

            paths.append(path_data)

    return PathResponse(paths=paths, shortest_distance=shortest_distance)


@router.get("/graph/deals-between")
async def deals_between_companies(
    company_a: int = Query(..., description="First company ID"),
    company_b: int = Query(..., description="Second company ID"),
    source: str = Query("cortellis", description="Source database"),
    limit: int = Query(50, ge=1, le=200),
):
    """
    Get all deals between two companies.

    Returns deals where both companies are involved,
    regardless of their role (principal/partner).
    """
    from unified_api.services.graph_sync import get_graph_sync_service

    logger.info(
        "Getting deals between companies",
        company_a=company_a,
        company_b=company_b,
    )

    graph_service = get_graph_sync_service()
    driver = graph_service._get_driver()

    deals = []

    with driver.session() as session:
        result = session.run("""
            MATCH (a:Company {source: $source, id: $company_a})-[r1]->(d:Deal)<-[r2]-(b:Company {source: $source, id: $company_b})
            RETURN d.id as deal_id, d.title as title, d.deal_type as deal_type,
                   d.status as status, d.announced_at as announced_at,
                   d.total_value as total_value,
                   type(r1) as company_a_role, type(r2) as company_b_role
            ORDER BY d.announced_at DESC
            LIMIT $limit
        """, {
            "source": source,
            "company_a": company_a,
            "company_b": company_b,
            "limit": limit,
        })

        for row in result:
            deals.append({
                "id": row["deal_id"],
                "title": row["title"],
                "deal_type": row["deal_type"],
                "status": row["status"],
                "announced_at": row["announced_at"],
                "total_value": row["total_value"],
                "company_a_role": row["company_a_role"],
                "company_b_role": row["company_b_role"],
            })

    return {"deals": deals, "count": len(deals)}


@router.get("/graph/top-partners")
async def top_partners(
    company_id: Optional[int] = Query(None, description="Company ID to find partners for"),
    source: str = Query("cortellis", description="Source database"),
    therapy_area: Optional[str] = None,
    deal_type: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
):
    """
    Get top partnering companies by deal count.

    If company_id is provided, returns top partners for that company.
    Otherwise returns top partnering companies overall.
    """
    from unified_api.services.graph_sync import get_graph_sync_service

    logger.info(
        "Getting top partners",
        company_id=company_id,
        therapy_area=therapy_area,
        deal_type=deal_type,
        limit=limit,
    )

    graph_service = get_graph_sync_service()
    driver = graph_service._get_driver()

    with driver.session() as session:
        if company_id:
            # Find partners for specific company
            result = session.run("""
                MATCH (c:Company {source: $source, id: $company_id})-[r1]->(d:Deal)<-[r2]-(partner:Company)
                WHERE c.id <> partner.id
                WITH partner.name as partner_name, partner.id as partner_id,
                     count(DISTINCT d) as deal_count
                ORDER BY deal_count DESC
                LIMIT $limit
                RETURN partner_name, partner_id, deal_count
            """, {"source": source, "company_id": company_id, "limit": limit})
        else:
            # Find most active partnering companies
            result = session.run("""
                MATCH (c:Company)-[r]->(d:Deal)
                WITH c.name as company_name, c.id as company_id, count(DISTINCT d) as deal_count
                ORDER BY deal_count DESC
                LIMIT $limit
                RETURN company_name, company_id, deal_count
            """, {"limit": limit})

        partners = []
        for row in result:
            if company_id:
                partners.append({
                    "name": row["partner_name"],
                    "id": row["partner_id"],
                    "deal_count": row["deal_count"],
                })
            else:
                partners.append({
                    "name": row["company_name"],
                    "id": row["company_id"],
                    "deal_count": row["deal_count"],
                })

    return {"partners": partners}


class SyncStats(BaseModel):
    """Statistics from graph sync operation."""
    cortellis_companies: int = 0
    cortellis_deals: int = 0
    deal_relationships: int = 0
    edgar_companies: int = 0


class GraphStats(BaseModel):
    """Current graph statistics."""
    nodes: dict = {}
    relationships: dict = {}


@router.get("/graph/stats", response_model=GraphStats)
async def get_graph_stats():
    """
    Get current statistics about nodes and relationships in Neo4j.

    Returns counts by label/type.
    """
    from unified_api.services.graph_sync import get_graph_sync_service

    logger.info("Getting graph stats")

    try:
        graph_service = get_graph_sync_service()
        stats = graph_service.get_sync_stats()
        return GraphStats(**stats)
    except Exception as e:
        logger.error("Failed to get graph stats", error=str(e))
        return GraphStats(nodes={}, relationships={})


@router.post("/graph/sync", response_model=SyncStats)
async def sync_graph(
    limit: Optional[int] = Query(None, description="Limit records per entity type (for testing)"),
):
    """
    Sync data from PostgreSQL to Neo4j.

    This operation:
    1. Creates/updates Company nodes from Cortellis and Edgar
    2. Creates/updates Deal nodes from Cortellis
    3. Creates relationships between companies and deals

    Use limit parameter for testing with smaller dataset.
    """
    from unified_api.services.graph_sync import get_graph_sync_service

    logger.info("Starting graph sync", limit=limit)

    graph_service = get_graph_sync_service()
    results = graph_service.full_sync(limit=limit)

    return SyncStats(**results)


@router.post("/graph/initialize")
async def initialize_graph():
    """
    Initialize Neo4j schema (indexes and constraints).

    Call this once before syncing data.
    """
    from unified_api.services.graph_sync import get_graph_sync_service

    logger.info("Initializing Neo4j schema")

    graph_service = get_graph_sync_service()
    graph_service.initialize_schema()

    return {"status": "initialized"}


@router.post("/graph/cypher")
async def execute_cypher(query: str, params: dict = {}):
    """
    Execute a Cypher query against Neo4j.

    **Warning**: This endpoint is for development/admin use only.
    In production, use parameterized queries only.
    """
    logger.warning("Direct Cypher query execution", query=query[:100])

    # TODO: Execute against Neo4j with safety checks
    raise HTTPException(status_code=501, detail="Not implemented")


# ============================================
# D3.js-Optimized Network Visualization
# ============================================

class D3Node(BaseModel):
    """D3.js-compatible node."""
    id: str
    name: str
    type: str  # company, deal
    deal_count: int = 0
    total_value: Optional[float] = None
    is_central: bool = False
    company_type: Optional[str] = None


class D3Link(BaseModel):
    """D3.js-compatible link."""
    source: str
    target: str
    deal_count: int = 1
    total_value: Optional[float] = None


class D3NetworkResponse(BaseModel):
    """D3.js-compatible network visualization data."""
    nodes: List[D3Node]
    links: List[D3Link]
    central_company: Optional[str] = None
    total_partners: int = 0
    total_deals: int = 0


@router.get("/graph/partnership-network/{company_id}", response_model=D3NetworkResponse)
async def get_partnership_network_d3(
    company_id: int,
    source: str = Query("cortellis", description="Source database"),
    depth: int = Query(1, ge=1, le=2, description="Network depth (1=direct, 2=partners of partners)"),
    min_deals: int = Query(1, ge=1, description="Minimum deals to include partner"),
    limit: int = Query(30, ge=1, le=100, description="Max partners to include"),
):
    """
    Get D3.js-optimized partnership network for visualization.

    Returns a simplified network with:
    - Companies as nodes (with deal_count and total_value)
    - Direct links between companies (aggregated deal relationships)

    This format is ideal for D3.js force-directed graphs.
    """
    from unified_api.services.graph_sync import get_graph_sync_service

    logger.info(
        "Getting D3 partnership network",
        company_id=company_id,
        depth=depth,
        limit=limit,
    )

    graph_service = get_graph_sync_service()
    driver = graph_service._get_driver()

    nodes = []
    links = []
    seen_nodes = {}
    seen_links = set()

    with driver.session() as session:
        # Get the central company
        result = session.run("""
            MATCH (c:Company {source: $source, id: $company_id})
            OPTIONAL MATCH (c)-[]->(d:Deal)
            WITH c, count(DISTINCT d) as deal_count
            RETURN c.id as id, c.name as name, c.company_type as company_type, deal_count
        """, {"source": source, "company_id": company_id})

        central = result.single()
        if not central:
            return D3NetworkResponse(nodes=[], links=[], total_partners=0, total_deals=0)

        central_node_id = f"company_{central['id']}"
        nodes.append(D3Node(
            id=central_node_id,
            name=central["name"],
            type="company",
            deal_count=central["deal_count"] or 0,
            is_central=True,
            company_type=central["company_type"],
        ))
        seen_nodes[central_node_id] = 0  # Index in nodes array

        # Get partners with aggregated deal data
        result = session.run("""
            MATCH (c:Company {source: $source, id: $company_id})-[]->(d:Deal)<-[]-(partner:Company)
            WHERE c.id <> partner.id
            WITH partner,
                 count(DISTINCT d) as deal_count,
                 sum(CASE WHEN d.total_value IS NOT NULL THEN toFloat(d.total_value) ELSE 0 END) as total_value
            WHERE deal_count >= $min_deals
            ORDER BY deal_count DESC
            LIMIT $limit
            RETURN partner.id as id, partner.name as name,
                   partner.company_type as company_type,
                   deal_count, total_value
        """, {
            "source": source,
            "company_id": company_id,
            "min_deals": min_deals,
            "limit": limit,
        })

        total_deals = 0
        for row in result:
            partner_node_id = f"company_{row['id']}"
            deal_count = row["deal_count"]
            total_value = row["total_value"]
            total_deals += deal_count

            if partner_node_id not in seen_nodes:
                seen_nodes[partner_node_id] = len(nodes)
                nodes.append(D3Node(
                    id=partner_node_id,
                    name=row["name"],
                    type="company",
                    deal_count=deal_count,
                    total_value=float(total_value) if total_value else None,
                    company_type=row["company_type"],
                ))

            # Add link
            link_key = tuple(sorted([central_node_id, partner_node_id]))
            if link_key not in seen_links:
                seen_links.add(link_key)
                links.append(D3Link(
                    source=central_node_id,
                    target=partner_node_id,
                    deal_count=deal_count,
                    total_value=float(total_value) if total_value else None,
                ))

        # For depth=2, get partners of partners
        if depth >= 2 and len(nodes) > 1:
            partner_ids = [int(n.id.replace("company_", "")) for n in nodes[1:]]

            result = session.run("""
                UNWIND $partner_ids as pid
                MATCH (p1:Company {source: $source, id: pid})-[]->(d:Deal)<-[]-(p2:Company)
                WHERE p1.id <> p2.id
                  AND p2.id <> $company_id
                  AND NOT p2.id IN $partner_ids
                WITH p1, p2, count(DISTINCT d) as deal_count
                WHERE deal_count >= $min_deals
                ORDER BY deal_count DESC
                LIMIT 50
                RETURN p1.id as source_id, p2.id as target_id,
                       p2.name as target_name, p2.company_type as target_type,
                       deal_count
            """, {
                "source": source,
                "company_id": company_id,
                "partner_ids": partner_ids,
                "min_deals": min_deals,
            })

            for row in result:
                source_node_id = f"company_{row['source_id']}"
                target_node_id = f"company_{row['target_id']}"
                deal_count = row["deal_count"]

                if target_node_id not in seen_nodes:
                    seen_nodes[target_node_id] = len(nodes)
                    nodes.append(D3Node(
                        id=target_node_id,
                        name=row["target_name"],
                        type="company",
                        deal_count=deal_count,
                        company_type=row["target_type"],
                    ))

                link_key = tuple(sorted([source_node_id, target_node_id]))
                if link_key not in seen_links:
                    seen_links.add(link_key)
                    links.append(D3Link(
                        source=source_node_id,
                        target=target_node_id,
                        deal_count=deal_count,
                    ))

    return D3NetworkResponse(
        nodes=nodes,
        links=links,
        central_company=central["name"],
        total_partners=len(nodes) - 1,
        total_deals=total_deals,
    )


class PartnerDetail(BaseModel):
    """Detailed partner information."""
    company_id: int
    company_name: str
    company_type: Optional[str] = None
    deal_count: int
    total_value: Optional[float] = None
    avg_value: Optional[float] = None
    first_deal_date: Optional[str] = None
    last_deal_date: Optional[str] = None
    deal_types: List[str] = []
    therapy_areas: List[str] = []


class PartnersSummaryResponse(BaseModel):
    """Summary of company's partners."""
    company_id: int
    company_name: str
    total_partners: int
    total_deal_value: Optional[float] = None
    partners: List[PartnerDetail]


@router.get("/graph/company/{company_id}/partners-summary", response_model=PartnersSummaryResponse)
async def get_partners_summary(
    company_id: int,
    source: str = Query("cortellis", description="Source database"),
    min_deals: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    """
    Get detailed summary of a company's partners.

    Returns partner companies with:
    - Deal count and total value
    - First/last deal dates
    - Common deal types and therapy areas
    """
    from unified_api.services.graph_sync import get_graph_sync_service

    logger.info("Getting partners summary", company_id=company_id)

    graph_service = get_graph_sync_service()
    driver = graph_service._get_driver()

    with driver.session() as session:
        # Get company name
        company_result = session.run("""
            MATCH (c:Company {source: $source, id: $company_id})
            RETURN c.name as name
        """, {"source": source, "company_id": company_id})

        company = company_result.single()
        if not company:
            raise HTTPException(status_code=404, detail="Company not found in graph")

        # Get partners with detailed metrics
        result = session.run("""
            MATCH (c:Company {source: $source, id: $company_id})-[]->(d:Deal)<-[]-(partner:Company)
            WHERE c.id <> partner.id
            WITH partner, d
            ORDER BY d.announced_at
            WITH partner,
                 collect(DISTINCT d) as deals,
                 count(DISTINCT d) as deal_count,
                 sum(CASE WHEN d.total_value IS NOT NULL THEN toFloat(d.total_value) ELSE 0 END) as total_value
            WHERE deal_count >= $min_deals
            ORDER BY deal_count DESC
            LIMIT $limit
            WITH partner, deals, deal_count, total_value,
                 head(deals).announced_at as first_deal,
                 last(deals).announced_at as last_deal
            RETURN partner.id as id, partner.name as name,
                   partner.company_type as company_type,
                   deal_count, total_value,
                   first_deal, last_deal,
                   [d IN deals | d.deal_type] as deal_types,
                   [d IN deals | d.therapy_area] as therapy_areas
        """, {
            "source": source,
            "company_id": company_id,
            "min_deals": min_deals,
            "limit": limit,
        })

        partners = []
        total_value = 0

        for row in result:
            partner_value = row["total_value"]
            if partner_value:
                total_value += partner_value

            # Get unique deal types and therapy areas
            deal_types = list(set(dt for dt in row["deal_types"] if dt))
            therapy_areas = list(set(ta for ta in row["therapy_areas"] if ta))

            partners.append(PartnerDetail(
                company_id=row["id"],
                company_name=row["name"],
                company_type=row["company_type"],
                deal_count=row["deal_count"],
                total_value=float(partner_value) if partner_value else None,
                avg_value=float(partner_value / row["deal_count"]) if partner_value else None,
                first_deal_date=str(row["first_deal"]) if row["first_deal"] else None,
                last_deal_date=str(row["last_deal"]) if row["last_deal"] else None,
                deal_types=deal_types[:5],
                therapy_areas=therapy_areas[:5],
            ))

    return PartnersSummaryResponse(
        company_id=company_id,
        company_name=company["name"],
        total_partners=len(partners),
        total_deal_value=total_value if total_value > 0 else None,
        partners=partners,
    )


@router.get("/graph/industry-network")
async def get_industry_network(
    therapy_area: Optional[str] = Query(None, description="Filter by therapy area"),
    deal_type: Optional[str] = Query(None, description="Filter by deal type"),
    source: str = Query("cortellis", description="Source database"),
    min_deals: int = Query(3, ge=1, description="Minimum deals between companies"),
    limit: int = Query(50, ge=10, le=200, description="Max companies to include"),
):
    """
    Get industry-wide partnership network.

    Returns the most connected companies and their relationships.
    Useful for understanding the overall partnership landscape.
    """
    from unified_api.services.graph_sync import get_graph_sync_service

    logger.info(
        "Getting industry network",
        therapy_area=therapy_area,
        deal_type=deal_type,
    )

    graph_service = get_graph_sync_service()
    driver = graph_service._get_driver()

    nodes = []
    links = []
    seen_nodes = {}
    seen_links = set()

    with driver.session() as session:
        # Build filter conditions
        deal_filters = []
        if therapy_area:
            deal_filters.append(f"d.therapy_area CONTAINS '{therapy_area}'")
        if deal_type:
            deal_filters.append(f"d.deal_type CONTAINS '{deal_type}'")

        where_clause = " AND ".join(deal_filters) if deal_filters else "true"

        # Get most connected companies
        result = session.run(f"""
            MATCH (c1:Company {{source: $source}})-[]->(d:Deal)<-[]-(c2:Company)
            WHERE c1.id < c2.id AND {where_clause}
            WITH c1, c2, count(DISTINCT d) as deal_count,
                 sum(CASE WHEN d.total_value IS NOT NULL THEN toFloat(d.total_value) ELSE 0 END) as total_value
            WHERE deal_count >= $min_deals
            ORDER BY deal_count DESC
            LIMIT $limit
            RETURN c1.id as c1_id, c1.name as c1_name, c1.company_type as c1_type,
                   c2.id as c2_id, c2.name as c2_name, c2.company_type as c2_type,
                   deal_count, total_value
        """, {
            "source": source,
            "min_deals": min_deals,
            "limit": limit,
        })

        for row in result:
            # Add nodes
            for prefix in ["c1", "c2"]:
                node_id = f"company_{row[f'{prefix}_id']}"
                if node_id not in seen_nodes:
                    seen_nodes[node_id] = len(nodes)
                    nodes.append(D3Node(
                        id=node_id,
                        name=row[f"{prefix}_name"],
                        type="company",
                        company_type=row[f"{prefix}_type"],
                    ))

            # Add link
            c1_id = f"company_{row['c1_id']}"
            c2_id = f"company_{row['c2_id']}"
            link_key = tuple(sorted([c1_id, c2_id]))

            if link_key not in seen_links:
                seen_links.add(link_key)
                links.append(D3Link(
                    source=c1_id,
                    target=c2_id,
                    deal_count=row["deal_count"],
                    total_value=float(row["total_value"]) if row["total_value"] else None,
                ))

        # Update node deal counts
        for node in nodes:
            company_id = int(node.id.replace("company_", ""))
            count_result = session.run("""
                MATCH (c:Company {source: $source, id: $company_id})-[]->(d:Deal)
                RETURN count(DISTINCT d) as deal_count
            """, {"source": source, "company_id": company_id})
            count_row = count_result.single()
            if count_row:
                node.deal_count = count_row["deal_count"]

    return D3NetworkResponse(
        nodes=nodes,
        links=links,
        total_partners=len(nodes),
        total_deals=sum(link.deal_count for link in links),
    )
