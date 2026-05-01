"""Unit tests for KnowledgeBaseProps, ChunkingConfig, and enums."""

import pytest

from gds_idea_cdk_constructs.knowledge_base.props import (
    EMBEDDING_MODEL_DEFAULTS,
    ChunkingConfig,
    ChunkingStrategy,
    EmbeddingModel,
    FixedSizeChunkingConfig,
    HierarchicalChunkingConfig,
    KnowledgeBaseProps,
    SemanticChunkingConfig,
    StorageType,
)

# -- Enum tests --


def test_chunking_strategy_values():
    """Test that ChunkingStrategy has expected members and string values."""
    assert ChunkingStrategy.NONE == "NONE"
    assert ChunkingStrategy.FIXED_SIZE == "FIXED_SIZE"
    assert ChunkingStrategy.HIERARCHICAL == "HIERARCHICAL"
    assert ChunkingStrategy.SEMANTIC == "SEMANTIC"
    assert len(ChunkingStrategy) == 4


def test_storage_type_values():
    """Test that StorageType has expected members."""
    assert StorageType.S3_VECTORS == "S3_VECTORS"
    assert len(StorageType) >= 1


def test_embedding_model_values():
    """Test that EmbeddingModel values are valid Bedrock model IDs."""
    assert EmbeddingModel.TITAN_V2 == "amazon.titan-embed-text-v2:0"
    assert EmbeddingModel.COHERE_ENGLISH_V3 == "cohere.embed-english-v3"
    assert EmbeddingModel.COHERE_MULTILINGUAL_V3 == "cohere.embed-multilingual-v3"


def test_embedding_model_defaults_cover_all_models():
    """Test that every EmbeddingModel has a default dimension in the lookup."""
    for model in EmbeddingModel:
        assert model in EMBEDDING_MODEL_DEFAULTS


# -- ChunkingConfig factory tests --


def test_chunking_config_none():
    """Test that ChunkingConfig.none() creates a NONE strategy config."""
    config = ChunkingConfig.none()
    assert config.strategy == ChunkingStrategy.NONE
    assert isinstance(config, ChunkingConfig)
    assert not isinstance(config, FixedSizeChunkingConfig)


def test_chunking_config_fixed_size_defaults():
    """Test that ChunkingConfig.fixed_size() has sensible defaults."""
    config = ChunkingConfig.fixed_size()
    assert config.strategy == ChunkingStrategy.FIXED_SIZE
    assert isinstance(config, FixedSizeChunkingConfig)
    assert config.max_tokens == 300
    assert config.overlap_percentage == 20


def test_chunking_config_fixed_size_custom():
    """Test that ChunkingConfig.fixed_size() accepts custom values."""
    config = ChunkingConfig.fixed_size(max_tokens=500, overlap_percentage=15)
    assert isinstance(config, FixedSizeChunkingConfig)
    assert config.max_tokens == 500
    assert config.overlap_percentage == 15


def test_chunking_config_hierarchical_defaults():
    """Test that ChunkingConfig.hierarchical() has sensible defaults."""
    config = ChunkingConfig.hierarchical()
    assert config.strategy == ChunkingStrategy.HIERARCHICAL
    assert isinstance(config, HierarchicalChunkingConfig)
    assert config.max_tokens == 300
    assert config.overlap_percentage == 20


def test_chunking_config_hierarchical_custom():
    """Test that ChunkingConfig.hierarchical() accepts custom values."""
    config = ChunkingConfig.hierarchical(max_tokens=400, overlap_percentage=10)
    assert isinstance(config, HierarchicalChunkingConfig)
    assert config.max_tokens == 400
    assert config.overlap_percentage == 10


def test_chunking_config_semantic_defaults():
    """Test that ChunkingConfig.semantic() has sensible defaults."""
    config = ChunkingConfig.semantic()
    assert config.strategy == ChunkingStrategy.SEMANTIC
    assert isinstance(config, SemanticChunkingConfig)
    assert config.max_tokens == 300
    assert config.buffer_size == 0
    assert config.breakpoint_percentile_threshold == 95


