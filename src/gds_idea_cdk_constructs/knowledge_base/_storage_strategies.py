"""Storage strategy pattern for knowledge base vector backends.

This module defines the ``IStorageStrategy`` ABC and concrete implementations
for each supported :class:`~.props.StorageType`.  The stack selects a strategy
via :data:`STORAGE_STRATEGY_MAP` — consumers never interact with strategy
classes directly.

To add a new storage backend:
    1. Implement :class:`IStorageStrategy`.
    2. Add a :class:`~.props.StorageType` enum member.
    3. Register the class in :data:`STORAGE_STRATEGY_MAP`.
"""

from abc import ABC, abstractmethod

from aws_cdk import (
    CfnResource,
    RemovalPolicy,
    aws_bedrock as bedrock,
    aws_iam as iam,
    aws_s3vectors as s3vectors,
)
from constructs import Construct

from .props import KnowledgeBaseProps, StorageType


class IStorageStrategy(ABC):
    """Interface for knowledge base vector storage backends.

    Each implementation creates the backend-specific infrastructure (e.g.,
    S3 Vector Bucket + Index) and exposes the information the Bedrock
    ``CfnKnowledgeBase`` needs to reference it.

    Args:
        scope: The CDK construct scope.
        kb_props: Knowledge base configuration properties.
    """

    def __init__(self, scope: Construct, kb_props: KnowledgeBaseProps) -> None:
        self.scope = scope
        self.kb_props = kb_props

    @abstractmethod
    def create_storage_resources(
        self, app_prefix: str, env_name: str, retain: bool
    ) -> None:
        """Provision backend-specific storage resources.

        Args:
            app_prefix: Naming prefix derived from the application name.
            env_name: Deployment environment name (e.g., ``"development"``).
            retain: Whether to apply RETAIN removal policy.
        """

    @abstractmethod
    def get_storage_configuration(
        self,
    ) -> bedrock.CfnKnowledgeBase.StorageConfigurationProperty:
        """Return the Bedrock storage configuration property.

        Returns:
            A ``StorageConfigurationProperty`` that tells Bedrock where
            to store and retrieve vectors.
        """

    @abstractmethod
    def get_iam_policy_statements(self) -> list[iam.PolicyStatement]:
        """Return IAM policy statements the KB service role needs.

        Returns:
            A list of ``PolicyStatement`` objects granting the KB role
            access to the storage backend.
        """

    @abstractmethod
    def get_resource_dependencies(self) -> list[CfnResource]:
        """Return CloudFormation resources the KB must depend on.

        Returns:
            A list of ``CfnResource`` objects that must be created before
            the Knowledge Base.
        """


class S3VectorsStorageStrategy(IStorageStrategy):
    """S3 Vectors storage backend — serverless vector storage built on S3.

    Creates:
        - ``CfnVectorBucket`` for vector storage
        - ``CfnIndex`` for the vector index (float32, configurable dimensions
          and distance metric)
    """

    def __init__(self, scope: Construct, kb_props: KnowledgeBaseProps) -> None:
        super().__init__(scope, kb_props)
        self._vector_bucket: s3vectors.CfnVectorBucket | None = None
        self._vector_index: s3vectors.CfnIndex | None = None

    def create_storage_resources(
        self, app_prefix: str, env_name: str, retain: bool
    ) -> None:
        """Create S3 Vector Bucket and Index.

        Args:
            app_prefix: Naming prefix derived from the application name.
            env_name: Deployment environment name.
            retain: Whether to apply RETAIN removal policy.
        """
        removal_policy = RemovalPolicy.RETAIN if retain else RemovalPolicy.DESTROY

        self._vector_bucket = s3vectors.CfnVectorBucket(
            self.scope,
            "VectorBucket",
            vector_bucket_name=f"{app_prefix}-vectors-{env_name}",
        )
        self._vector_bucket.apply_removal_policy(removal_policy)

        self._vector_index = s3vectors.CfnIndex(
            self.scope,
            "VectorIndex",
            index_name=f"{app_prefix}-index-{env_name}",
            vector_bucket_name=self._vector_bucket.vector_bucket_name,
            data_type="float32",
            dimension=self.kb_props.resolved_embedding_dimensions(),
            distance_metric=self.kb_props.distance_metric,
            metadata_configuration=s3vectors.CfnIndex.MetadataConfigurationProperty(
                non_filterable_metadata_keys=["content"],
            ),
        )
        self._vector_index.add_dependency(self._vector_bucket)

    def get_storage_configuration(
        self,
    ) -> bedrock.CfnKnowledgeBase.StorageConfigurationProperty:
        """Return S3 Vectors storage configuration for Bedrock.

        Returns:
            A ``StorageConfigurationProperty`` pointing to the S3 Vector
            Bucket and Index.

        Raises:
            RuntimeError: If called before ``create_storage_resources``.
        """
        if self._vector_bucket is None or self._vector_index is None:
            raise RuntimeError(
                "create_storage_resources() must be called before "
                "get_storage_configuration()"
            )

        return bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
            type="S3_VECTORS",
            s3_vectors_configuration=bedrock.CfnKnowledgeBase.S3VectorsConfigurationProperty(
                vector_bucket_arn=self._vector_bucket.attr_vector_bucket_arn,
                index_name=self._vector_index.index_name,
            ),
        )

    def get_iam_policy_statements(self) -> list[iam.PolicyStatement]:
        """Return S3 Vectors IAM permissions for the KB service role.

        Returns:
            A list containing a single ``PolicyStatement`` granting
            read/write access to the vector bucket and index.

        Raises:
            RuntimeError: If called before ``create_storage_resources``.
        """
        if self._vector_bucket is None or self._vector_index is None:
            raise RuntimeError(
                "create_storage_resources() must be called before "
                "get_iam_policy_statements()"
            )

        return [
            iam.PolicyStatement(
                sid="S3VectorsAccess",
                actions=[
                    "s3vectors:CreateIndex",
                    "s3vectors:GetIndex",
                    "s3vectors:PutVectors",
                    "s3vectors:GetVectors",
                    "s3vectors:DeleteVectors",
                    "s3vectors:QueryVectors",
                    "s3vectors:ListVectors",
                    "s3vectors:GetVectorBucket",
                    "s3vectors:ListVectorBuckets",
                ],
                resources=[
                    self._vector_bucket.attr_vector_bucket_arn,
                    self._vector_index.attr_index_arn,
                ],
            )
        ]

    def get_resource_dependencies(self) -> list[CfnResource]:
        """Return the CfnIndex as a dependency for the Knowledge Base.

        Returns:
            A list containing the ``CfnIndex`` (which transitively depends
            on the ``CfnVectorBucket``).

        Raises:
            RuntimeError: If called before ``create_storage_resources``.
        """
        if self._vector_index is None:
            raise RuntimeError(
                "create_storage_resources() must be called before "
                "get_resource_dependencies()"
            )

        return [self._vector_index]


STORAGE_STRATEGY_MAP: dict[StorageType, type[IStorageStrategy]] = {
    StorageType.S3_VECTORS: S3VectorsStorageStrategy,
}
