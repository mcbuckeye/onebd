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
    Cortellis PostgreSQL Database - ACTUAL SCHEMA (introspected from DB):

    Table: deals
      id: integer (PRIMARY KEY)
      title: text (deal headline, searchable with ILIKE)
      deal_type: character varying (License, Collaboration, etc.)
      status: character varying (Active, Terminated, etc.)
      is_optional: boolean
      is_merger_acquisition: boolean
      has_contract: boolean
      therapy_area_id: integer
      date_start: timestamp (deal start date)
      date_end: timestamp (deal end date)
      date_event_most_recent: timestamp
      date_change_last: timestamp
      date_added: timestamp
      summary: text (detailed description)
      agreement_type: character varying
      asset_type: character varying
      transaction_type: character varying
      phase_highest_start: character varying (Phase 1, Phase 2, Phase 3, etc.)
      phase_highest_now: character varying
      category_raw: jsonb (JSON data)
      cross_references_raw: jsonb (JSON cross-references)

    Table: companies
      id: integer (PRIMARY KEY)
      name: character varying (company name, searchable)
      company_type: character varying
      hq_location: character varying
      cik: character varying (SEC CIK number)
      ticker: character varying (stock symbol)

    PostgreSQL Syntax Rules:
    - Use ILIKE for case-insensitive search: title ILIKE '%oncology%'
    - Boolean checks: is_merger_acquisition = true
    - JSONB access: cross_references_raw->>'key'
    - Date comparison: date_start >= '2020-01-01'::timestamp
    - LIMIT for large result sets

    Example queries:
    - Oncology deals: "SELECT id, title, status, phase_highest_start FROM deals WHERE title ILIKE '%oncology%' LIMIT 10"
    - Phase 3 deals: "SELECT title, phase_highest_start FROM deals WHERE phase_highest_start = 'Phase 3' ORDER BY date_start DESC LIMIT 20"
    - Find Pfizer: "SELECT name, ticker, company_type FROM companies WHERE name ILIKE '%pfizer%'"
    - M&A deals: "SELECT title, deal_type FROM deals WHERE is_merger_acquisition = true LIMIT 10"
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