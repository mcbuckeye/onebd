"""
pgvector tool for semantic search on contracts and Edgar filings.
"""
from typing import Any, Callable, Optional, List
from sqlalchemy import text
import structlog

from .base import BaseTool
from ..models import ToolResult

logger = structlog.get_logger(__name__)


class PgVectorTool(BaseTool):
    """Tool for semantic search using pgvector vector database."""

    SCHEMA_DESCRIPTION = """
    pgvector Database contains embedded documents for semantic search:

    Main tables:
    - document_chunks(id, document_id, document_type, content, embedding vector(1536),
                      metadata, created_at)
    - documents(id, title, source, doc_type, effective_date, metadata)

    Document types:
    - 'contract': Licensing agreements, collaboration contracts
    - 'edgar_filing': SEC filings (10-K, 10-Q, 8-K)
    - 'press_release': Company announcements
    - 'patent': Patent filings and documents

    The embedding column stores 1536-dimensional vectors for semantic similarity.
    Use <=> operator for cosine distance (lower is more similar).

    Example queries:
    - Find similar contracts: "SELECT content, metadata, embedding <=> query_embedding as distance
                               FROM document_chunks
                               WHERE document_type = 'contract'
                               ORDER BY embedding <=> query_embedding
                               LIMIT 10"
    """

    def __init__(
        self,
        session_factory: Optional[Callable] = None,
        embedding_dimension: int = 1536,
        max_retries: int = 2
    ):
        super().__init__("pgvector", max_retries)
        self.session_factory = session_factory
        self.embedding_dimension = embedding_dimension

    async def _get_embedding(self, text_str: str) -> List[float]:
        """
        Get embedding vector for text.
        In production, this calls OpenAI or other embedding API.
        For now, returns a mock or uses database function.
        """
        return [0.0] * self.embedding_dimension

    async def _execute_impl(self, query: str, **kwargs) -> ToolResult:
        """
        Execute semantic search query.

        Args:
            query: The natural language query to search for
            document_type: Optional filter for document type
            limit: Maximum results (default 10)
            threshold: Minimum similarity threshold (default 0.7)
        """
        if self.session_factory is None:
            return ToolResult(
                success=False,
                error="Session factory not provided",
                row_count=0,
                query_executed=query
            )

        import asyncio

        # Get embedding for the query text
        embedding = await self._get_embedding(query)

        # Get parameters
        document_type = kwargs.get('document_type')
        limit = kwargs.get('limit', 10)
        threshold = kwargs.get('threshold', 0.7)

        # Build query
        sql = """
            SELECT
                dc.id,
                dc.document_id,
                dc.document_type,
                dc.content,
                dc.metadata,
                1 - (dc.embedding <=> :embedding) as similarity
            FROM document_chunks dc
            WHERE 1 - (dc.embedding <=> :embedding) > :threshold
        """

        if document_type:
            sql += " AND dc.document_type = :document_type"

        sql += """
            ORDER BY dc.embedding <=> :embedding
            LIMIT :limit
        """

        def _sync_execute():
            session = None
            try:
                session = self.session_factory()
                # Execute
                result = session.execute(
                    text(sql),
                    {
                        "embedding": embedding,
                        "threshold": threshold,
                        "limit": limit,
                        "document_type": document_type
                    }
                )

                rows = result.mappings().all()

                data = []
                for row in rows:
                    row_dict = dict(row)
                    # Convert non-serializable types
                    for key, value in list(row_dict.items()):
                        if hasattr(value, 'isoformat'):
                            row_dict[key] = value.isoformat()
                        elif key == 'embedding':
                            row_dict[key] = list(value) if value else None
                    data.append(row_dict)

                return ToolResult(
                    success=True,
                    data=data,
                    row_count=len(data),
                    query_executed=sql
                )

            except Exception as e:
                logger.error("pgvector query failed", query=sql, error=str(e))
                return ToolResult(
                    success=False,
                    error=str(e),
                    row_count=0,
                    query_executed=sql
                )
            finally:
                if session:
                    session.close()

        # Run synchronous query in thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_execute)

    def is_available(self) -> bool:
        """Check if pgvector tool is available."""
        # TODO: Implement actual table existence check
        # For now, return False since document_chunks table doesn't exist yet
        return False

    def get_schema_description(self) -> str:
        """Return schema description for LLM."""
        return self.SCHEMA_DESCRIPTION
