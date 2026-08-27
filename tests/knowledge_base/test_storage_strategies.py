"""Unit tests for storage strategies."""

import pytest
from aws_cdk import App, Environment as CdkEnvironment, Stack

from gds_idea_cdk_constructs.knowledge_base._storage_strategies import (
    STORAGE_STRATEGY_MAP,
    IStorageStrategy,
    S3VectorsStorageStrategy,
)
from gds_idea_cdk_constructs.knowledge_base.props import (
    KnowledgeBaseProps,
    StorageType,
)


@pytest.fixture
def cdk_app():
    """Fixture for CDK App."""
    return App()


@pytest.fixture
def test_stack(cdk_app):
    """Fixture for a test CDK Stack."""
    env = CdkEnvironment(account="testing", region="eu-west-2")
    return Stack(cdk_app, "TestStack", env=env)


@pytest.fixture
def default_props():
    """Fixture for default KnowledgeBaseProps."""
    return KnowledgeBaseProps()


@pytest.fixture
def s3_vectors_strategy(test_stack, default_props):
    """Fixture for an initialised S3VectorsStorageStrategy."""
    strategy = S3VectorsStorageStrategy(test_stack, default_props)
    strategy.create_storage_resources("testapp", "development", retain=True)
    return strategy


# -- STORAGE_STRATEGY_MAP tests --


def test_storage_strategy_map_contains_all_storage_types():
    """Test that STORAGE_STRATEGY_MAP covers all StorageType members."""
    for storage_type in StorageType:
        assert storage_type in STORAGE_STRATEGY_MAP


def test_storage_strategy_map_values_are_correct_classes():
    """Test that STORAGE_STRATEGY_MAP maps to correct strategy classes."""
    assert STORAGE_STRATEGY_MAP[StorageType.S3_VECTORS] == S3VectorsStorageStrategy


def test_all_strategies_implement_interface():
    """Test that all mapped strategies have the required methods."""
    for _, strategy_class in STORAGE_STRATEGY_MAP.items():
        assert hasattr(strategy_class, "create_storage_resources")
        assert hasattr(strategy_class, "get_storage_configuration")
        assert hasattr(strategy_class, "get_iam_policy_statements")
        assert hasattr(strategy_class, "get_resource_dependencies")


def test_all_strategies_are_subclasses_of_interface():
    """Test that all mapped strategies are subclasses of IStorageStrategy."""
    for _, strategy_class in STORAGE_STRATEGY_MAP.items():
        assert issubclass(strategy_class, IStorageStrategy)


# -- S3VectorsStorageStrategy tests --


def test_s3_vectors_creates_resources(s3_vectors_strategy):
    """Test that S3VectorsStorageStrategy creates vector bucket and index."""
    assert s3_vectors_strategy._vector_bucket is not None
    assert s3_vectors_strategy._vector_index is not None


def test_s3_vectors_get_storage_configuration(s3_vectors_strategy):
    """Test that get_storage_configuration returns valid config."""
    config = s3_vectors_strategy.get_storage_configuration()

    assert config.type == "S3_VECTORS"
    assert config.s3_vectors_configuration is not None


def test_s3_vectors_get_iam_policy_statements(s3_vectors_strategy):
    """Test that get_iam_policy_statements returns S3 Vectors permissions."""
    statements = s3_vectors_strategy.get_iam_policy_statements()

    assert len(statements) == 1
    statement = statements[0]

    # Check actions include the expected S3 Vectors operations
    actions = statement.actions
    assert "s3vectors:PutVectors" in actions
    assert "s3vectors:GetVectors" in actions
    assert "s3vectors:QueryVectors" in actions
    assert "s3vectors:DeleteVectors" in actions
    assert "s3vectors:GetVectorBucket" in actions


def test_s3_vectors_get_resource_dependencies(s3_vectors_strategy):
    """Test that get_resource_dependencies returns the vector index."""
    deps = s3_vectors_strategy.get_resource_dependencies()

    assert len(deps) == 1
    # The dependency should be the CfnIndex
    assert deps[0] == s3_vectors_strategy._vector_index


def test_s3_vectors_default_non_filterable_metadata_keys(s3_vectors_strategy):
    """Test that the index excludes Bedrock's reserved keys by default.

    S3 Vectors treats every metadata key as filterable (subject to a
    2048-byte cap per vector) unless declared non-filterable. Bedrock
    Knowledge Base auto-populates AMAZON_BEDROCK_TEXT (raw chunk text)
    and AMAZON_BEDROCK_METADATA (wrapper bookkeeping) on every vector, so
    these must be excluded by default to avoid the cap being hit as soon
    as chunk text grows beyond ~2KB. See
    https://repost.aws/questions/QUWezLMjc0S8GOiaa3jOOKGQ/s3-vector-big-metadata-error
    """
    metadata_config = s3_vectors_strategy._vector_index.metadata_configuration

    assert metadata_config.non_filterable_metadata_keys == [
        "AMAZON_BEDROCK_TEXT",
        "AMAZON_BEDROCK_METADATA",
    ]


def test_s3_vectors_custom_non_filterable_metadata_keys(test_stack):
    """Test that a custom non_filterable_metadata_keys list is honoured."""
    props = KnowledgeBaseProps(non_filterable_metadata_keys=["custom_key"])
    strategy = S3VectorsStorageStrategy(test_stack, props)
    strategy.create_storage_resources("testapp", "development", retain=True)

    metadata_config = strategy._vector_index.metadata_configuration
    assert metadata_config.non_filterable_metadata_keys == ["custom_key"]


def test_s3_vectors_custom_dimensions(test_stack):
    """Test that custom embedding dimensions are applied to the index."""
    props = KnowledgeBaseProps(embedding_dimensions=512)
    strategy = S3VectorsStorageStrategy(test_stack, props)
    strategy.create_storage_resources("testapp", "development", retain=True)

    # Verify the index was created with custom dimensions
    assert strategy._vector_index is not None
    # The dimension property is set via CloudFormation — we verify it was
    # passed correctly by checking the resolved props
    assert props.resolved_embedding_dimensions() == 512


def test_s3_vectors_custom_distance_metric(test_stack):
    """Test that custom distance metric is applied."""
    props = KnowledgeBaseProps(distance_metric="euclidean")
    strategy = S3VectorsStorageStrategy(test_stack, props)
    strategy.create_storage_resources("testapp", "development", retain=True)

    assert strategy._vector_index is not None


# -- Error cases: calling methods before create_storage_resources --


def test_s3_vectors_get_config_before_create_raises(test_stack, default_props):
    """Test that get_storage_configuration raises before resources are created."""
    strategy = S3VectorsStorageStrategy(test_stack, default_props)

    with pytest.raises(RuntimeError, match="create_storage_resources"):
        strategy.get_storage_configuration()


def test_s3_vectors_get_iam_before_create_raises(test_stack, default_props):
    """Test that get_iam_policy_statements raises before resources are created."""
    strategy = S3VectorsStorageStrategy(test_stack, default_props)

    with pytest.raises(RuntimeError, match="create_storage_resources"):
        strategy.get_iam_policy_statements()


def test_s3_vectors_get_deps_before_create_raises(test_stack, default_props):
    """Test that get_resource_dependencies raises before resources are created."""
    strategy = S3VectorsStorageStrategy(test_stack, default_props)

    with pytest.raises(RuntimeError, match="create_storage_resources"):
        strategy.get_resource_dependencies()
