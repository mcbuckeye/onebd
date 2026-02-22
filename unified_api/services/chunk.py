"""
Text chunking service with token-based splitting and section awareness

Imported from Edgar BD project and adapted for unified platform.
"""
from dataclasses import dataclass
from typing import List, Optional

import tiktoken
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class TextChunk:
    """Represents a text chunk with metadata"""
    text: str
    chunk_index: int
    section: Optional[str] = None
    token_count: Optional[int] = None


class ChunkingStrategy:
    """Token-based chunking with configurable size and overlap"""

    def __init__(
        self,
        chunk_size: int = 800,
        chunk_overlap: int = 125,
        model: str = "cl100k_base",  # GPT-4, text-embedding-3-* tokenizer
    ):
        """
        Initialize chunking strategy

        Args:
            chunk_size: Target chunk size in tokens (default 800, range 600-1000)
            chunk_overlap: Overlap between chunks in tokens (default 125, range 100-150)
            model: Tokenizer model name
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        try:
            self.tokenizer = tiktoken.get_encoding(model)
        except Exception as e:
            logger.warning(f"Failed to load tokenizer {model}, using cl100k_base", error=str(e))
            self.tokenizer = tiktoken.get_encoding("cl100k_base")

        logger.info(
            "Chunking strategy initialized",
            chunk_size=chunk_size,
            overlap=chunk_overlap,
            tokenizer=model,
        )

    def count_tokens(self, text: str) -> int:
        """Count tokens in text"""
        return len(self.tokenizer.encode(text))

    def chunk_text(
        self,
        text: str,
        section: Optional[str] = None,
        preserve_paragraphs: bool = True,
    ) -> List[TextChunk]:
        """
        Chunk text into overlapping segments

        Args:
            text: Text to chunk
            section: Optional section identifier (e.g., "Item 1.01")
            preserve_paragraphs: Try to avoid splitting paragraphs mid-sentence

        Returns:
            List of TextChunk objects
        """
        if not text or not text.strip():
            return []

        # Encode full text
        tokens = self.tokenizer.encode(text)
        total_tokens = len(tokens)

        if total_tokens <= self.chunk_size:
            # Text fits in single chunk
            return [
                TextChunk(
                    text=text,
                    chunk_index=0,
                    section=section,
                    token_count=total_tokens,
                )
            ]

        chunks = []
        chunk_index = 0
        start_idx = 0

        while start_idx < total_tokens:
            # Extract chunk tokens
            end_idx = min(start_idx + self.chunk_size, total_tokens)
            chunk_tokens = tokens[start_idx:end_idx]

            # Decode chunk
            chunk_text = self.tokenizer.decode(chunk_tokens)

            # Try to end at paragraph boundary if we're not at the end
            if preserve_paragraphs and end_idx < total_tokens:
                chunk_text = self._adjust_chunk_boundary(chunk_text)
                # Re-encode to get actual token count after adjustment
                chunk_tokens = self.tokenizer.encode(chunk_text)

            chunks.append(
                TextChunk(
                    text=chunk_text,
                    chunk_index=chunk_index,
                    section=section,
                    token_count=len(chunk_tokens),
                )
            )

            chunk_index += 1

            # Move start position with overlap
            if end_idx >= total_tokens:
                break

            start_idx = end_idx - self.chunk_overlap

        logger.debug(
            "Text chunked",
            section=section,
            total_tokens=total_tokens,
            num_chunks=len(chunks),
        )

        return chunks

    def _adjust_chunk_boundary(self, text: str) -> str:
        """
        Adjust chunk boundary to end at a sentence or paragraph break

        Args:
            text: Chunk text to adjust

        Returns:
            Adjusted text ending at a natural boundary
        """
        # Try to find last paragraph break
        last_double_newline = text.rfind("\n\n")
        if last_double_newline > len(text) * 0.7:
            return text[: last_double_newline + 2].rstrip()

        # Try to find last sentence ending
        sentence_endings = [". ", ".\n", "! ", "!\n", "? ", "?\n"]
        last_sentence = -1

        for ending in sentence_endings:
            idx = text.rfind(ending)
            if idx > last_sentence and idx > len(text) * 0.7:
                last_sentence = idx

        if last_sentence > 0:
            return text[: last_sentence + 1].rstrip()

        # No good boundary found, return as-is
        return text

    def chunk_document_by_sections(
        self,
        sections: List[tuple[str, str]],
    ) -> List[TextChunk]:
        """
        Chunk a document that's already been split into sections

        Args:
            sections: List of (section_name, section_text) tuples

        Returns:
            List of TextChunk objects with section metadata
        """
        all_chunks = []

        for section_name, section_text in sections:
            section_chunks = self.chunk_text(section_text, section=section_name)
            all_chunks.extend(section_chunks)

        logger.info(
            "Document chunked by sections",
            num_sections=len(sections),
            total_chunks=len(all_chunks),
        )

        return all_chunks


# Default chunker instance
_default_chunker: Optional[ChunkingStrategy] = None


def get_chunker(
    chunk_size: int = 800,
    chunk_overlap: int = 125,
) -> ChunkingStrategy:
    """Get or create a chunker with the specified parameters"""
    global _default_chunker

    if _default_chunker is None:
        _default_chunker = ChunkingStrategy(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    return _default_chunker


def chunk_text(text: str, section: Optional[str] = None) -> List[TextChunk]:
    """Convenience function to chunk text using default chunker"""
    chunker = get_chunker()
    return chunker.chunk_text(text, section=section)
