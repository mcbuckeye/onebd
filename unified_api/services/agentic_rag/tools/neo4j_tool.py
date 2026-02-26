"""
Neo4j graph database tool for the Agentic RAG agent.
"""
from typing import Any, Optional
import structlog

from neo4j import AsyncGraphDatabase, AsyncDriver

from .base import BaseTool
from ..models import ToolResult

logger = structlog.get_logger(__name__)


class Neo4jTool(BaseTool):
    """Tool for querying Neo4j graph database."""

    SCHEMA_DESCRIPTION = """
    Neo4j Graph Database contains business development data:

    Nodes:
    - Deal: Represents a business deal with properties: id, title, area, indication,
            phase, deal_type, status, total_value, upfront_value, deal_date
    - Company: Organization with properties: id, name, type (pharma, biotech)
    - Contract: Agreement document with properties: id, title, type, effective_date
    - Asset: Drug/compound with properties: id, name, mechanism, indication

    Relationships:
    - (Deal)-[:INVOLVES]->(Company): Which companies are parties to a deal
    - (Deal)-[:HAS_CONTRACT]->(Contract): Contracts associated with a deal
    - (Deal)-[:FOR_ASSET]->(Asset): What asset the deal covers
    - (Asset)-[:TARGETS]->(Indication): Disease indications
    - (Company)-[:ACQUIRED]->(Company): Acquisition relationships

    Example queries:
    - Find deals by area: "MATCH (d:Deal)-[:INVOLVES]->(c:Company) WHERE d.area CONTAINS 'Oncology' RETURN d, c"
    - Find deal network: "MATCH path = (d:Deal {id: 'D123'})-[:INVOLVES]->(c)-[:ACQUIRED]->(c2) RETURN path"
    """

    def __init__(
        self,
        driver: Optional[AsyncDriver] = None,
        uri: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        database: str = "neo4j",
        max_retries: int = 2
    ):
        super().__init__("neo4j", max_retries)
        self._driver = driver
        self._uri = uri
        self._username = username
        self._password = password
        self._database = database
        self._is_connected = driver is not None

    async def _get_driver(self) -> AsyncDriver:
        """Lazy initialization of Neo4j driver."""
        if self._driver is None:
            if not all([self._uri, self._username, self._password]):
                raise ValueError("Neo4j credentials not provided")
            self._driver = AsyncGraphDatabase.driver(
                self._uri,
                auth=(self._username, self._password)
            )
            self._is_connected = True
        return self._driver

    async def _execute_impl(self, query: str, **kwargs) -> ToolResult:
        """Execute a Cypher query against Neo4j."""
        driver = await self._get_driver()

        try:
            async with driver.session(database=self._database) as session:
                result = await session.run(query)
                records = await result.fetch(
len(await result.fetch_all()) if hasattr(result, 'fetch_all') else 1000
                )

                # Convert records to dicts
                data = []
                for record in records:
                    row = {}
                    for key in record.keys():
                        value = record[key]
                        # Handle Neo4j node types
                        if hasattr(value, 'items'):
                            row[key] = dict(value.items())
                        elif hasattr(value, 'start_node'):
                            # Relationship
                            row[key] = {
                                "type": value.type,
                                "start": value.start_node.id,
                                "end": value.end_node.id,
                                "properties": dict(value.items())
                            }
                        else:
                            row[key] = value
                    data.append(row)

                return ToolResult(
                    success=True,
                    data=data,
                    row_count=len(data),
                    query_executed=query
                )

        except Exception as e:
            logger.error("Neo4j query failed", query=query, error=str(e))
            return ToolResult(
                success=False,
                error=str(e),
                row_count=0,
                query_executed=query
            )

    async def is_available(self) -> bool:
        """Check if Neo4j is reachable."""
        if not self._is_connected:
            return False
        try:
            driver = await self._get_driver()
            await driver.verify_connectivity()
            return True
        except Exception:
            return False

    def get_schema_description(self) -> str:
        """Return schema description for LLM."""
        return self.SCHEMA_DESCRIPTION

    async def close(self):
        """Close the Neo4j driver."""
        if self._driver:
            await self._driver.close()
            self._is_connected = False