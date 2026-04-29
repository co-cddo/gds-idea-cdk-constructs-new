# gds-idea-cdk-constructs

A repo for commonly used constructs in the team.

## WebApp

This simplifies the deployment of containerised applications in the gds-idea team infrastructure.
It is not designed to be used directly but it is a dependency in the [app templates repo](https://github.com/co-cddo/gds-idea-app-templates)
For instructions on usage please see the docs for gds-idea-app-templates.

## AgentCore

Deploys an [Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock/latest/userguide/agentcore.html) runtime with memory, permissions, and observability pre-configured.

### Quick start (zero-config)

Uses the built-in agent template — no code to copy:

```python
from gds_idea_cdk_constructs.agent_core import AgentCore, AgentCoreProperties

AgentCore(
    app,
    "MyAgent",
    props=AgentCoreProperties(
        runtime_name="my-agent",
    ),
)
```

### Configuring via props

Everything is configurable without modifying agent code:

```python
AgentCore(
    app,
    "MyAgent",
    props=AgentCoreProperties(
        runtime_name="my-data-agent",
        model_id="eu.anthropic.claude-sonnet-4-6",
        system_prompt="You are a helpful data analyst. Today is {today}.",
        log_level="DEBUG",
        environment_variables={
            "BUDGET_TOKENS": "8000",
            "THINKING_ENABLED": "false",
            "MAX_HISTORY": "30",
        },
    ),
    env=cdk.Environment(account="123456789", region="eu-west-2"),
)
```

#### Properties

| Property | Type | Default | Description |
|---|---|---|---|
| `runtime_name` | `str` | *(required)* | Unique name per account/region |
| `description` | `str` | `"An AgentCore Runtime..."` | Runtime description |
| `agent_code_directory` | `str` | Built-in template | Path to agent code + Dockerfile |
| `platform` | `Platform` | `LINUX_ARM64` | Docker build target |
| `memory_name` | `str` | `"chat_session_store"` | Memory store name |
| `memory_description` | `str` | `"Stores short-term..."` | Memory store description |
| `model_id` | `str` | `"eu.anthropic.claude-sonnet-4-6"` | Bedrock model ID |
| `log_level` | `str` | `"INFO"` | Log level |
| `system_prompt` | `str` | `""` | System prompt (overrides default file) |
| `environment_variables` | `dict` | `{}` | Extra env vars passed to the container |

#### Agent environment variables

These are read by the built-in agent template and can be set via `environment_variables`:

| Variable | Default | Description |
|---|---|---|
| `MAX_TOKENS` | `20000` | Max output tokens per request |
| `BUDGET_TOKENS` | `16000` | Thinking budget tokens |
| `THINKING_ENABLED` | `true` | Enable/disable extended thinking |
| `MAX_HISTORY` | `20` | Max conversation history events to load |

### Custom agent code

For full control (adding tools, custom logic), point to your own directory:

```python
AgentCore(
    app,
    "MyAgent",
    props=AgentCoreProperties(
        runtime_name="my-agent",
        agent_code_directory="my_agent_code/",
    ),
)
```

Your directory must contain a `Dockerfile` and an `agent.py` entrypoint. The built-in `agent_template/` can be copied as a starting point.

Docs https://co-cddo.github.io/gds-idea-cdk-constructs/
