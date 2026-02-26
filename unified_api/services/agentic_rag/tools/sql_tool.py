"""
SQL database tool for querying Cortellis and Edgar databases.
"""
from typing import Any, Callable, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import structlog

from .base import BaseTool
from ..models import ToolResult

logger = structlog.get_logger(__name__)


class SQLTool(BaseTool):
    """Tool for querying SQL databases (PostgreSQL)."""

    SCHEMA_DESCRIPTION = """
    SQL Database contains structured business development data:

    Main tables:
    - deals(id, title, area, indication, phase, deal_type, status, total_value,
            upfront_value, deal_date, acquirer_id, target_id, source)
    - companies(id, name, type, country, employees, revenue)
    - contracts(id, deal_id, title, content, effective_date, expiration_date)
    - financial_terms(id, deal_id, upfront, milestones, royalties, total_value)

    Key relationships:
    - deals.acquirer_id -> companies.id
    - deals.target_id -> companies.id
    - contracts.deal_id -> deals.id
    - financial_terms.deal_id -> deals.id

    Example queries:
    - Find deals by area: "SELECT * FROM deals WHERE area ILIKE '%Oncology%'"
    - Deal with parties: "SELECT d.*, c1.name as acquirer, c2.name as target
                          FROM deals d
                          JOIN companies c1 ON d.acquirer_id = c1.id
                          JOIN companies c2 ON d.target_id = c2.id
                          WHERE d.area ILIKE '%Oncology%'"
    """

    def __init__(
        self,
        session_factory: Optional[Callable[[], AsyncSession]] = None,
        connection_string: Optional[str] = None,
        max_retries: int = 2
    ):
        super().__init__("sql", max_retries)
        self.session_factory = session_factory
        self.connection_string = connection_string

    async def _execute_impl(self, query: str, **kwargs) -> ToolResult:
        """Execute SQL query against database."""
        if self.session_factory is None:
            return ToolResult(
                success=False,
                error="SQL session factory not provided",
                row_count=0,
                query_executed=query
            )

        session = None
        try:
            session = self.session_factory()
            result = await session.execute(text(query))

            # Get column names from result keys
            columns = result.keys() if hasattr(result, 'keys') else []

            # Fetch all rows
            rows = result.mappings().all()

            # Convert to list of dicts
            data = []
            for row in rows:
                row_dict = dict(row)
                # Convert non-serializable types
                for key, value in row_dict.items():
                    if hasattr(value, 'isoformat'):  # datetime
                        row_dict[key] = value.isoformat()
                    elif value is None:
                        row_dict[key] = None
                    else:
                        row_dict[key] = value
                data.append(row_dict)

            return ToolResult(
                success=True,
                data=data,
                row_count=len(data),
                query_executed=query
            )

        except Exception as e:
            logger.error("SQL query failed", query=query, error=str(e))
            return ToolResult(
                success=False,
                error=str(e),
                row_count=0,
                query_executed=query
            )
        finally:
            if session:
                await session.close()

    def is_available(self) -> bool:
        """Check if SQL tool is available."""
        return self.session_factory is not None or self.connection_string is not None

    def get_schema_description(self) -> str:
        """Return schema description for LLM."""
        return self.SCHEMA_DESCRIPTION

    def validate_query(self, query: str) -> tuple[bool, Optional[str]]:
        """
        Basic SQL validation - prevent destructive operations.
        Returns (is_valid, error_message).
        """
        query_upper = query.strip().upper()

        # Only allow SELECT statements
        forbidden_keywords = ['DELETE', 'DROP', 'TRUNCATE', 'UPDATE', 'INSERT', 'ALTER']
        for keyword in forbidden_keywords:
            if keyword in query_upper:
                return False, f"Query contains forbidden keyword: {keyword}"

        # Must start with SELECT
        if not query_upper.startswith('SELECT'):
            return False, "Only SELECT queries are allowed"

        return True, None