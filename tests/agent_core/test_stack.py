"""CDK stack tests for AgentCore construct."""

import pytest
from aws_cdk import App, Environment as CdkEnvironment
from aws_cdk.assertions import Match, Template

from gds_idea_cdk_constructs.agent_core.props import (
    AgentCoreProperties,
    BuiltInAgent,
    CustomAgent,
    GatewayConfig,
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


@pytest.fixture
def gateway_unfiltered(cdk_app, cdk_env):
    """Gateway attached with no target filter."""
    return AgentCore(
        cdk_app,
        "GatewayStack",
        props=AgentCoreProperties(runtime_name="gw_agent", gateway=GatewayConfig()),
        env=cdk_env,
    )


@pytest.fixture
def gateway_filtered(cdk_app, cdk_env):
    """Two gateways attached, filtered to the wfc target."""
    return AgentCore(
        cdk_app,
        "GatewayFilteredStack",
        props=AgentCoreProperties(
            runtime_name="gw_filtered_agent",
            gateway=GatewayConfig(gateways=["idea-data", "other"], targets=["wfc"]),
        ),
        env=cdk_env,
    )


# =============================================================================
# Runtime resource tests
# =============================================================================


def test_creates_runtime_resource(builtin_default):
    """Tests that the AgentCore Runtime is created correctly."""
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


def test_runtime_has_output(builtin_default):
    template = Template.from_stack(builtin_default)
    template.has_output("RuntimeArn", {"Value": Match.any_value()})


# =============================================================================
# Built-in agent environment variable tests
# =============================================================================


def test_builtin_default_env_vars(builtin_default):
    """Tests that BuiltInAgent mode injects the correct default env vars."""
    template = Template.from_stack(builtin_default)
    template.has_resource_properties(
        "AWS::BedrockAgentCore::Runtime",
        {
            "EnvironmentVariables": Match.object_like(
                {
                    "MODEL_ID": "eu.anthropic.claude-sonnet-4-6",
                    "MAX_TOKENS": "8000",
                    "BUDGET_TOKENS": "4000",
                    "THINKING_ENABLED": "true",
                    "MAX_HISTORY": "20",
                    "REGION": "eu-west-2",
                    "LOG_LEVEL": "INFO",
                }
            ),
        },
    )


def test_builtin_custom_model_env_vars(builtin_custom_model):
    """Tests that custom model settings are injected as env vars."""
    template = Template.from_stack(builtin_custom_model)
    template.has_resource_properties(
        "AWS::BedrockAgentCore::Runtime",
        {
            "EnvironmentVariables": Match.object_like(
                {
                    "MODEL_ID": "eu.anthropic.claude-haiku-4-5-20251001",
                    "MAX_TOKENS": "4000",
                    "BUDGET_TOKENS": "2000",
                    "THINKING_ENABLED": "false",
                    "LOG_LEVEL": "DEBUG",
                    "SYSTEM_PROMPT": "You are a test agent.",
                }
            ),
        },
    )


def test_no_system_prompt_env_var_when_empty(builtin_default):
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


def test_custom_agent_injects_model_id_and_region(custom_agent_with_memory):
    """Tests that CustomAgent mode injects model_id, region, and user env vars."""
    template = Template.from_stack(custom_agent_with_memory)
    template.has_resource_properties(
        "AWS::BedrockAgentCore::Runtime",
        {
            "EnvironmentVariables": Match.object_like(
                {
                    "MODEL_ID": "eu.anthropic.claude-sonnet-4-6",
                    "REGION": "eu-west-2",
                    "MY_VAR": "hello",
                }
            ),
        },
    )


def test_custom_agent_injects_user_env_vars(custom_agent_no_memory):
    template = Template.from_stack(custom_agent_no_memory)
    template.has_resource_properties(
        "AWS::BedrockAgentCore::Runtime",
        {
            "EnvironmentVariables": Match.object_like(
                {
                    "API_KEY": "secret",
                    "REGION": "eu-west-2",
                }
            ),
        },
    )


def test_custom_agent_does_not_inject_builtin_specific_vars(custom_agent_no_memory):
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


def test_memory_created_when_configured(builtin_default):
    """Tests that memory is created when config is provided."""
    template = Template.from_stack(builtin_default)
    template.has_resource_properties(
        "AWS::BedrockAgentCore::Memory",
        {
            "Name": "chat_session_store",
            "Description": "Stores short-term conversation history",
        },
    )


def test_custom_memory_name(builtin_custom_model):
    template = Template.from_stack(builtin_custom_model)
    template.has_resource_properties(
        "AWS::BedrockAgentCore::Memory",
        {"Name": "custom_memory"},
    )


def test_memory_id_injected_as_env_var(builtin_default):
    template = Template.from_stack(builtin_default)
    template.has_resource_properties(
        "AWS::BedrockAgentCore::Runtime",
        {
            "EnvironmentVariables": Match.object_like(
                {
                    "MEMORY_ID": Match.any_value(),
                }
            ),
        },
    )


def test_no_memory_when_none(builtin_no_memory):
    template = Template.from_stack(builtin_no_memory)
    template.resource_count_is("AWS::BedrockAgentCore::Memory", 0)


def test_no_memory_id_env_var_when_none(builtin_no_memory):
    template = Template.from_stack(builtin_no_memory)
    template_json = template.to_json()
    for resource in template_json["Resources"].values():
        if resource["Type"] == "AWS::BedrockAgentCore::Runtime":
            env_vars = resource["Properties"].get("EnvironmentVariables", {})
            assert "MEMORY_ID" not in env_vars


# =============================================================================
# IAM permission tests
# =============================================================================


def test_cross_region_model_gets_inference_profile_permission(builtin_default):
    """eu.* model should get inference-profile ARN + foundation-model wildcard."""
    template = Template.from_stack(builtin_default)
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": [
                                    "bedrock:InvokeModel",
                                    "bedrock:InvokeModelWithResponseStream",
                                ],
                                "Effect": "Allow",
                                "Resource": [
                                    "arn:aws:bedrock:eu-west-2:123456789012:inference-profile/eu.anthropic.claude-sonnet-4-6",
                                    "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6",
                                ],
                            }
                        )
                    ]
                )
            }
        },
    )


