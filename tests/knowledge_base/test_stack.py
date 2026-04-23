"""Unit tests for the KnowledgeBase stack."""

import pytest
from aws_cdk import App, Environment as CdkEnvironment
from aws_cdk.assertions import Match, Template

from gds_idea_cdk_constructs.config import AppConfig, DeploymentConfig
from gds_idea_cdk_constructs.knowledge_base.props import (
    ChunkingStrategy,
    EmbeddingModel,
    KnowledgeBaseProps,
)
from gds_idea_cdk_constructs.knowledge_base.stack import KnowledgeBase
from tests.conftest import TEST_CONFIG

# -- Fixtures --


@pytest.fixture
def cdk_app():
    """Fixture for CDK App."""
    return App()


@pytest.fixture
def test_cdk_env():
    """Fixture for TESTING CdkEnvironment."""
    return CdkEnvironment(account="testing", region="eu-west-2")


@pytest.fixture
def deployment_config(test_cdk_env):
    """Fixture for test DeploymentConfig."""
    return DeploymentConfig.from_dict(test_cdk_env, TEST_CONFIG)


@pytest.fixture
def app_config():
    """Fixture for AppConfig."""
    return AppConfig(app_name="testapp", framework="streamlit")


@pytest.fixture
def kb_default(cdk_app, deployment_config, app_config):
    """Fixture for KnowledgeBase with default props."""
    return KnowledgeBase(
        cdk_app,
        deployment_config=deployment_config,
        app_config=app_config,
    )


@pytest.fixture
def kb_no_sync(cdk_app, deployment_config, app_config):
    """Fixture for KnowledgeBase with auto-sync disabled."""
    return KnowledgeBase(
        cdk_app,
        deployment_config=deployment_config,
        app_config=app_config,
        kb_props=KnowledgeBaseProps(enable_auto_sync=False),
    )


@pytest.fixture
def kb_fixed_chunking(cdk_app, deployment_config, app_config):
    """Fixture for KnowledgeBase with fixed-size chunking."""
    return KnowledgeBase(
        cdk_app,
        deployment_config=deployment_config,
        app_config=app_config,
        kb_props=KnowledgeBaseProps(
            chunking_strategy=ChunkingStrategy.FIXED_SIZE,
            chunk_max_tokens=500,
            chunk_overlap_percentage=15,
        ),
    )


# -- Core resource tests --


def test_kb_stack_creates_s3_bucket(kb_default):
    """Test that the stack creates an S3 bucket for source documents."""
    template = Template.from_stack(kb_default)

    template.resource_count_is("AWS::S3::Bucket", 1)
    template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "BucketName": "testapp-kb-data-testing",
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
            "VersioningConfiguration": {"Status": "Enabled"},
        },
    )


def test_kb_stack_creates_vector_bucket(kb_default):
    """Test that the stack creates an S3 Vector Bucket."""
    template = Template.from_stack(kb_default)

    template.resource_count_is("AWS::S3Vectors::VectorBucket", 1)
    template.has_resource_properties(
        "AWS::S3Vectors::VectorBucket",
        {"VectorBucketName": "testapp-vectors-testing"},
    )


def test_kb_stack_creates_vector_index(kb_default):
    """Test that the stack creates an S3 Vectors Index."""
    template = Template.from_stack(kb_default)

    template.resource_count_is("AWS::S3Vectors::Index", 1)
    template.has_resource_properties(
        "AWS::S3Vectors::Index",
        {
            "IndexName": "testapp-index-testing",
            "DataType": "float32",
            "Dimension": 1024,
            "DistanceMetric": "cosine",
        },
    )


def test_kb_stack_creates_knowledge_base(kb_default):
    """Test that the stack creates a Bedrock Knowledge Base."""
    template = Template.from_stack(kb_default)

    template.resource_count_is("AWS::Bedrock::KnowledgeBase", 1)
    template.has_resource_properties(
        "AWS::Bedrock::KnowledgeBase",
        {
            "Name": "testapp-kb-testing",
            "KnowledgeBaseConfiguration": {
                "Type": "VECTOR",
                "VectorKnowledgeBaseConfiguration": {
                    "EmbeddingModelArn": Match.any_value(),
                },
            },
            "StorageConfiguration": {
                "Type": "S3_VECTORS",
            },
        },
    )

    # Verify the embedding model ARN references Titan V2 via Fn::Join
    template_json = template.to_json()
    for resource in template_json["Resources"].values():
        if resource["Type"] == "AWS::Bedrock::KnowledgeBase":
            arn = resource["Properties"]["KnowledgeBaseConfiguration"][
                "VectorKnowledgeBaseConfiguration"
            ]["EmbeddingModelArn"]
            # Fn::Join produces a list — check the model ID is in there
            join_parts = arn.get("Fn::Join", [None, []])[1]
            joined = "".join(str(p) for p in join_parts)
            assert "titan-embed-text-v2" in joined


