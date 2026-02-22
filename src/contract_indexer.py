"""Contract indexing service for full-text search and RAG embeddings."""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Generator

import tiktoken
from openai import OpenAI
from sqlalchemy import create_engine, text, func
from sqlalchemy.orm import sessionmaker, Session

from .config import AppConfig
from .models import DealContract, ContractContent, ContractChunk

logger = logging.getLogger(__name__)

# OpenAI embedding model config
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
MAX_TOKENS_PER_CHUNK = 512
CHUNK_OVERLAP_TOKENS = 50


class ContractIndexer:
    """Service for indexing contract documents for search and RAG."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.engine = create_engine(config.database.connection_string)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.contracts_dir = Path(config.contracts_dir)
        self.tokenizer = tiktoken.get_encoding("cl100k_base")

        if config.openai.api_key:
            self.openai_client = OpenAI(api_key=config.openai.api_key)
        else:
            self.openai_client = None

    def count_tokens(self, text: str) -> int:
        """Count tokens in text using tiktoken."""
        return len(self.tokenizer.encode(text))

    def chunk_text(self, text: str) -> Generator[tuple[int, str, int], None, None]:
        """Split text into overlapping chunks for embedding.

        Yields: (chunk_index, chunk_text, token_count)
        """
        tokens = self.tokenizer.encode(text)
        total_tokens = len(tokens)

        if total_tokens == 0:
            return

        chunk_index = 0
        start = 0

        while start < total_tokens:
            end = min(start + MAX_TOKENS_PER_CHUNK, total_tokens)
            chunk_tokens = tokens[start:end]
            chunk_text = self.tokenizer.decode(chunk_tokens)

            yield chunk_index, chunk_text, len(chunk_tokens)

            chunk_index += 1
            # Move start forward, accounting for overlap
            start = end - CHUNK_OVERLAP_TOKENS if end < total_tokens else total_tokens

    def read_contract_text(self, contract: DealContract) -> Optional[str]:
        """Read the text content of a contract from file."""
        if not contract.text_file_path:
            return None

        # Handle both relative and absolute paths
        file_path = Path(contract.text_file_path)
        if not file_path.is_absolute():
            file_path = self.contracts_dir.parent / contract.text_file_path

        if not file_path.exists():
            logger.warning(f"Contract text file not found: {file_path}")
            return None

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error reading contract file {file_path}: {e}")
            return None

    def index_contracts_fulltext(
        self,
        batch_size: int = 100,
        force_reindex: bool = False,
    ) -> dict:
        """Index contract text files for full-text search.

        Args:
            batch_size: Number of contracts to process per batch
            force_reindex: If True, reindex all contracts (otherwise skip existing)

        Returns:
            dict with stats about the indexing operation
        """
        stats = {
            "total_contracts": 0,
            "indexed": 0,
            "skipped": 0,
            "errors": 0,
        }

        with self.SessionLocal() as session:
            # Get contracts with text files
            query = session.query(DealContract).filter(
                DealContract.text_file_path.isnot(None)
            )

            if not force_reindex:
                # Skip already indexed contracts
                indexed_ids = session.query(ContractContent.contract_id).subquery()
                query = query.filter(~DealContract.id.in_(indexed_ids))

            contracts = query.all()
            stats["total_contracts"] = len(contracts)
            logger.info(f"Found {len(contracts)} contracts to index")

            for i, contract in enumerate(contracts):
                try:
                    content = self.read_contract_text(contract)
                    if not content or len(content.strip()) == 0:
                        stats["skipped"] += 1
                        continue

                    word_count = len(content.split())

                    # Create or update ContractContent
                    existing = session.query(ContractContent).filter(
                        ContractContent.contract_id == contract.id
                    ).first()

                    if existing:
                        existing.content = content
                        existing.word_count = word_count
                        existing.indexed_at = datetime.utcnow()
                    else:
                        cc = ContractContent(
                            contract_id=contract.id,
                            deal_id=contract.deal_id,
                            content=content,
                            word_count=word_count,
                        )
                        session.add(cc)

                    stats["indexed"] += 1

                    # Commit in batches
                    if (i + 1) % batch_size == 0:
                        session.commit()
                        logger.info(f"Indexed {i + 1}/{len(contracts)} contracts")

                except Exception as e:
                    logger.error(f"Error indexing contract {contract.id}: {e}")
                    stats["errors"] += 1

            # Final commit
            session.commit()

            # Update tsvector column using PostgreSQL's to_tsvector
            logger.info("Updating full-text search vectors...")
            session.execute(text("""
                UPDATE contract_content
                SET content_tsvector = to_tsvector('english', content)
                WHERE content_tsvector IS NULL
            """))
            session.commit()

        logger.info(f"Indexing complete: {stats}")
        return stats

    def embed_contracts(
        self,
        batch_size: int = 50,
        api_batch_size: int = 100,
        force_reembed: bool = False,
    ) -> dict:
        """Generate embeddings for contract chunks.

        Args:
            batch_size: Number of contracts to process per batch
            api_batch_size: Number of chunks to embed per API call
            force_reembed: If True, regenerate all embeddings

        Returns:
            dict with stats about the embedding operation
        """
        if not self.openai_client:
            raise ValueError("OpenAI API key not configured")

        stats = {
            "total_contracts": 0,
            "contracts_processed": 0,
            "chunks_created": 0,
            "chunks_embedded": 0,
            "errors": 0,
        }

        with self.SessionLocal() as session:
            # Get contracts with indexed content
            query = session.query(ContractContent)

            if not force_reembed:
                # Skip contracts that already have chunks with embeddings
                embedded_ids = session.query(ContractChunk.contract_id).filter(
                    ContractChunk.embedding.isnot(None)
                ).distinct().subquery()
                query = query.filter(~ContractContent.contract_id.in_(embedded_ids))

            contracts = query.all()
            stats["total_contracts"] = len(contracts)
            logger.info(f"Found {len(contracts)} contracts to embed")

            # Collect all chunks first
            all_chunks = []

            for contract in contracts:
                try:
                    # Delete existing chunks if re-embedding
                    if force_reembed:
                        session.query(ContractChunk).filter(
                            ContractChunk.contract_id == contract.contract_id
                        ).delete()

                    # Create chunks
                    for chunk_idx, chunk_text, token_count in self.chunk_text(contract.content):
                        chunk = ContractChunk(
                            contract_id=contract.contract_id,
                            deal_id=contract.deal_id,
                            chunk_index=chunk_idx,
                            content=chunk_text,
                            token_count=token_count,
                        )
                        session.add(chunk)
                        all_chunks.append(chunk)
                        stats["chunks_created"] += 1

                    stats["contracts_processed"] += 1

                except Exception as e:
                    logger.error(f"Error chunking contract {contract.contract_id}: {e}")
                    stats["errors"] += 1

            # Commit chunks
            session.commit()
            logger.info(f"Created {stats['chunks_created']} chunks")

            # Generate embeddings in batches
            logger.info("Generating embeddings...")
            for i in range(0, len(all_chunks), api_batch_size):
                batch = all_chunks[i:i + api_batch_size]
                texts = [c.content for c in batch]

                try:
                    response = self.openai_client.embeddings.create(
                        model=EMBEDDING_MODEL,
                        input=texts,
                    )

                    for j, embedding_data in enumerate(response.data):
                        batch[j].embedding = embedding_data.embedding
                        stats["chunks_embedded"] += 1

                    session.commit()
                    logger.info(f"Embedded {min(i + api_batch_size, len(all_chunks))}/{len(all_chunks)} chunks")

                except Exception as e:
                    logger.error(f"Error generating embeddings for batch starting at {i}: {e}")
                    stats["errors"] += 1

        logger.info(f"Embedding complete: {stats}")
        return stats

    def resume_embedding(
        self,
        api_batch_size: int = 2000,
    ) -> dict:
        """Resume embedding chunks that don't have embeddings yet.

        This is optimized for resuming interrupted embedding jobs.
        Uses larger batch sizes (OpenAI supports up to 2048 per call).

        Args:
            api_batch_size: Number of chunks to embed per API call (max 2048)

        Returns:
            dict with stats about the embedding operation
        """
        if not self.openai_client:
            raise ValueError("OpenAI API key not configured")

        stats = {
            "total_unembedded": 0,
            "chunks_embedded": 0,
            "errors": 0,
        }

        with self.SessionLocal() as session:
            # Count unembedded chunks
            total = session.execute(text(
                "SELECT COUNT(*) FROM contract_chunks WHERE embedding IS NULL"
            )).scalar()
            stats["total_unembedded"] = total
            logger.info(f"Found {total:,} chunks without embeddings")

            if total == 0:
                return stats

            # Process in batches directly from DB
            offset = 0
            while True:
                # Fetch batch of unembedded chunks
                result = session.execute(text("""
                    SELECT id, content
                    FROM contract_chunks
                    WHERE embedding IS NULL
                    ORDER BY id
                    LIMIT :limit
                """), {"limit": api_batch_size})

                rows = result.fetchall()
                if not rows:
                    break

                chunk_ids = [r.id for r in rows]
                texts = [r.content for r in rows]

                try:
                    response = self.openai_client.embeddings.create(
                        model=EMBEDDING_MODEL,
                        input=texts,
                    )

                    # Update embeddings in batch
                    for i, embedding_data in enumerate(response.data):
                        session.execute(text("""
                            UPDATE contract_chunks
                            SET embedding = :embedding
                            WHERE id = :id
                        """), {
                            "embedding": str(embedding_data.embedding),
                            "id": chunk_ids[i]
                        })

                    session.commit()
                    stats["chunks_embedded"] += len(rows)
                    logger.info(f"Embedded {stats['chunks_embedded']:,}/{total:,} chunks ({stats['chunks_embedded']*100/total:.1f}%)")

                except Exception as e:
                    logger.error(f"Error generating embeddings: {e}")
                    stats["errors"] += 1
                    # Continue to next batch on error
                    session.rollback()

        logger.info(f"Resume embedding complete: {stats}")
        return stats

    def search_fulltext(
        self,
        query: str,
        limit: int = 20,
    ) -> List[dict]:
        """Search contracts using PostgreSQL full-text search.

        Args:
            query: Search query (supports PostgreSQL tsquery syntax)
            limit: Maximum results to return

        Returns:
            List of matching contracts with relevance info
        """
        with self.SessionLocal() as session:
            # Build tsquery from the input
            result = session.execute(text("""
                SELECT
                    cc.id,
                    cc.contract_id,
                    cc.deal_id,
                    d.title as deal_title,
                    dc.contract_types,
                    cc.word_count,
                    ts_rank(cc.content_tsvector, plainto_tsquery('english', :query)) as rank,
                    ts_headline('english', cc.content, plainto_tsquery('english', :query),
                        'MaxWords=50, MinWords=20, StartSel=**, StopSel=**') as snippet
                FROM contract_content cc
                JOIN deals d ON d.id = cc.deal_id
                JOIN deal_contracts dc ON dc.id = cc.contract_id
                WHERE cc.content_tsvector @@ plainto_tsquery('english', :query)
                ORDER BY rank DESC
                LIMIT :limit
            """), {"query": query, "limit": limit})

            return [
                {
                    "id": row.id,
                    "contract_id": row.contract_id,
                    "deal_id": row.deal_id,
                    "deal_title": row.deal_title,
                    "contract_types": row.contract_types,
                    "word_count": row.word_count,
                    "rank": row.rank,
                    "snippet": row.snippet,
                }
                for row in result
            ]

    def search_similar(
        self,
        query: str,
        limit: int = 10,
    ) -> List[dict]:
        """Search contracts using vector similarity (RAG).

        Args:
            query: Natural language query
            limit: Maximum results to return

        Returns:
            List of similar contract chunks with deal context
        """
        if not self.openai_client:
            raise ValueError("OpenAI API key not configured")

        # Generate embedding for query
        response = self.openai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=[query],
        )
        query_embedding = response.data[0].embedding

        with self.SessionLocal() as session:
            # Use pgvector's cosine distance operator
            result = session.execute(text("""
                SELECT
                    cc.id,
                    cc.contract_id,
                    cc.deal_id,
                    cc.chunk_index,
                    cc.content,
                    cc.token_count,
                    d.title as deal_title,
                    dc.contract_types,
                    1 - (cc.embedding <=> :embedding::vector) as similarity
                FROM contract_chunks cc
                JOIN deals d ON d.id = cc.deal_id
                JOIN deal_contracts dc ON dc.id = cc.contract_id
                WHERE cc.embedding IS NOT NULL
                ORDER BY cc.embedding <=> :embedding::vector
                LIMIT :limit
            """), {"embedding": str(query_embedding), "limit": limit})

            return [
                {
                    "id": row.id,
                    "contract_id": row.contract_id,
                    "deal_id": row.deal_id,
                    "chunk_index": row.chunk_index,
                    "content": row.content,
                    "token_count": row.token_count,
                    "deal_title": row.deal_title,
                    "contract_types": row.contract_types,
                    "similarity": row.similarity,
                }
                for row in result
            ]

    def get_stats(self) -> dict:
        """Get indexing statistics."""
        with self.SessionLocal() as session:
            total_contracts = session.query(func.count(DealContract.id)).filter(
                DealContract.text_file_path.isnot(None)
            ).scalar()

            indexed_contracts = session.query(func.count(ContractContent.id)).scalar()

            total_chunks = session.query(func.count(ContractChunk.id)).scalar()

            embedded_chunks = session.query(func.count(ContractChunk.id)).filter(
                ContractChunk.embedding.isnot(None)
            ).scalar()

            return {
                "total_text_contracts": total_contracts,
                "indexed_for_fulltext": indexed_contracts,
                "total_chunks": total_chunks,
                "embedded_chunks": embedded_chunks,
            }
