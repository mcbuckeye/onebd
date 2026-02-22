"""
BD Intelligence Platform - Services

Service modules for:
- Database connections
- SEC EDGAR fetching
- Document parsing
- Chunking and embedding
- Deal extraction
- Graph synchronization
- Entity resolution

Imported and adapted from Edgar BD project.
"""
from unified_api.services.edgar import EDGARClient, get_edgar_client
from unified_api.services.parse import DocumentParser, parse_document
from unified_api.services.chunk import ChunkingStrategy, TextChunk, get_chunker, chunk_text
from unified_api.services.embed import (
    EmbeddingProvider,
    OpenAIEmbedding,
    OllamaEmbedding,
    get_embedding_provider,
    embed_text,
    embed_texts,
)
from unified_api.services.graph_sync import GraphSyncService, get_graph_sync_service
from unified_api.services.database import (
    get_cortellis_engine,
    get_edgar_engine,
    get_cortellis_session,
    get_edgar_session,
    check_cortellis_connection,
    check_edgar_connection,
)
from unified_api.services.entity_resolution import (
    EntityResolutionService,
    CompanyMatch,
    get_entity_resolution_service,
)

__all__ = [
    # EDGAR
    "EDGARClient",
    "get_edgar_client",
    # Parsing
    "DocumentParser",
    "parse_document",
    # Chunking
    "ChunkingStrategy",
    "TextChunk",
    "get_chunker",
    "chunk_text",
    # Embedding
    "EmbeddingProvider",
    "OpenAIEmbedding",
    "OllamaEmbedding",
    "get_embedding_provider",
    "embed_text",
    "embed_texts",
    # Graph Sync
    "GraphSyncService",
    "get_graph_sync_service",
    # Database
    "get_cortellis_engine",
    "get_edgar_engine",
    "get_cortellis_session",
    "get_edgar_session",
    "check_cortellis_connection",
    "check_edgar_connection",
    # Entity Resolution
    "EntityResolutionService",
    "CompanyMatch",
    "get_entity_resolution_service",
]
