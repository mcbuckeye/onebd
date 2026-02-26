"""
Base class for Agentic RAG tools.
All tools must implement the Tool interface.
"""
from abc import ABC, abstractmethod
from typing import Any, Optional
import structlog

from ..models import ToolResult

logger = structlog.get_logger(__name__)


class BaseTool(ABC):
    """Abstract base class for data source tools."""

    def __init__(self, name: str, max_retries: int = 2):
        self.name = name
        self.max_retries = max_retries
        self.logger = logger.bind(tool=name)

    @abstractmethod
    async def _execute_impl(self, query: str, **kwargs) -> ToolResult:
        """
        Actual implementation of tool execution.
        Must be implemented by subclasses.
        """
        pass

    async def execute(self, query: str, **kwargs) -> ToolResult:
        """
        Execute query with retry logic.

        Args:
            query: The query string to execute
            **kwargs: Additional parameters

        Returns:
            ToolResult with success status and data/error
        """
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                self.logger.info(
                    f"Executing {self.name} query",
                    attempt=attempt + 1,
                    max_retries=self.max_retries + 1
                )
                result = await self._execute_impl(query, **kwargs)

                # Defensive: handle None result
                if result is None:
                    last_error = "Tool returned None instead of ToolResult"
                    self.logger.error(f"{self.name} returned None")
                    continue

                if result.success:
                    self.logger.info(
                        f"{self.name} query succeeded",
                        row_count=result.row_count
                    )
                    return result
                else:
                    # Tool returned error (e.g., syntax error)
                    last_error = result.error
                    self.logger.warning(
                        f"{self.name} query returned error",
                        attempt=attempt + 1,
                        error=result.error
                    )

            except Exception as e:
                last_error = str(e)
                self.logger.error(
                    f"{self.name} query failed",
                    attempt=attempt + 1,
                    error=str(e)
                )

        # All retries exhausted - return detailed error for debugging
        error_detail = f"""Query failed after {self.max_retries + 1} attempts.

Tool: {self.name}
Query: {query[:500]}{'...' if len(query) > 500 else ''}

Last Error:
{last_error}

Tip: Check query syntax against the database schema. Common issues:
- Using EXISTS() instead of IS NOT NULL in Cypher
- Referencing non-existent columns
- Wrong quote style (use single quotes for strings)
- Missing LIMIT clause for large tables"""

        return ToolResult(
            success=False,
            error=error_detail,
            row_count=0,
            query_executed=query
        )

    def is_available(self) -> bool:
        """
        Check if tool is available/connectable.
        Override in subclass if needed.
        """
        return True

    def get_schema_description(self) -> str:
        """
        Return schema description for LLM context.
        Override in subclass.
        """
        return f"{self.name} tool - no schema description available"