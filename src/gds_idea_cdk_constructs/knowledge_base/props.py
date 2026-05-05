"""Configuration properties and enums for the KnowledgeBase construct."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ChunkingStrategy(StrEnum):
    """Chunking strategies for knowledge base data ingestion.

    Controls how source documents are split into chunks before embedding.

    Attributes:
        NONE: No chunking — each file is embedded as a single document.
            Best for short, atomic documents (e.g., individual profiles).
        FIXED_SIZE: Split documents into fixed-size token chunks with overlap.
            Good general-purpose option for long documents.
        HIERARCHICAL: Two-level chunking with parent and child chunks.
            Useful for structured documents with natural hierarchy.
        SEMANTIC: Split on semantic boundaries (e.g., paragraphs, sections).
            Best for documents where meaning-based boundaries matter.
    """

    NONE = "NONE"
    FIXED_SIZE = "FIXED_SIZE"
    HIERARCHICAL = "HIERARCHICAL"
    SEMANTIC = "SEMANTIC"


class StorageType(StrEnum):
    """Vector storage backends for the knowledge base.

    Attributes:
        S3_VECTORS: Amazon S3 Vectors — serverless vector storage built on S3.
    """

    S3_VECTORS = "S3_VECTORS"


class EmbeddingModel(StrEnum):
    """Supported embedding models for knowledge base vectorisation.

    Each value is the Bedrock foundation model ID.

    Attributes:
        TITAN_V2: Amazon Titan Text Embeddings V2 (1024 dimensions by default).
        COHERE_ENGLISH_V3: Cohere Embed English v3 (1024 dimensions by default).
        COHERE_MULTILINGUAL_V3: Cohere Embed Multilingual v3
            (1024 dimensions by default).
    """

    TITAN_V2 = "amazon.titan-embed-text-v2:0"
    COHERE_ENGLISH_V3 = "cohere.embed-english-v3"
    COHERE_MULTILINGUAL_V3 = "cohere.embed-multilingual-v3"


# Default dimensions per embedding model.
# Used when the caller does not explicitly set embedding_dimensions.
EMBEDDING_MODEL_DEFAULTS: dict[EmbeddingModel, int] = {
    EmbeddingModel.TITAN_V2: 1024,
    EmbeddingModel.COHERE_ENGLISH_V3: 1024,
    EmbeddingModel.COHERE_MULTILINGUAL_V3: 1024,
}


# -- Chunking configuration --


@dataclass
class ChunkingConfig:
    """Base chunking configuration.

    Use the static factory methods to create the appropriate variant:

    - :meth:`none` — no chunking (default)
    - :meth:`fixed_size` — fixed-size token chunks with overlap
    - :meth:`hierarchical` — two-level parent/child chunks
    - :meth:`semantic` — split on semantic boundaries

    Example:
        ::

            ChunkingConfig.none()
            ChunkingConfig.fixed_size(max_tokens=500, overlap_percentage=15)
            ChunkingConfig.semantic(max_tokens=400)
    """

    strategy: ChunkingStrategy

    @staticmethod
    def none() -> ChunkingConfig:
        """Create a no-chunking configuration.

        Each source file is embedded as a single document.  Best for
        short, atomic documents (e.g., individual profiles).
        """
        return ChunkingConfig(strategy=ChunkingStrategy.NONE)

    @staticmethod
    def fixed_size(
        max_tokens: int = 300,
        overlap_percentage: int = 20,
    ) -> FixedSizeChunkingConfig:
        """Create a fixed-size chunking configuration.

        Args:
            max_tokens: Maximum tokens per chunk.
            overlap_percentage: Percentage overlap between consecutive
                chunks (0–100).
        """
        return FixedSizeChunkingConfig(
            strategy=ChunkingStrategy.FIXED_SIZE,
            max_tokens=max_tokens,
            overlap_percentage=overlap_percentage,
        )

    @staticmethod
    def hierarchical(
        max_tokens: int = 300,
        overlap_percentage: int = 20,
    ) -> HierarchicalChunkingConfig:
        """Create a hierarchical (two-level) chunking configuration.

        Parent chunks are ``max_tokens * 5`` tokens; child chunks are
        ``max_tokens`` tokens.  Overlap is computed as
        ``max_tokens * overlap_percentage / 100`` tokens.

        Args:
            max_tokens: Maximum tokens per child chunk.
            overlap_percentage: Percentage of ``max_tokens`` used as
                overlap between chunks (0–100).
        """
        return HierarchicalChunkingConfig(
            strategy=ChunkingStrategy.HIERARCHICAL,
            max_tokens=max_tokens,
            overlap_percentage=overlap_percentage,
        )

    @staticmethod
    def semantic(
        max_tokens: int = 300,
        buffer_size: int = 0,
        breakpoint_percentile_threshold: int = 95,
    ) -> SemanticChunkingConfig:
        """Create a semantic chunking configuration.

        Splits documents on semantic boundaries (e.g., paragraphs,
        topic shifts).

        Args:
            max_tokens: Maximum tokens per chunk.
            buffer_size: Number of surrounding sentences to include
                for context when evaluating breakpoints.
            breakpoint_percentile_threshold: Percentile threshold
                (0–100) for detecting semantic breakpoints.
        """
        return SemanticChunkingConfig(
            strategy=ChunkingStrategy.SEMANTIC,
            max_tokens=max_tokens,
            buffer_size=buffer_size,
            breakpoint_percentile_threshold=breakpoint_percentile_threshold,
        )


@dataclass
class FixedSizeChunkingConfig(ChunkingConfig):
    """Fixed-size chunking configuration.

    Attributes:
        max_tokens: Maximum tokens per chunk.
        overlap_percentage: Percentage overlap between consecutive chunks.
    """

    max_tokens: int = 300
    overlap_percentage: int = 20


@dataclass
class HierarchicalChunkingConfig(ChunkingConfig):
    """Hierarchical (two-level) chunking configuration.

    Attributes:
        max_tokens: Maximum tokens per child chunk.
            Parent chunks use ``max_tokens * 5``.
        overlap_percentage: Percentage of ``max_tokens`` used as
            overlap between chunks.
    """

    max_tokens: int = 300
    overlap_percentage: int = 20


@dataclass
class SemanticChunkingConfig(ChunkingConfig):
    """Semantic chunking configuration.

    Attributes:
        max_tokens: Maximum tokens per chunk.
        buffer_size: Number of surrounding sentences for context.
        breakpoint_percentile_threshold: Percentile threshold for
            detecting semantic breakpoints.
    """

    max_tokens: int = 300
    buffer_size: int = 0
    breakpoint_percentile_threshold: int = 95


# -- Main props --


@dataclass
class KnowledgeBaseProps:
    """Configuration properties for the KnowledgeBase stack.

    All fields have sensible defaults so ``KnowledgeBaseProps()`` is valid
    with no arguments.  Override individual fields to customise behaviour.

    Example:
        Default (no chunking, Titan V2, S3 Vectors)::

            props = KnowledgeBaseProps()

        Fixed-size chunking with auto-sync::

            props = KnowledgeBaseProps(
                chunking=ChunkingConfig.fixed_size(
                    max_tokens=500,
                    overlap_percentage=15,
                ),
                inclusion_prefixes=["documents/"],
                enable_auto_sync=True,
            )
    """

    # -- Storage --
    storage_type: StorageType = StorageType.S3_VECTORS
    """Vector storage backend.  Only S3_VECTORS is supported today."""

    # -- Embedding model --
    embedding_model: EmbeddingModel = EmbeddingModel.TITAN_V2
    """Bedrock foundation model used to generate embeddings."""

    embedding_dimensions: int | None = None
    """Vector dimensions.  When ``None`` the default for the chosen
    embedding model is used (see :data:`EMBEDDING_MODEL_DEFAULTS`)."""

    distance_metric: str = "cosine"
    """Distance metric for the vector index (cosine, euclidean, dotproduct)."""

    # -- Chunking --
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig.none)
    """How source documents are split before embedding."""

    # -- Data source --
    inclusion_prefixes: list[str] = field(default_factory=list)
    """S3 key prefixes to include during ingestion.  Empty means all objects."""

    data_deletion_policy: str = "DELETE"
    """What happens to vectors when source data is removed (DELETE or RETAIN)."""

    # -- Auto-sync --
    enable_auto_sync: bool = True
    """Enable SQS-debounced auto-sync when objects land in the data bucket."""

    sync_batch_window_seconds: int = 300
    """SQS batching window in seconds (max 300).  The Lambda is invoked once
    per window, regardless of how many S3 events arrive.  AWS SQS enforces a
    maximum of 300 seconds (5 minutes)."""

    # -- Lifecycle --
    retain_on_delete: bool = True
    """Use RETAIN removal policy for the data bucket and vector storage.
    Set to ``False`` only for development / throwaway stacks."""

    # -- Knowledge base metadata --
    description: str = ""
    """Optional description stored on the Bedrock Knowledge Base resource."""

    def resolved_embedding_dimensions(self) -> int:
        """Return the effective embedding dimensions.

        Returns:
            Explicit ``embedding_dimensions`` if set, otherwise the default
            for the chosen ``embedding_model``.
        """
        if self.embedding_dimensions is not None:
            return self.embedding_dimensions
        return EMBEDDING_MODEL_DEFAULTS.get(self.embedding_model, 1024)