def test_kb_stack_creates_data_source(kb_default):
    """Test that the stack creates a Bedrock Data Source."""
    template = Template.from_stack(kb_default)

    template.resource_count_is("AWS::Bedrock::DataSource", 1)
    template.has_resource_properties(
        "AWS::Bedrock::DataSource",
        {
            "Name": "testapp-datasource-testing",
            "DataSourceConfiguration": {
                "Type": "S3",
            },
            "DataDeletionPolicy": "DELETE",
        },
    )


def test_kb_stack_creates_ssm_parameter(kb_default):
    """Test that the stack creates an SSM parameter for the KB ID."""
    template = Template.from_stack(kb_default)

    template.resource_count_is("AWS::SSM::Parameter", 1)
    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {
            "Name": "/testapp/kb-id",
            "Type": "String",
        },
    )


def test_kb_stack_creates_iam_role_for_bedrock(kb_default):
    """Test that the stack creates an IAM role for the Bedrock service."""
    template = Template.from_stack(kb_default)

    template.has_resource_properties(
        "AWS::IAM::Role",
        {
            "RoleName": "testapp-kb-role-testing",
            "AssumeRolePolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": "sts:AssumeRole",
                                "Effect": "Allow",
                                "Principal": {
                                    "Service": "bedrock.amazonaws.com",
                                },
                            }
                        )
                    ]
                )
            },
        },
    )


def test_kb_stack_role_has_invoke_model_permission(kb_default):
    """Test that the KB role can invoke the embedding model."""
    template = Template.from_stack(kb_default)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": "bedrock:InvokeModel",
                                "Effect": "Allow",
                            }
                        )
                    ]
                )
            }
        },
    )


def test_kb_stack_role_has_s3_vectors_permissions(kb_default):
    """Test that the KB role has S3 Vectors access permissions."""
    template = Template.from_stack(kb_default)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": Match.array_with(
                                    [
                                        "s3vectors:PutVectors",
                                        "s3vectors:GetVectors",
                                        "s3vectors:QueryVectors",
                                    ]
                                ),
                                "Effect": "Allow",
                            }
                        )
                    ]
                )
            }
        },
    )


# -- Chunking configuration tests --


def test_kb_stack_default_chunking_none(kb_default):
    """Test that default chunking strategy is NONE."""
    template = Template.from_stack(kb_default)

    template.has_resource_properties(
        "AWS::Bedrock::DataSource",
        {
            "VectorIngestionConfiguration": {
                "ChunkingConfiguration": {
                    "ChunkingStrategy": "NONE",
                },
            },
        },
    )


def test_kb_stack_fixed_size_chunking(kb_fixed_chunking):
    """Test that fixed-size chunking is configured correctly."""
    template = Template.from_stack(kb_fixed_chunking)

    template.has_resource_properties(
        "AWS::Bedrock::DataSource",
        {
            "VectorIngestionConfiguration": {
                "ChunkingConfiguration": {
                    "ChunkingStrategy": "FIXED_SIZE",
                    "FixedSizeChunkingConfiguration": {
                        "MaxTokens": 500,
                        "OverlapPercentage": 15,
                    },
                },
            },
        },
    )


def test_kb_stack_hierarchical_chunking(cdk_app, deployment_config, app_config):
    """Test that hierarchical chunking is configured correctly."""
    kb = KnowledgeBase(
        cdk_app,
        deployment_config=deployment_config,
        app_config=app_config,
        kb_props=KnowledgeBaseProps(
            chunking_strategy=ChunkingStrategy.HIERARCHICAL,
            chunk_max_tokens=300,
            chunk_overlap_percentage=20,
        ),
    )
    template = Template.from_stack(kb)

    template.has_resource_properties(
        "AWS::Bedrock::DataSource",
        {
            "VectorIngestionConfiguration": {
                "ChunkingConfiguration": {
                    "ChunkingStrategy": "HIERARCHICAL",
                    "HierarchicalChunkingConfiguration": {
                        "LevelConfigurations": [
                            {"MaxTokens": 1500},  # 300 * 5
                            {"MaxTokens": 300},
                        ],
                        "OverlapTokens": 60,  # 300 * 20 / 100
                    },
                },
            },
        },
    )


