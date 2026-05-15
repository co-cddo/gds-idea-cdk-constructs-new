"""CDK stack tests for AgentCore construct."""

import pytest
from aws_cdk import App, Environment as CdkEnvironment
from aws_cdk.assertions import Match, Template

from gds_idea_cdk_constructs.agent_core.props import (
    AgentCoreProperties,
    BuiltInAgent,
    CustomAgent,
    MemoryConfig,
    ModelConfig,
)
from gds_idea_cdk_constructs.agent_core.stack import AgentCore

# -- Fixtures --


@pytest.fixture
def cdk_app():
    return App()


@pytest.fixture
def cdk_env():
    return CdkEnvironment(account="123456789012", region="eu-west-2")


@pytest.fixture
def builtin_default(cdk_app, cdk_env):
    """Zero-config: BuiltInAgent with memory enabled."""
    return AgentCore(
        cdk_app,
        "TestStack",
        props=AgentCoreProperties(runtime_name="test_agent"),
        env=cdk_env,
    )


@pytest.fixture
def builtin_custom_model(cdk_app, cdk_env):
    """BuiltInAgent with custom model settings and system prompt."""
    return AgentCore(
        cdk_app,
        "CustomModelStack",
        props=AgentCoreProperties(
            runtime_name="custom_model_agent",
            agent=BuiltInAgent(
                model=ModelConfig(
                    model_id="eu.anthropic.claude-haiku-4-5-20251001",
                    max_tokens=4000,
                    budget_tokens=2000,
                    thinking_enabled=False,
                ),
                system_prompt="You are a test agent.",
                log_level="DEBUG",
            ),
            memory=MemoryConfig(name="custom_memory"),
        ),
        env=cdk_env,
    )


@pytest.fixture
def builtin_no_memory(cdk_app, cdk_env):
    """BuiltInAgent with memory disabled."""
    return AgentCore(
        cdk_app,
        "NoMemoryStack",
        props=AgentCoreProperties(
            runtime_name="no_memory_agent",
            agent=BuiltInAgent(),
            memory=None,
        ),
        env=cdk_env,
    )


@pytest.fixture
def custom_agent_with_memory(cdk_app, cdk_env):
    """CustomAgent with memory enabled."""
    return AgentCore(
        cdk_app,
        "CustomAgentStack",
        props=AgentCoreProperties(
            runtime_name="custom_agent",
            agent=CustomAgent(
                agent_code_directory="tests/fixtures/fake_agent/",
                model_id="eu.anthropic.claude-sonnet-4-6",
                environment_variables={"MY_VAR": "hello"},
            ),
            memory=MemoryConfig(name="custom_store"),
        ),
        env=cdk_env,
    )


@pytest.fixture
def custom_agent_no_memory(cdk_app, cdk_env):
    """CustomAgent with memory disabled."""
    return AgentCore(
        cdk_app,
        "CustomNoMemStack",
        props=AgentCoreProperties(
            runtime_name="custom_no_mem",
            agent=CustomAgent(
                agent_code_directory="tests/fixtures/fake_agent/",
                environment_variables={"API_KEY": "secret"},
            ),
            memory=None,
        ),
        env=cdk_env,
    )


# =============================================================================
# Runtime resource tests
# =============================================================================


class TestRuntimeCreation:
    """Tests that the AgentCore Runtime is created correctly."""

    def test_creates_runtime_resource(self, builtin_default):
        template = Template.from_stack(builtin_default)
        template.has_resource_properties(
            "AWS::BedrockAgentCore::Runtime",
            {
                "AgentRuntimeName": "test_agent",
                "Description": (
                    "An AgentCore Runtime deployed by the Agent Constructs Template"
                ),

            },
        )

    def test_runtime_has_output(self, builtin_default):
        template = Template.from_stack(builtin_default)
        template.has_output("RuntimeArn", {"Value": Match.any_value()})


# =============================================================================
# Built-in agent environment variable tests
# =============================================================================


class TestBuiltInAgentEnvVars:
    """Tests that BuiltInAgent mode injects the correct env vars."""

    def test_default_env_vars(self, builtin_default):
        template = Template.from_stack(builtin_default)
        template.has_resource_properties(
            "AWS::BedrockAgentCore::Runtime",
            {
                "EnvironmentVariables": Match.object_like({
                    "MODEL_ID": "eu.anthropic.claude-sonnet-4-6",
                    "MAX_TOKENS": "8000",
                    "BUDGET_TOKENS": "4000",
                    "THINKING_ENABLED": "true",
                    "MAX_HISTORY": "20",
                    "REGION": "eu-west-2",
                    "LOG_LEVEL": "INFO",
                }),
            },
        )

    def test_custom_model_env_vars(self, builtin_custom_model):
        template = Template.from_stack(builtin_custom_model)
        template.has_resource_properties(
            "AWS::BedrockAgentCore::Runtime",
            {
                "EnvironmentVariables": Match.object_like({
                    "MODEL_ID": "eu.anthropic.claude-haiku-4-5-20251001",
                    "MAX_TOKENS": "4000",
                    "BUDGET_TOKENS": "2000",
                    "THINKING_ENABLED": "false",
                    "LOG_LEVEL": "DEBUG",
                    "SYSTEM_PROMPT": "You are a test agent.",
                }),
            },
        )

    def test_no_system_prompt_env_var_when_empty(self, builtin_default):
        """When system_prompt is empty, SYSTEM_PROMPT env var should not be set."""
        template = Template.from_stack(builtin_default)
        template_json = template.to_json()
        for resource in template_json["Resources"].values():
            if resource["Type"] == "AWS::BedrockAgentCore::Runtime":
                env_vars = resource["Properties"].get("EnvironmentVariables", {})
                assert "SYSTEM_PROMPT" not in env_vars


