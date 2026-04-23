"""Configuration properties and enums for the KnowledgeBase construct."""

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
                chunking_strategy=ChunkingStrategy.FIXED_SIZE,
                chunk_max_tokens=500,
                chunk_overlap_percentage=15,
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
    chunking_strategy: ChunkingStrategy = ChunkingStrategy.NONE
    """How source documents are split before embedding."""

    chunk_max_tokens: int = 300
    """Maximum tokens per chunk (used with ``FIXED_SIZE``)."""

    chunk_overlap_percentage: int = 20
    """Percentage overlap between consecutive chunks (used with ``FIXED_SIZE``)."""

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
