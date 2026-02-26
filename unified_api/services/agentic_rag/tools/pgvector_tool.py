"""
pgvector tool for semantic search on contracts and Edgar filings.
"""
from typing import Any, Callable, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
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
        session_factory: Optional[Callable[[], AsyncSession]] = None,
        embedding_dimension: int = 1536,
        max_retries: int = 2
    ):
        super().__init__("pgvector", max_retries)
        self.session_factory = session_factory
        self.embedding_dimension = embedding_dimension

    async def _get_embedding(self, text: str) -> List[float]:
        """
        Get embedding vector for text.
        In production, this calls OpenAI or other embedding API.
        For now, returns a mock or uses database function.
        """
        # TODO: Implement actual embedding call
        # This is a placeholder - real implementation would call:
        # - OpenAI text-embedding-3-small
        # - Azure OpenAI embeddings
        # - Or use pgvector's built-in embedding function
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
                row_count=0
            )

        session = None
        try:
            session = self.session_factory()

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

            # Get embedding for the query text
            embedding = await self._get_embedding(query)

            # Execute
            result = await session.execute(
                sql,
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
                # Convert metadata JSON if needed
                if isinstance(row_dict.get('metadata'), str):
                    import json
                    try:
                        row_dict['metadata'] = json.loads(row_dict['metadata'])
                    except json.JSONDecodeError:
                        pass
                data.append(row_dict)

            return ToolResult(
                success=True,
                data=data,
                row_count=len(data),
                query_executed=f"Semantic search: {query}"
            )

        except Exception as e:
            logger.error("pgvector query failed", query=query, error=str(e))
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
        """Check if pgvector tool is available."""
        return self.session_factory is not None

    def get_schema_description(self) -> str:
        """Return schema description for LLM."""
        return self.SCHEMA_DESCRIPTION

    async def hybrid_search(
        self,
        semantic_query: str,
        keyword_query: Optional[str] = None,
        document_type: Optional[str] = None,
        limit: int = 10
    ) -> ToolResult:
        """
        Perform hybrid search combining semantic and keyword matching.
        More sophisticated than pure semantic search.
        """
        if self.session_factory is None:
            return ToolResult(
                success=False,
                error="Session factory not provided",
                row_count=0
            )

        session = None
        try:
            session = self.session_factory()

            # Get embedding
            embedding = await self._get_embedding(semantic_query)

            # Build hybrid query
            sql = """
                SELECT
                    dc.id,
                    dc.document_id,
                    dc.document_type,
                    dc.content,
                    dc.metadata,
                    -- Semantic score
                    1 - (dc.embedding <=> :embedding) as semantic_score,
                    -- Keyword score (if provided)
                    CASE
                        WHEN :keyword_query IS NOT NULL AND dc.content ILIKE :keyword_pattern
                        THEN 0.3
                        ELSE 0.0
                    END as keyword_score,
                    -- Combined score
                    (1 - (dc.embedding <=> :embedding)) * 0.7 +
                    CASE
                        WHEN :keyword_query IS NOT NULL AND dc.content ILIKE :keyword_pattern
                        THEN 0.3
                        ELSE 0.0
                    END as combined_score
                FROM document_chunks dc
                WHERE 1 - (dc.embedding <=> :embedding) > 0.5
            """

            if document_type:
                sql += " AND dc.document_type = :document_type"

            sql += " ORDER BY combined_score DESC LIMIT :limit"

            result = await session.execute(
                sql,
                {
                    "embedding": embedding,
                    "keyword_query": keyword_query,
                    "keyword_pattern": f"%{keyword_query}%" if keyword_query else None,
                    "document_type": document_type,
                    "limit": limit
                }
            )

            rows = result.mappings().all()
            data = [dict(row) for row in rows]

            return ToolResult(
                success=True,
                data=data,
                row_count=len(data),
                query_executed=f"Hybrid search: semantic='{semantic_query}', keyword='{keyword_query}'"
            )

        except Exception as e:
            logger.error("Hybrid search failed", error=str(e))
            return ToolResult(
                success=False,
                error=str(e),
                row_count=0
            )
        finally:
            if session:
                await session.close()