def test_custom_agent_gets_model_permissions(custom_agent_with_memory):
    """CustomAgent should also get bedrock:InvokeModel permissions."""
    template = Template.from_stack(custom_agent_with_memory)
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": [
                                    "bedrock:InvokeModel",
                                    "bedrock:InvokeModelWithResponseStream",
                                ],
                                "Effect": "Allow",
                            }
                        )
                    ]
                )
            }
        },
    )


def test_memory_read_permissions_granted(builtin_default):
    """When memory is enabled, runtime should have memory read access."""
    template = Template.from_stack(builtin_default)
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
                                        "bedrock-agentcore:GetEvent",
                                        "bedrock-agentcore:ListEvents",
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


def test_memory_write_permissions_granted(builtin_default):
    """When memory is enabled, runtime should have memory write access."""
    template = Template.from_stack(builtin_default)
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": "bedrock-agentcore:CreateEvent",
                                "Effect": "Allow",
                            }
                        )
                    ]
                )
            }
        },
    )


def test_no_memory_resource_when_disabled(builtin_no_memory):
    """When memory=None, no memory resource should exist."""
    template = Template.from_stack(builtin_no_memory)
    template.resource_count_is("AWS::BedrockAgentCore::Memory", 0)


def test_cloudwatch_logs_permission(builtin_default):
    template = Template.from_stack(builtin_default)
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": [
                                    "logs:CreateLogGroup",
                                    "logs:CreateLogStream",
                                    "logs:PutLogEvents",
                                    "logs:DescribeLogStreams",
                                ],
                                "Effect": "Allow",
                            }
                        )
                    ]
                )
            }
        },
    )


def test_xray_permission(builtin_default):
    template = Template.from_stack(builtin_default)
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": [
                                    "xray:PutTraceSegments",
                                    "xray:PutTelemetryRecords",
                                    "xray:GetSamplingRules",
                                    "xray:GetSamplingTargets",
                                ],
                                "Effect": "Allow",
                                "Resource": "*",
                            }
                        )
                    ]
                )
            }
        },
    )


def test_cloudwatch_metrics_permission(builtin_default):
    template = Template.from_stack(builtin_default)
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": "cloudwatch:PutMetricData",
                                "Effect": "Allow",
                                "Condition": {
                                    "StringEquals": {
                                        "cloudwatch:namespace": "bedrock-agentcore"
                                    },
                                },
                            }
                        )
                    ]
                )
            }
        },
    )


def test_agentcore_identity_permission(builtin_default):
    template = Template.from_stack(builtin_default)
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": [
                                    "bedrock-agentcore:GetWorkloadAccessToken",
                                    "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                                    "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
                                ],
                                "Effect": "Allow",
                            }
                        )
                    ]
                )
            }
        },
    )


def test_observability_permissions_present_for_custom_agent(custom_agent_no_memory):
    """Custom agents should also get logging/xray/metrics permissions."""
    template = Template.from_stack(custom_agent_no_memory)
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": [
                                    "xray:PutTraceSegments",
                                    "xray:PutTelemetryRecords",
                                    "xray:GetSamplingRules",
                                    "xray:GetSamplingTargets",
                                ],
                                "Effect": "Allow",
                            }
                        )
                    ]
                )
            }
        },
    )


# =============================================================================
# Gateway tests
# =============================================================================