def test_kb_stack_semantic_chunking(cdk_app, deployment_config, app_config):
    """Test that semantic chunking is configured correctly."""
    kb = KnowledgeBase(
        cdk_app,
        deployment_config=deployment_config,
        app_config=app_config,
        kb_props=KnowledgeBaseProps(
            chunking_strategy=ChunkingStrategy.SEMANTIC,
            chunk_max_tokens=400,
        ),
    )
    template = Template.from_stack(kb)

    template.has_resource_properties(
        "AWS::Bedrock::DataSource",
        {
            "VectorIngestionConfiguration": {
                "ChunkingConfiguration": {
                    "ChunkingStrategy": "SEMANTIC",
                    "SemanticChunkingConfiguration": {
                        "MaxTokens": 400,
                        "BufferSize": 0,
                        "BreakpointPercentileThreshold": 95,
                    },
                },
            },
        },
    )


# -- Auto-sync tests --


def test_kb_stack_auto_sync_creates_sqs_queue(kb_default):
    """Test that auto-sync creates an SQS queue."""
    template = Template.from_stack(kb_default)

    # Main queue + DLQ
    template.resource_count_is("AWS::SQS::Queue", 2)
    template.has_resource_properties(
        "AWS::SQS::Queue",
        {
            "QueueName": "testapp-kb-sync-testing",
        },
    )


def test_kb_stack_auto_sync_creates_lambda(kb_default):
    """Test that auto-sync creates a Lambda function."""
    template = Template.from_stack(kb_default)

    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "testapp-kb-sync-testing",
            "Handler": "kb_sync.handler",
            "Runtime": "python3.11",
        },
    )


def test_kb_stack_auto_sync_lambda_has_start_ingestion_permission(kb_default):
    """Test that the sync Lambda can start ingestion jobs."""
    template = Template.from_stack(kb_default)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": "bedrock:StartIngestionJob",
                                "Effect": "Allow",
                            }
                        )
                    ]
                )
            }
        },
    )


def test_kb_stack_auto_sync_creates_sqs_event_source(kb_default):
    """Test that the Lambda has an SQS event source mapping."""
    template = Template.from_stack(kb_default)

    template.resource_count_is("AWS::Lambda::EventSourceMapping", 1)
    template.has_resource_properties(
        "AWS::Lambda::EventSourceMapping",
        {
            "BatchSize": 10,
            "MaximumBatchingWindowInSeconds": 300,  # 5 minutes (default)
        },
    )


def test_kb_stack_no_sync_has_no_lambda(kb_no_sync):
    """Test that disabling auto-sync removes Lambda and SQS resources."""
    template = Template.from_stack(kb_no_sync)

    template.resource_count_is("AWS::Lambda::Function", 0)
    template.resource_count_is("AWS::SQS::Queue", 0)
    template.resource_count_is("AWS::Lambda::EventSourceMapping", 0)


def test_kb_stack_custom_sync_batch_window(cdk_app, deployment_config, app_config):
    """Test that custom sync batch window is applied."""
    kb = KnowledgeBase(
        cdk_app,
        deployment_config=deployment_config,
        app_config=app_config,
        kb_props=KnowledgeBaseProps(
            enable_auto_sync=True,
            sync_batch_window_seconds=120,
        ),
    )
    template = Template.from_stack(kb)

    template.has_resource_properties(
        "AWS::Lambda::EventSourceMapping",
        {
            "MaximumBatchingWindowInSeconds": 120,  # 2 minutes
        },
    )


# -- Inclusion prefixes tests --


def test_kb_stack_with_inclusion_prefixes(cdk_app, deployment_config, app_config):
    """Test that inclusion prefixes are applied to the data source."""
    kb = KnowledgeBase(
        cdk_app,
        deployment_config=deployment_config,
        app_config=app_config,
        kb_props=KnowledgeBaseProps(
            inclusion_prefixes=["documents/", "reports/"],
        ),
    )
    template = Template.from_stack(kb)

    template.has_resource_properties(
        "AWS::Bedrock::DataSource",
        {
            "DataSourceConfiguration": {
                "Type": "S3",
                "S3Configuration": {
                    "InclusionPrefixes": ["documents/", "reports/"],
                },
            },
        },
    )


def test_kb_stack_without_inclusion_prefixes(kb_default):
    """Test that empty inclusion prefixes are omitted."""
    template = Template.from_stack(kb_default)
    template_json = template.to_json()

    # Find the DataSource and verify no InclusionPrefixes key
    for resource in template_json["Resources"].values():
        if resource["Type"] == "AWS::Bedrock::DataSource":
            s3_config = (
                resource["Properties"]
                .get("DataSourceConfiguration", {})
                .get("S3Configuration", {})
            )
            assert "InclusionPrefixes" not in s3_config


