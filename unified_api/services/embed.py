"""
Embedding service with pluggable providers (OpenAI, Ollama)

Imported from Edgar BD project and adapted for unified platform.
"""
from typing import List, Optional

import httpx
from openai import AsyncOpenAI
import structlog

from unified_api.config import settings

logger = structlog.get_logger(__name__)


class EmbeddingProvider:
    """Base class for embedding providers"""

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts"""
        raise NotImplementedError

    async def embed_single(self, text: str) -> List[float]:
        """Generate embedding for a single text"""
        embeddings = await self.embed([text])
        return embeddings[0]


class OpenAIEmbedding(EmbeddingProvider):
    """OpenAI embedding provider"""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.openai_api_key
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI embeddings")

        self.client = AsyncOpenAI(api_key=self.api_key)
        self.model = model or settings.embedding_model
        self.expected_dim = settings.vector_dim

        logger.info("OpenAI embedding provider initialized", model=self.model, dim=self.expected_dim)

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using OpenAI API"""
        if not texts:
            return []

        try:
            # OpenAI allows up to 2048 texts per request for text-embedding-3-*
            # We'll batch in chunks of 100 to be safe
            batch_size = 100
            all_embeddings = []

            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]

                response = await self.client.embeddings.create(
                    input=batch,
                    model=self.model,
                )

                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)

                logger.debug(
                    "Generated embeddings batch",
                    batch_num=i // batch_size + 1,
                    batch_size=len(batch),
                    total=len(texts),
                )

            logger.info("OpenAI embeddings generated", count=len(all_embeddings))
            return all_embeddings

        except Exception as e:
            logger.error("OpenAI embedding failed", error=str(e))
            raise


class OllamaEmbedding(EmbeddingProvider):
    """Ollama embedding provider (local)"""

    def __init__(self, base_url: str = "http://localhost:11434", model: Optional[str] = None):
        self.base_url = base_url
        self.model = model or settings.embedding_model
        self.expected_dim = settings.vector_dim

        logger.info(
            "Ollama embedding provider initialized",
            base_url=self.base_url,
            model=self.model,
            dim=self.expected_dim,
        )

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using Ollama"""
        if not texts:
            return []

        all_embeddings = []

        async with httpx.AsyncClient(timeout=60.0) as client:
            for text in texts:
                try:
                    response = await client.post(
                        f"{self.base_url}/api/embeddings",
                        json={"model": self.model, "prompt": text},
                    )
                    response.raise_for_status()
                    data = response.json()
                    all_embeddings.append(data["embedding"])

                except Exception as e:
                    logger.error("Ollama embedding failed for text", error=str(e))
                    raise

        logger.info("Ollama embeddings generated", count=len(all_embeddings))
        return all_embeddings


def get_embedding_provider(provider: str = "openai") -> EmbeddingProvider:
    """Get the configured embedding provider"""
    provider = provider.lower()

    if provider == "openai":
        return OpenAIEmbedding()
    elif provider == "ollama":
        return OllamaEmbedding()
    else:
        raise ValueError(
            f"Unknown embedding provider: {provider}. "
            f"Valid options: openai, ollama"
        )


# Global provider instance (initialized on first use)
_provider: EmbeddingProvider | None = None


async def embed_texts(texts: List[str], provider: str = "openai") -> List[List[float]]:
    """Convenience function to embed texts using the configured provider"""
    global _provider
    if _provider is None:
        _provider = get_embedding_provider(provider)

    return await _provider.embed(texts)


async def embed_text(text: str, provider: str = "openai") -> List[float]:
    """Convenience function to embed a single text"""
    global _provider
    if _provider is None:
        _provider = get_embedding_provider(provider)

    return await _provider.embed_single(text)
