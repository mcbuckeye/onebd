"""
Neo4j graph database tool for the Agentic RAG agent.
"""
from typing import Optional
import structlog

from neo4j import AsyncGraphDatabase, AsyncDriver

from .base import BaseTool
from ..models import ToolResult

logger = structlog.get_logger(__name__)


class Neo4jTool(BaseTool):
    """Tool for querying Neo4j graph database."""

    SCHEMA_DESCRIPTION = """
    Neo4j Graph Database contains synchronized business-development entities.
    Counts change over time; query them when a count is needed.

    Nodes:
    - Deal: Business deal with these EXACT properties:
      - id (integer)
      - title (string): The deal headline (searchable text)
      - status (string): e.g., "Active", "Terminated"
      - deal_type (string): Type of deal
      - announced_at (string): Date like "2004-01-06 00:00:00" (use for sorting)
      - total_value (number or null): Projected deal value as synchronized from Cortellis
      - updated_at (datetime)
      - source (string): Usually "cortellis"

    - Company: Organization with properties:
      - id (integer)
      - name (string): Company name (searchable)
      - cik (string): SEC CIK number
      - ticker (string): Stock ticker
      - company_type (string): Type classification
      - xref_id (integer): Cross-reference ID
      - source (string)

    Relationships:
    - (Company)-[:LICENSES_OUT]->(Deal): Principal/licensor relationship
    - (Company)-[:LICENSES_IN]->(Deal): Partner/licensee relationship
    - Other synchronized roles may use PARTICIPATES_IN, ACQUIRES, or ACQUIRED_BY

    CRITICAL Cypher Rules:
    - Use `IS NOT NULL` instead of `EXISTS()` for property checks (deprecated syntax)
    - NO "GROUP BY" in Cypher - aggregations work differently
    - NO SQL-style joins - use pattern matching instead
    - String contains: `d.title CONTAINS 'oncology'` (case-sensitive)
    - Case-insensitive: `toLower(d.title) CONTAINS 'oncology'`
    - Company names must be matched case-insensitively with CONTAINS, never exact equality;
      source names often include suffixes such as Inc, Ltd, plc, or country labels

    Example queries:
    - Find deals: "MATCH (d:Deal) WHERE d.title CONTAINS 'oncology' RETURN d LIMIT 10"
    - Oncology ADC deals: "MATCH (d:Deal) WHERE toLower(d.title) CONTAINS 'oncology' AND toLower(d.title) CONTAINS 'adc' RETURN d LIMIT 20"
    - Find companies: "MATCH (c:Company) WHERE toLower(c.name) CONTAINS 'pfizer' RETURN c LIMIT 10"
    - Recent deals: "MATCH (d:Deal) RETURN d ORDER BY d.announced_at DESC LIMIT 10"
    - Company deals: "MATCH (c:Company)-[:LICENSES_OUT|LICENSES_IN]->(d:Deal) WHERE toLower(c.name) CONTAINS 'pfizer' RETURN d, c LIMIT 10"
    - Active deals only: "MATCH (d:Deal) WHERE d.status = 'Active' AND d.title CONTAINS 'oncology' RETURN d"
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
                records = await result.data()

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

    def is_available(self) -> bool:
        """Return whether the tool is configured without leaking an un-awaited coroutine."""
        return self._driver is not None or all([
            self._uri,
            self._username,
            self._password,
        ])

    def get_schema_description(self) -> str:
        """Return schema description for LLM."""
        return self.SCHEMA_DESCRIPTION

    async def close(self):
        """Close the Neo4j driver."""
        if self._driver:
            await self._driver.close()
            self._is_connected = False