def _gateway_param_logical_id(template, ssm_path):
    """Find the CFN parameter logical ID that resolves the given SSM path."""
    for logical_id, param in template.to_json()["Parameters"].items():
        if param.get("Default") == ssm_path:
            return logical_id
    raise AssertionError(f"No CloudFormation parameter for {ssm_path}")


def test_gateway_reads_url_and_arn_from_ssm(gateway_unfiltered):
    """Tests that the gateway URL and ARN are resolved from SSM at deploy time."""
    template = Template.from_stack(gateway_unfiltered)
    for attribute in ("url", "arn"):
        template.has_parameter(
            "*",
            {
                "Type": "AWS::SSM::Parameter::Value<String>",
                "Default": f"/gds-idea/gateways/idea-data/{attribute}",
            },
        )


def test_gateway_urls_env_var_is_json_list_of_ssm_values(gateway_filtered):
    template = Template.from_stack(gateway_filtered)
    url_a = _gateway_param_logical_id(template, "/gds-idea/gateways/idea-data/url")
    url_b = _gateway_param_logical_id(template, "/gds-idea/gateways/other/url")
    template.has_resource_properties(
        "AWS::BedrockAgentCore::Runtime",
        {
            "EnvironmentVariables": Match.object_like(
                {
                    "GATEWAY_URLS": {
                        "Fn::Join": [
                            "",
                            ['["', {"Ref": url_a}, '","', {"Ref": url_b}, '"]'],
                        ]
                    }
                }
            ),
        },
    )


def test_gateway_targets_env_var_set_when_filtered(gateway_filtered):
    template = Template.from_stack(gateway_filtered)
    template.has_resource_properties(
        "AWS::BedrockAgentCore::Runtime",
        {"EnvironmentVariables": Match.object_like({"GATEWAY_TARGETS": '["wfc"]'})},
    )


def test_no_gateway_targets_env_var_when_unfiltered(gateway_unfiltered):
    """No GATEWAY_TARGETS means the agent keeps every tool on the gateway."""
    template_json = Template.from_stack(gateway_unfiltered).to_json()
    for resource in template_json["Resources"].values():
        if resource["Type"] == "AWS::BedrockAgentCore::Runtime":
            env_vars = resource["Properties"]["EnvironmentVariables"]
            assert "GATEWAY_URLS" in env_vars
            assert "GATEWAY_TARGETS" not in env_vars


def test_gateway_invoke_permission_uses_exact_gateway_arns(gateway_filtered):
    """InvokeGateway rejects wildcards, so each gateway ARN is listed exactly."""
    template = Template.from_stack(gateway_filtered)
    arn_a = _gateway_param_logical_id(template, "/gds-idea/gateways/idea-data/arn")
    arn_b = _gateway_param_logical_id(template, "/gds-idea/gateways/other/arn")
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        {
                            "Sid": "GatewayInvoke",
                            "Action": "bedrock-agentcore:InvokeGateway",
                            "Effect": "Allow",
                            "Resource": [{"Ref": arn_a}, {"Ref": arn_b}],
                        }
                    ]
                )
            }
        },
    )


def test_no_gateway_resources_when_not_configured(builtin_default):
    template = Template.from_stack(builtin_default)
    template_json = template.to_json()
    assert not any(
        "gateways" in param.get("Default", "")
        for param in template_json["Parameters"].values()
    )
    for resource in template_json["Resources"].values():
        if resource["Type"] == "AWS::BedrockAgentCore::Runtime":
            env_vars = resource["Properties"]["EnvironmentVariables"]
            assert "GATEWAY_URLS" not in env_vars
        if resource["Type"] == "AWS::IAM::Policy":
            sids = [
                s.get("Sid")
                for s in resource["Properties"]["PolicyDocument"]["Statement"]
            ]
            assert "GatewayInvoke" not in sids


def test_custom_agent_gets_gateway_env_vars_and_permission(cdk_app, cdk_env):
    """CustomAgent gets the same env vars and IAM grant, and wires MCP itself."""
    stack = AgentCore(
        cdk_app,
        "CustomGatewayStack",
        props=AgentCoreProperties(
            runtime_name="custom_gw",
            agent=CustomAgent(agent_code_directory="tests/fixtures/fake_agent/"),
            gateway=GatewayConfig(targets=["wfc"]),
        ),
        env=cdk_env,
    )
    template = Template.from_stack(stack)
    template.has_resource_properties(
        "AWS::BedrockAgentCore::Runtime",
        {
            "EnvironmentVariables": Match.object_like(
                {
                    "GATEWAY_URLS": Match.any_value(),
                    "GATEWAY_TARGETS": '["wfc"]',
                }
            ),
        },
    )
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [Match.object_like({"Sid": "GatewayInvoke"})]
                )
            }
        },
    )
