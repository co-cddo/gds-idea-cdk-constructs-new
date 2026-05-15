"""Unit tests for AgentCore props dataclasses."""

import pytest

from gds_idea_cdk_constructs.agent_core.props import (
    AgentCoreProperties,
    BuiltInAgent,
    CustomAgent,
    MemoryConfig,
    ModelConfig,
)


# -- ModelConfig tests --


class TestModelConfig:
    def test_defaults(self):
        config = ModelConfig()
        assert config.model_id == "eu.anthropic.claude-sonnet-4-6"
        assert config.max_tokens == 8000
        assert config.budget_tokens == 4000
        assert config.thinking_enabled is True
        assert config.max_history == 20

    def test_custom_values(self):
        config = ModelConfig(
            model_id="eu.anthropic.claude-haiku-4-5-20251001",
            max_tokens=4000,
            budget_tokens=2000,
            thinking_enabled=False,
            max_history=10,
        )
        assert config.model_id == "eu.anthropic.claude-haiku-4-5-20251001"
        assert config.max_tokens == 4000
        assert config.budget_tokens == 2000
        assert config.thinking_enabled is False
        assert config.max_history == 10

    def test_budget_tokens_must_be_less_than_max_tokens(self):
        with pytest.raises(ValueError, match="budget_tokens must be less than max_tokens"):
            ModelConfig(max_tokens=8000, budget_tokens=8000)

    def test_budget_tokens_greater_than_max_tokens_raises(self):
        with pytest.raises(ValueError, match="budget_tokens must be less than max_tokens"):
            ModelConfig(max_tokens=4000, budget_tokens=5000)

    def test_to_envs(self):
        config = ModelConfig(
            model_id="eu.anthropic.claude-sonnet-4-6",
            max_tokens=8000,
            budget_tokens=4000,
            thinking_enabled=True,
            max_history=20,
        )
        envs = config.to_envs()
        assert envs == {
            "MODEL_ID": "eu.anthropic.claude-sonnet-4-6",
            "MAX_TOKENS": "8000",
            "BUDGET_TOKENS": "4000",
            "THINKING_ENABLED": "true",
            "MAX_HISTORY": "20",
        }

    def test_to_envs_thinking_disabled(self):
        config = ModelConfig(thinking_enabled=False)
        envs = config.to_envs()
        assert envs["THINKING_ENABLED"] == "false"


# -- MemoryConfig tests --


class TestMemoryConfig:
    def test_defaults(self):
        config = MemoryConfig()
        assert config.name == "chat_session_store"
        assert config.description == "Stores short-term conversation history"

    def test_custom_values(self):
        config = MemoryConfig(name="my-store", description="Custom description")
        assert config.name == "my-store"
        assert config.description == "Custom description"


# -- BuiltInAgent tests --


class TestBuiltInAgent:
    def test_defaults(self):
        agent = BuiltInAgent()
        assert isinstance(agent.model, ModelConfig)
        assert agent.system_prompt == ""
        assert agent.log_level == "INFO"

    def test_custom_model(self):
        agent = BuiltInAgent(model=ModelConfig(budget_tokens=2000, max_tokens=4000))
        assert agent.model.budget_tokens == 2000
        assert agent.model.max_tokens == 4000

    def test_model_instances_not_shared(self):
        a = BuiltInAgent()
        b = BuiltInAgent()
        a.model.max_history = 99
        assert b.model.max_history == 20


# -- CustomAgent tests --


class TestCustomAgent:
    def test_requires_agent_code_directory(self):
        with pytest.raises(TypeError):
            CustomAgent()  # type: ignore[call-arg]

    def test_defaults(self):
        agent = CustomAgent(agent_code_directory="my_code/")
        assert agent.agent_code_directory == "my_code/"
        assert agent.model_id == "eu.anthropic.claude-sonnet-4-6"
        assert agent.environment_variables == {}

    def test_custom_values(self):
        agent = CustomAgent(
            agent_code_directory="custom/",
            model_id="eu.anthropic.claude-haiku-4-5-20251001",
            environment_variables={"KEY": "value"},
        )
        assert agent.agent_code_directory == "custom/"
        assert agent.model_id == "eu.anthropic.claude-haiku-4-5-20251001"
        assert agent.environment_variables == {"KEY": "value"}

    def test_environment_variables_not_shared(self):
        a = CustomAgent(agent_code_directory="a/")
        b = CustomAgent(agent_code_directory="b/")
        a.environment_variables["TEST"] = "value"
        assert "TEST" not in b.environment_variables


# -- AgentCoreProperties tests --


class TestAgentCoreProperties:
    def test_requires_runtime_name(self):
        with pytest.raises(TypeError):
            AgentCoreProperties()  # type: ignore[call-arg]

    def test_defaults(self):
        props = AgentCoreProperties(runtime_name="my-agent")
        assert props.runtime_name == "my-agent"
        assert isinstance(props.agent, BuiltInAgent)
        assert isinstance(props.memory, MemoryConfig)
        assert props.description == "An AgentCore Runtime deployed by the Agent Constructs Template"

    def test_builtin_agent_mode(self):
        props = AgentCoreProperties(
            runtime_name="test",
            agent=BuiltInAgent(
                model=ModelConfig(budget_tokens=2000, max_tokens=4000),
                system_prompt="Be helpful.",
                log_level="DEBUG",
            ),
        )
        assert isinstance(props.agent, BuiltInAgent)
        assert props.agent.model.budget_tokens == 2000
        assert props.agent.system_prompt == "Be helpful."
        assert props.agent.log_level == "DEBUG"

    def test_custom_agent_mode(self):
        props = AgentCoreProperties(
            runtime_name="test",
            agent=CustomAgent(
                agent_code_directory="my_code/",
                environment_variables={"API_KEY": "secret"},
            ),
        )
        assert isinstance(props.agent, CustomAgent)
        assert props.agent.agent_code_directory == "my_code/"
        assert props.agent.environment_variables == {"API_KEY": "secret"}

    def test_memory_none_disables_memory(self):
        props = AgentCoreProperties(runtime_name="test", memory=None)
        assert props.memory is None

    def test_custom_memory(self):
        props = AgentCoreProperties(
            runtime_name="test",
            memory=MemoryConfig(name="custom-store"),
        )
        assert props.memory.name == "custom-store"