# =============================================================================
# Custom agent environment variable tests
# =============================================================================


class TestCustomAgentEnvVars:
    """Tests that CustomAgent mode injects the correct env vars."""

    def test_injects_model_id_and_region(self, custom_agent_with_memory):
        template = Template.from_stack(custom_agent_with_memory)
        template.has_resource_properties(
            "AWS::BedrockAgentCore::Runtime",
            {
                "EnvironmentVariables": Match.object_like({
                    "MODEL_ID": "eu.anthropic.claude-sonnet-4-6",
                    "REGION": "eu-west-2",
                    "MY_VAR": "hello",
                }),
            },
        )

    def test_injects_user_env_vars(self, custom_agent_no_memory):
        template = Template.from_stack(custom_agent_no_memory)
        template.has_resource_properties(
            "AWS::BedrockAgentCore::Runtime",
            {
                "EnvironmentVariables": Match.object_like({
                    "API_KEY": "secret",
                    "REGION": "eu-west-2",
                }),
            },
        )

    def test_does_not_inject_builtin_specific_vars(self, custom_agent_no_memory):
        """CustomAgent should NOT get MAX_TOKENS, BUDGET_TOKENS, etc."""
        template = Template.from_stack(custom_agent_no_memory)
        template_json = template.to_json()
        for resource in template_json["Resources"].values():
            if resource["Type"] == "AWS::BedrockAgentCore::Runtime":
                env_vars = resource["Properties"].get("EnvironmentVariables", {})
                assert "MAX_TOKENS" not in env_vars
                assert "BUDGET_TOKENS" not in env_vars
                assert "THINKING_ENABLED" not in env_vars
                assert "LOG_LEVEL" not in env_vars


# =============================================================================
# Memory tests
# =============================================================================


class TestMemory:
    """Tests that memory is created or skipped based on config."""

    def test_memory_created_when_configured(self, builtin_default):
        template = Template.from_stack(builtin_default)
        template.has_resource_properties(
            "AWS::BedrockAgentCore::Memory",
            {
                "Name": "chat_session_store",
                "Description": "Stores short-term conversation history",
            },
        )

    def test_custom_memory_name(self, builtin_custom_model):
        template = Template.from_stack(builtin_custom_model)
        template.has_resource_properties(
            "AWS::BedrockAgentCore::Memory",
            {"Name": "custom_memory"},
        )

    def test_memory_id_injected_as_env_var(self, builtin_default):
        template = Template.from_stack(builtin_default)
        template.has_resource_properties(
            "AWS::BedrockAgentCore::Runtime",
            {
                "EnvironmentVariables": Match.object_like({
                    "MEMORY_ID": Match.any_value(),
                }),
            },
        )

    def test_no_memory_when_none(self, builtin_no_memory):
        template = Template.from_stack(builtin_no_memory)
        template.resource_count_is("AWS::BedrockAgentCore::Memory", 0)

    def test_no_memory_id_env_var_when_none(self, builtin_no_memory):
        template = Template.from_stack(builtin_no_memory)
        template_json = template.to_json()
        for resource in template_json["Resources"].values():
            if resource["Type"] == "AWS::BedrockAgentCore::Runtime":
                env_vars = resource["Properties"].get("EnvironmentVariables", {})
                assert "MEMORY_ID" not in env_vars


# =============================================================================
# IAM permission tests
# =============================================================================


class TestModelPermissions:
    """Tests that model invoke permissions are granted correctly."""

    def test_cross_region_model_gets_inference_profile_permission(
            self, 
            builtin_default
        ):
        """eu.* model should get inference-profile ARN + foundation-model wildcard."""
        template = Template.from_stack(builtin_default)
        template.has_resource_properties(
            "AWS::IAM::Policy",
            {
                "PolicyDocument": {
                    "Statement": Match.array_with([
                        Match.object_like({
                            "Action": [
                                "bedrock:InvokeModel",
                                "bedrock:InvokeModelWithResponseStream",
                            ],
                            "Effect": "Allow",
                            "Resource": [
                                "arn:aws:bedrock:eu-west-2:123456789012:inference-profile/eu.anthropic.claude-sonnet-4-6",
                                "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6",
                            ],
                        })
                    ])
                }
            },
        )

    def test_custom_agent_gets_model_permissions(self, custom_agent_with_memory):
        """CustomAgent should also get bedrock:InvokeModel permissions."""
        template = Template.from_stack(custom_agent_with_memory)
        template.has_resource_properties(
            "AWS::IAM::Policy",
            {
                "PolicyDocument": {
                    "Statement": Match.array_with([
                        Match.object_like({
                            "Action": [
                                "bedrock:InvokeModel",
                                "bedrock:InvokeModelWithResponseStream",
                            ],
                            "Effect": "Allow",
                        })
                    ])
                }
            },
        )


