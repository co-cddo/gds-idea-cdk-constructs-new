# gds-idea-cdk-constructs

A repo for commonly used constructs in the team.

## WebApp

This simplifies the deployment of containerised applications in the gds-idea team infrastructure.
It is not designed to be used directly but it is a dependency managed by [gds-idea-app-kit](https://github.com/co-cddo/gds-idea-app-kit).
For instructions on usage please see the docs for gds-idea-app-kit.

## AgentCore

Deploys an [Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock/latest/userguide/agentcore.html) runtime with memory, permissions, and observability pre-configured. The built-in agent uses Strands Agent Framework.

### Quick start (zero-config)

Uses the built-in agent template with sensible defaults — no code to copy:

```python
from gds_idea_cdk_constructs.agent_core import AgentCore, AgentCoreProperties

AgentCore(
    app,
    "MyAgent",
    props=AgentCoreProperties(runtime_name="my-agent"),
)
```

### Built-in agent with custom settings

Configure the model, system prompt, and memory without writing agent code:

```python
from gds_idea_cdk_constructs.agent_core import (
    AgentCore,
    AgentCoreProperties,
    BuiltInAgent,
    ModelConfig,
    MemoryConfig,
)

AgentCore(
    app,
    "MyAgent",
    props=AgentCoreProperties(
        runtime_name="my-data-agent",
        agent=BuiltInAgent(
            model=ModelConfig(
                model_id="eu.anthropic.claude-sonnet-4-6",
                max_tokens=8000,
                budget_tokens=4000,
            ),
            system_prompt="You are a helpful data analyst.",
            log_level="DEBUG",
        ),
        memory=MemoryConfig(name="my-memory"),
    ),
)
```

To disable memory, pass `memory=None`.

### Custom agent code

For full control (adding tools, custom logic), use `CustomAgent`:

```python
from gds_idea_cdk_constructs.agent_core import (
    AgentCore,
    AgentCoreProperties,
    CustomAgent,
)

AgentCore(
    app,
    "MyAgent",
    props=AgentCoreProperties(
        runtime_name="my-agent",
        agent=CustomAgent(
            agent_code_directory="my_agent_code/",
            model_id="eu.anthropic.claude-sonnet-4-6",
            environment_variables={"MY_API_KEY": "secret"},
        ),
        memory=None,
    ),
)
```

Your directory must contain a `Dockerfile` and an `agent.py` entrypoint. The built-in `agent_template/` can be copied as a starting point.

The construct automatically injects these env vars into your container:

| Variable | When |
|---|---|
| `MODEL_ID` | Always |
| `REGION` | Always |
| `MEMORY_ID` | When `memory` is set |

### Configuration reference

#### `AgentCoreProperties`

| Property | Type | Default | Description |
|---|---|---|---|
| `runtime_name` | `str` | *(required)* | Unique name per account/region |
| `agent` | `BuiltInAgent \| CustomAgent` | `BuiltInAgent()` | Agent mode |
| `memory` | `MemoryConfig \| None` | `MemoryConfig()` | Memory config, or `None` to skip |
| `description` | `str` | `"An AgentCore Runtime..."` | Runtime description |
| `platform` | `Platform` | `LINUX_ARM64` | Docker build target |
| `removal_policy` | `RemovalPolicy` | `DESTROY` | Removal policy for stateful resources |

#### `BuiltInAgent`

| Property | Type | Default | Description |
|---|---|---|---|
| `model` | `ModelConfig` | `ModelConfig()` | Model configuration |
| `system_prompt` | `str` | `""` | System prompt (overrides default file) |
| `log_level` | `str` | `"INFO"` | Log level |

#### `ModelConfig`

| Property | Type | Default | Description |
|---|---|---|---|
| `model_id` | `str` | `"eu.anthropic.claude-sonnet-4-6"` | Bedrock model ID |
| `max_tokens` | `int` | `8000` | Max output tokens (thinking + reply) |
| `budget_tokens` | `int` | `4000` | Thinking budget (must be < max_tokens) |
| `thinking_enabled` | `bool` | `True` | Enable extended thinking |
| `max_history` | `int` | `20` | Conversation turns to retain |

#### `CustomAgent`

| Property | Type | Default | Description |
|---|---|---|---|
| `agent_code_directory` | `str` | *(required)* | Path to agent code + Dockerfile |
| `model_id` | `str` | `"eu.anthropic.claude-sonnet-4-6"` | Bedrock model ID |
| `environment_variables` | `dict` | `{}` | Extra env vars for your container |

#### `MemoryConfig`

| Property | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | `"chat_session_store"` | Memory store name |
| `description` | `str` | `"Stores short-term..."` | Memory store description |

Docs https://co-cddo.github.io/gds-idea-cdk-constructs-new/