def test_chunking_config_semantic_custom():
    """Test that ChunkingConfig.semantic() accepts custom values."""
    config = ChunkingConfig.semantic(
        max_tokens=400,
        buffer_size=2,
        breakpoint_percentile_threshold=90,
    )
    assert isinstance(config, SemanticChunkingConfig)
    assert config.max_tokens == 400
    assert config.buffer_size == 2
    assert config.breakpoint_percentile_threshold == 90


# -- KnowledgeBaseProps defaults --


def test_knowledge_base_props_defaults():
    """Test that KnowledgeBaseProps has sensible defaults."""
    props = KnowledgeBaseProps()

    assert props.storage_type == StorageType.S3_VECTORS
    assert props.embedding_model == EmbeddingModel.TITAN_V2
    assert props.embedding_dimensions is None
    assert props.distance_metric == "cosine"
    assert props.chunking.strategy == ChunkingStrategy.NONE
    assert props.inclusion_prefixes == []
    assert props.data_deletion_policy == "DELETE"
    assert props.enable_auto_sync is True
    assert props.sync_batch_window_seconds == 300
    assert props.retain_on_delete is True
    assert props.description == ""


def test_knowledge_base_props_custom_values():
    """Test that KnowledgeBaseProps accepts custom values."""
    props = KnowledgeBaseProps(
        storage_type=StorageType.S3_VECTORS,
        embedding_model=EmbeddingModel.COHERE_ENGLISH_V3,
        embedding_dimensions=512,
        distance_metric="euclidean",
        chunking=ChunkingConfig.fixed_size(max_tokens=500, overlap_percentage=15),
        inclusion_prefixes=["docs/", "reports/"],
        data_deletion_policy="RETAIN",
        enable_auto_sync=False,
        sync_batch_window_seconds=120,
        retain_on_delete=False,
        description="Custom knowledge base",
    )

    assert props.embedding_model == EmbeddingModel.COHERE_ENGLISH_V3
    assert props.embedding_dimensions == 512
    assert props.distance_metric == "euclidean"
    assert props.chunking.strategy == ChunkingStrategy.FIXED_SIZE
    assert isinstance(props.chunking, FixedSizeChunkingConfig)
    assert props.chunking.max_tokens == 500
    assert props.chunking.overlap_percentage == 15
    assert props.inclusion_prefixes == ["docs/", "reports/"]
    assert props.data_deletion_policy == "RETAIN"
    assert props.enable_auto_sync is False
    assert props.sync_batch_window_seconds == 120
    assert props.retain_on_delete is False
    assert props.description == "Custom knowledge base"


def test_knowledge_base_props_mutable_default_isolation():
    """Test that inclusion_prefixes default is not shared across instances."""
    props_a = KnowledgeBaseProps()
    props_b = KnowledgeBaseProps()

    props_a.inclusion_prefixes.append("data/")

    assert props_b.inclusion_prefixes == []


def test_knowledge_base_props_chunking_default_isolation():
    """Test that chunking default is not shared across instances."""
    props_a = KnowledgeBaseProps()
    props_b = KnowledgeBaseProps()

    assert props_a.chunking is not props_b.chunking


# -- resolved_embedding_dimensions --


def test_resolved_embedding_dimensions_default_titan():
    """Test that resolved dimensions use Titan V2 default when not set."""
    props = KnowledgeBaseProps()
    assert props.resolved_embedding_dimensions() == 1024


def test_resolved_embedding_dimensions_explicit():
    """Test that explicit embedding_dimensions takes precedence."""
    props = KnowledgeBaseProps(embedding_dimensions=512)
    assert props.resolved_embedding_dimensions() == 512


def test_resolved_embedding_dimensions_cohere():
    """Test that Cohere model uses its own default dimensions."""
    props = KnowledgeBaseProps(embedding_model=EmbeddingModel.COHERE_ENGLISH_V3)
    assert props.resolved_embedding_dimensions() == 1024


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        (EmbeddingModel.TITAN_V2, 1024),
        (EmbeddingModel.COHERE_ENGLISH_V3, 1024),
        (EmbeddingModel.COHERE_MULTILINGUAL_V3, 1024),
    ],
)
def test_resolved_embedding_dimensions_per_model(model, expected):
    """Test that each model resolves to its expected default dimensions."""
    props = KnowledgeBaseProps(embedding_model=model)
    assert props.resolved_embedding_dimensions() == expected