# -- Embedding model tests --


def test_kb_stack_custom_embedding_model(cdk_app, deployment_config, app_config):
    """Test that a custom embedding model is applied."""
    kb = KnowledgeBase(
        cdk_app,
        deployment_config=deployment_config,
        app_config=app_config,
        kb_props=KnowledgeBaseProps(
            embedding_model=EmbeddingModel.COHERE_ENGLISH_V3,
        ),
    )
    template = Template.from_stack(kb)

    # The ARN is a Fn::Join token, so check the raw template JSON
    template_json = template.to_json()
    for resource in template_json["Resources"].values():
        if resource["Type"] == "AWS::Bedrock::KnowledgeBase":
            arn = resource["Properties"]["KnowledgeBaseConfiguration"][
                "VectorKnowledgeBaseConfiguration"
            ]["EmbeddingModelArn"]
            join_parts = arn.get("Fn::Join", [None, []])[1]
            joined = "".join(str(p) for p in join_parts)
            assert "cohere.embed-english-v3" in joined
            break
    else:
        pytest.fail("No AWS::Bedrock::KnowledgeBase resource found")


# -- app_config as string tests --


def test_kb_stack_accepts_string_app_name(cdk_app, deployment_config):
    """Test that the stack accepts a plain string as app_config."""
    kb = KnowledgeBase(
        cdk_app,
        deployment_config=deployment_config,
        app_config="my-kb-app",
        kb_props=KnowledgeBaseProps(enable_auto_sync=False),
    )

    assert kb.app_name == "my-kb-app"

    template = Template.from_stack(kb)
    template.has_resource_properties(
        "AWS::S3::Bucket",
        {"BucketName": "my-kb-app-kb-data-testing"},
    )


def test_kb_stack_accepts_app_config_object(cdk_app, deployment_config, app_config):
    """Test that the stack accepts an AppConfig object."""
    kb = KnowledgeBase(
        cdk_app,
        deployment_config=deployment_config,
        app_config=app_config,
        kb_props=KnowledgeBaseProps(enable_auto_sync=False),
    )

    assert kb.app_name == "testapp"


# -- Cross-stack attribute tests --


def test_kb_stack_exposes_kb_id(kb_default):
    """Test that the stack exposes the KB ID attribute."""
    assert kb_default.kb_id is not None


def test_kb_stack_exposes_kb_arn(kb_default):
    """Test that the stack exposes the KB ARN attribute."""
    assert kb_default.kb_arn is not None


def test_kb_stack_exposes_data_bucket(kb_default):
    """Test that the stack exposes the data bucket."""
    assert kb_default.data_bucket is not None
    assert kb_default.data_bucket.bucket_name is not None


def test_kb_stack_exposes_ssm_parameter(kb_default):
    """Test that the stack exposes the SSM parameter."""
    assert kb_default.ssm_parameter is not None
    assert kb_default.ssm_parameter.parameter_name is not None


def test_kb_stack_exposes_data_source_id(kb_default):
    """Test that the stack exposes the data source ID."""
    assert kb_default.data_source_id is not None


# -- Error handling --


def test_kb_stack_invalid_storage_type_raises_error(
    cdk_app, deployment_config, app_config
):
    """Test that an invalid storage type raises ValueError."""
    with pytest.raises(ValueError, match="Unsupported storage type"):
        KnowledgeBase(
            cdk_app,
            deployment_config=deployment_config,
            app_config=app_config,
            kb_props=KnowledgeBaseProps(
                storage_type="invalid_type",  # type: ignore[arg-type]
            ),
        )


# -- CloudFormation outputs --


def test_kb_stack_has_expected_outputs(kb_default):
    """Test that the stack creates the expected CloudFormation outputs."""
    template = Template.from_stack(kb_default)

    template.has_output(
        "KnowledgeBaseId",
        {"Description": "Bedrock Knowledge Base ID"},
    )
    template.has_output(
        "KnowledgeBaseArn",
        {"Description": "Bedrock Knowledge Base ARN"},
    )
    template.has_output(
        "DataBucketName",
        {"Description": "S3 bucket for source documents"},
    )
    template.has_output(
        "DataSourceId",
        {"Description": "Bedrock Data Source ID"},
    )
    template.has_output(
        "SsmParameterName",
        {"Description": "SSM parameter storing the KB ID"},
    )