class TestMemoryPermissions:
    """Tests that memory read/write permissions are granted when memory exists."""

    def test_memory_read_permissions_granted(self, builtin_default):
        """When memory is enabled, runtime should have memory read access."""
        template = Template.from_stack(builtin_default)
        template.has_resource_properties(
            "AWS::IAM::Policy",
            {
                "PolicyDocument": {
                    "Statement": Match.array_with([
                        Match.object_like({
                            "Action": Match.array_with([
                                "bedrock-agentcore:GetEvent",
                                "bedrock-agentcore:ListEvents",
                            ]),
                            "Effect": "Allow",
                        })
                    ])
                }
            },
        )

    def test_memory_write_permissions_granted(self, builtin_default):
        """When memory is enabled, runtime should have memory write access."""
        template = Template.from_stack(builtin_default)
        template.has_resource_properties(
            "AWS::IAM::Policy",
            {
                "PolicyDocument": {
                    "Statement": Match.array_with([
                        Match.object_like({
                            "Action": "bedrock-agentcore:CreateEvent",
                            "Effect": "Allow",
                        })
                    ])
                }
            },
        )

    def test_no_memory_resource_when_disabled(self, builtin_no_memory):
        """When memory=None, no memory resource should exist."""
        template = Template.from_stack(builtin_no_memory)
        template.resource_count_is("AWS::BedrockAgentCore::Memory", 0)


class TestObservabilityPermissions:
    """Tests that logging, x-ray, and metrics permissions are always granted."""

    def test_cloudwatch_logs_permission(self, builtin_default):
        template = Template.from_stack(builtin_default)
        template.has_resource_properties(
            "AWS::IAM::Policy",
            {
                "PolicyDocument": {
                    "Statement": Match.array_with([
                        Match.object_like({
                            "Action": [
                                "logs:CreateLogGroup",
                                "logs:CreateLogStream",
                                "logs:PutLogEvents",
                                "logs:DescribeLogStreams",
                            ],
                            "Effect": "Allow",
                        })
                    ])
                }
            },
        )

    def test_xray_permission(self, builtin_default):
        template = Template.from_stack(builtin_default)
        template.has_resource_properties(
            "AWS::IAM::Policy",
            {
                "PolicyDocument": {
                    "Statement": Match.array_with([
                        Match.object_like({
                            "Action": [
                                "xray:PutTraceSegments",
                                "xray:PutTelemetryRecords",
                                "xray:GetSamplingRules",
                                "xray:GetSamplingTargets",
                            ],
                            "Effect": "Allow",
                            "Resource": "*",
                        })
                    ])
                }
            },
        )

    def test_cloudwatch_metrics_permission(self, builtin_default):
        template = Template.from_stack(builtin_default)
        template.has_resource_properties(
            "AWS::IAM::Policy",
            {
                "PolicyDocument": {
                    "Statement": Match.array_with([
                        Match.object_like({
                            "Action": "cloudwatch:PutMetricData",
                            "Effect": "Allow",
                            "Condition": {
                                "StringEquals": (
                                    {"cloudwatch:namespace": "bedrock-agentcore"}
                                ),
                            },
                        })
                    ])
                }
            },
        )

    def test_agentcore_identity_permission(self, builtin_default):
        template = Template.from_stack(builtin_default)
        template.has_resource_properties(
            "AWS::IAM::Policy",
            {
                "PolicyDocument": {
                    "Statement": Match.array_with([
                        Match.object_like({
                            "Action": [
                                "bedrock-agentcore:GetWorkloadAccessToken",
                                "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                                "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
                            ],
                            "Effect": "Allow",
                        })
                    ])
                }
            },
        )

    def test_observability_permissions_present_for_custom_agent(
            self, 
            custom_agent_no_memory
        ): 
        """Custom agents should also get logging/xray/metrics permissions."""
        template = Template.from_stack(custom_agent_no_memory)
        template.has_resource_properties(
            "AWS::IAM::Policy",
            {
                "PolicyDocument": {
                    "Statement": Match.array_with([
                        Match.object_like({
                            "Action": [
                                "xray:PutTraceSegments",
                                "xray:PutTelemetryRecords",
                                "xray:GetSamplingRules",
                                "xray:GetSamplingTargets",
                            ],
                            "Effect": "Allow",
                        })
                    ])
                }
            },
        )
