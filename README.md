# gds-idea-cdk-constructs

A repo for commonly used constructs in the team.

## WebApp

This simplifies the deployment of containerised applications in the gds-idea team infrastructure.
It is not designed to be used directly but it is a dependency managed by [gds-idea-app-kit](https://github.com/co-cddo/gds-idea-app-kit).
For instructions on usage please see the docs for gds-idea-app-kit.

## Tagging

`IdeaTags` applies the standard GDS IDEA tags (`Environment`, `ManagedBy`, `Repository`, `AppName` and optionally `Owner`) to every stack and resource in an app.
Values are validated on creation, so a placeholder such as `TBA`, a repository that is not a bare repo name, or a comma in an owner fails immediately.

```python
from gds_idea_cdk_constructs import IdeaTags

IdeaTags(
    environment=dep_config.environment,
    app_name=app_config.app_name,
    repository="gds-idea-app-example",
    owners=["Alice Example", "Bob Example"],  # optional, names not emails, joined with "+"
).apply(app)
```

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
| `GATEWAY_URLS` | When `gateway` is set |
| `GATEWAY_TARGETS` | When `gateway` is set with `targets` |

### Conversations and `runtimeSessionId`

The built-in agent keeps one agent alive for the length of a conversation, instead of rebuilding it on every message. Its history is loaded from Memory on the first message, then kept in the container.

AgentCore routes requests to the same container only when they carry the same `runtimeSessionId`. **Callers must pass one**, and use the same value as the `session_id` in the payload:

```python
client.invoke_agent_runtime(
    agentRuntimeArn=runtime_arn,
    runtimeSessionId=session_id,  # at least 33 characters; a uuid4 string works
    payload=json.dumps({"prompt": prompt, "session_id": session_id}).encode(),
)
```

The agent rejects a request whose payload `session_id` is missing or differs from the `runtimeSessionId` with HTTP 422. boto3 raises this in the caller as `RuntimeClientError` ("Received error (422) from runtime"); the reason is in the agent's CloudWatch logs. This matters because boto3 makes up a new `runtimeSessionId` when you leave it out, so a forgotten ID would otherwise start a fresh, empty conversation on every message.

Things to know:

- **Warm versus cold history.** A warm container remembers earlier tool calls and their results. After a restart (15 minutes idle, 8 hours maximum) only the saved user and assistant text is reloaded, so the agent may repeat a tool call it already made.
- **Restart reloads a window, not everything.** After a restart only the newest `max_history` saved messages are loaded (default 20, about 10 turns). Older messages are still in Memory but are not given to the agent.
- **One turn at a time.** A second message in the same conversation waits for the first to finish.
- **Failed or abandoned turns.** If a turn fails, or the client disconnects mid-reply, the agent is dropped and rebuilt from Memory on the next message.
- **A new `session_id`** in the same container starts a fresh agent with that conversation's history.
- **Memory is still written every turn**, so no conversation depends on a container staying alive.
- **Checking it works.** Logs show `Building agent | Session=...` when an agent is built. Later turns in the same conversation log only `Turn start | ... | Messages=N`, with N growing.

`CustomAgent` is unaffected: this behaviour lives in the built-in template.

### Using tools from a shared gateway

Tools live in one shared AgentCore Gateway, owned by a separate repository. This construct never creates a gateway: it looks one up and lets the agent use its tools.

```python
import aws_cdk as cdk

from gds_idea_cdk_constructs.agent_core import (
    AgentCore,
    AgentCoreProperties,
    GatewayConfig,
)

# Only the tools of the "gats" target
AgentCore(
    app,
    "GatsAgent",
    props=AgentCoreProperties(
        runtime_name="gats_agent",
        gateway=GatewayConfig(targets=["gats"]),
    ),
    env=cdk.Environment(account="123456789012", region="eu-west-2"),
)

# Every tool on the gateway, including ones added later
AgentCore(
    app,
    "DiaAgent",
    props=AgentCoreProperties(
        runtime_name="dia_agent",
        gateway=GatewayConfig(),
    ),
)
```

Tools are named `{target}___{tool}` (three underscores), so `targets=["gats"]` keeps every tool whose name starts with `gats___`.

What the construct does for you:

- Reads the gateway URL and ARN from `/gds-idea/gateways/{name}/url` and `/arn` at deploy time.
- Lets the runtime role call the gateway (`bedrock-agentcore:InvokeGateway`, on the exact gateway ARN).
- Passes `GATEWAY_URLS` (and `GATEWAY_TARGETS`, when you pin targets) to the agent.
- Checks your targets exist at synth time, so a typo fails the build instead of leaving the agent without tools.

#### Two separate controls

| | Where | What it does |
|---|---|---|
| `targets=[...]` | This construct | Keeps the agent's tool list short. Not a security control: it is a filter in the agent's own code. |
| Cedar policies | The gateway repository | Decides which callers may use which tools. Enforced by the gateway. |

#### Things to know

- **Pinned targets need a real `env=`.** The check reads the gateway's tool list at synth time, which needs a concrete account and region. With no `targets`, no lookup happens.
- **The tool list is cached** in `cdk.context.json`. If you add a target that was created after the cache was written, synth fails and prints the exact `cdk context --reset '...'` command to run.
- **The first synth skips the check.** The CDK returns a placeholder until it has fetched the value, then synthesises again. A typo is caught on that second pass.
- **Deploy the gateway first.** The URL and ARN come from SSM parameters the gateway repository publishes. If they do not exist, the deploy fails.
- **If a gateway is recreated,** redeploy each agent that uses it, so it picks up the new URL and ARN.
- **The gateway's Cedar policy needs this agent's role name.** The role is named `{runtime_name}-{region}` (for example `gats_agent-eu-west-2`), so the caller is `arn:aws:sts::<account>:assumed-role/<runtime_name>-<region>`. Changing `runtime_name` changes the role, so the policy must change too. If the name does not match, the agent sees no tools.
- **A change that forces the role to be replaced needs the role renamed first.** The role has a fixed name, and CloudFormation cannot create a replacement with the same name while the old one exists.
- **New gateway tools appear when the agent is next built:** a new conversation, or within 15 minutes (see below). Not instantly.
- **Semantic search.** If the gateway has semantic search on, it adds a built-in `x_amz_bedrock_agentcore_search` tool. Pinned agents do not get it (it has no `target___` prefix); agents with no `targets` do.
- **Target names use single underscores** (`gats_kb`, not `gats__kb`), so they cannot be confused with the `___` separator.
- **Several gateways** can be listed in `gateways=[...]`. A target may live on any of them.

#### How the connection is kept

The agent opens its gateway connections when it is built and closes them when it is replaced. Because one agent now lasts a whole conversation, it is also rebuilt every **15 minutes**, keeping its messages, so a connection that has quietly dropped does not stay broken.

- The turn that triggers a rebuild pays the reconnect time.
- A connection can also drop between rebuilds. Strands does not raise an error then: the model receives an error result from the tool (`Tool execution failed: ...`). The agent spots such a result on a gateway tool and rebuilds on the **next** message. The message where the drop happened still gets a poor answer. Errors a tool reports about its own work, such as bad SQL, do not trigger a rebuild. At most one of these rebuilds happens per minute.
- If the gateway cannot be reached during a rebuild, the agent carries on with its current connection and tries again after 60 seconds, so an unreachable gateway does not slow down every message.
- If the gateway cannot be reached when a conversation starts, that message fails with an error. The agent never silently runs without its tools.

#### With `CustomAgent`

A custom agent gets the same environment variables and `InvokeGateway` permission, but connects itself:

| Variable | Value |
|---|---|
| `GATEWAY_URLS` | JSON list of MCP endpoint URLs |
| `GATEWAY_TARGETS` | JSON list of target names. Only set when you pin targets; absent means keep everything. |

Requests must be signed with SigV4 for the `bedrock-agentcore` service. The built-in agent template shows how (`agent_template/_gateway.py`).

### Configuration reference

#### `AgentCoreProperties`

| Property | Type | Default | Description |
|---|---|---|---|
| `runtime_name` | `str` | *(required)* | Unique name per account/region |
| `agent` | `BuiltInAgent \| CustomAgent` | `BuiltInAgent()` | Agent mode |
| `memory` | `MemoryConfig \| None` | `MemoryConfig()` | Memory config, or `None` to skip |
| `knowledge_base` | `KnowledgeBaseConfig \| None` | `None` | Optional KB attachment (auto-wires env vars + permissions) |
| `gateway` | `GatewayConfig \| None` | `None` | Optional shared-gateway attachment (auto-wires URL, permissions, env vars) |
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
| `max_history` | `int` | `20` | Saved messages loaded from Memory when a conversation's agent is built |

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

#### `GatewayConfig`

| Property | Type | Default | Description |
|---|---|---|---|
| `gateways` | `list[str]` | `["idea-data"]` | Gateway names. Lowercase letters, digits and hyphens. |
| `targets` | `list[str] \| None` | `None` | Targets to keep, e.g. `["gats"]`. `None` keeps every tool, including future ones. An empty list is rejected. |

## Knowledge Base

Creates an [Amazon Bedrock Knowledge Base](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html) with S3 data source, vector storage, and automatic sync. Supports configurable chunking strategies, embedding models, and storage backends.

### Quick start (all defaults)

Deploys a Knowledge Base with Titan V2 embeddings, S3 Vectors storage, no chunking, and auto-sync enabled:

```python
from gds_idea_cdk_constructs import DeploymentConfig
from gds_idea_cdk_constructs.knowledge_base import KnowledgeBase

kb = KnowledgeBase(app, deployment_config=config, app_config="my-kb")
```

### Custom chunking and embedding

```python
from gds_idea_cdk_constructs.knowledge_base import (
    KnowledgeBase,
    KnowledgeBaseProps,
    ChunkingConfig,
    EmbeddingModel,
)

kb = KnowledgeBase(
    app,
    deployment_config=config,
    app_config="my-kb",
    kb_props=KnowledgeBaseProps(
        chunking=ChunkingConfig.semantic(max_tokens=400),
        embedding_model=EmbeddingModel.COHERE_ENGLISH_V3,
        inclusion_prefixes=["documents/"],
        retain_on_delete=False,  # dev only, deletes S3 bucket and contents on cdk destroy
    )
)
```

Note: retain_on_delete defaults to True i.e. the S3 bucket and any data therein will NOT be deleted. The stack should be emptied and deleted manually in this case. Otherwise, to avoid doing this, set retain_on_delete to False to allow
cdk to destroy the s3 bucket and any data located inside.

### Attaching to AgentCore

Use `KnowledgeBaseConfig` to wire a Knowledge Base into an AgentCore runtime:

```python
from gds_idea_cdk_constructs import DeploymentConfig
from gds_idea_cdk_constructs.agent_core import (
    AgentCore,
    AgentCoreProperties,
    KnowledgeBaseConfig,
)
from gds_idea_cdk_constructs.knowledge_base import KnowledgeBase

# Knowledge Base (all defaults: Titan V2, S3 Vectors, no chunking, auto-sync)
kb = KnowledgeBase(app, deployment_config=config, app_config="my-agent-kb")

# AgentCore Runtime (BuiltInAgent default + KB attached)
AgentCore(
    app,
    "MyAgentStack",
    props=AgentCoreProperties(
        runtime_name="my_kb_agent",
        knowledge_base=KnowledgeBaseConfig(knowledge_base=kb),
    )
)
```

For a CustomAgent with tuned retrieval settings:

```python
from gds_idea_cdk_constructs.agent_core import CustomAgent
from gds_idea_cdk_constructs.knowledge_base import ChunkingConfig, KnowledgeBaseProps

kb = KnowledgeBase(
    app,
    deployment_config=config,
    app_config="my-agent-kb",
    kb_props=KnowledgeBaseProps(
        chunking=ChunkingConfig.semantic(max_tokens=400),
        retain_on_delete=False,
    ),
)

AgentCore(
    app,
    "MyAgentStack",
    props=AgentCoreProperties(
        runtime_name="my_kb_agent",
        agent=CustomAgent(
            agent_code_directory="path/to/my_agent/",
        ),
        knowledge_base=KnowledgeBaseConfig(
            knowledge_base=kb,
            min_score=0.7,
        ),
    )
)
```

See [`examples/agent_with_kbase.py`](examples/agent_with_kbase.py) for a full working example.

### Manual integration (without AgentCore)

Use this pattern to query a Knowledge Base directly from a WebApp or Lambda — without an AgentCore runtime in between, and grant_retrieve the webapp or lambda role to give it access alongside any other LLM-based permissions:

```python
import aws_cdk as cdk

from gds_idea_cdk_constructs import AppConfig, DeploymentConfig
from gds_idea_cdk_constructs.knowledge_base import KnowledgeBase
from gds_idea_cdk_constructs.web_app import WebApp, WebAppContainerProperties

app = cdk.App()
cdk_env = cdk.Environment()
config = DeploymentConfig(cdk_env)
app_config = AppConfig(app_name="my-app", framework="streamlit")

# Knowledge Base
kb = KnowledgeBase(app, deployment_config=config, app_config="my-app")

# WebApp with KB env vars injected
webapp = WebApp(
    app,
    deployment_config=config,
    app_config=app_config,
    container_props=WebAppContainerProperties(
        environment_variables=kb.environment_variables,
    ),
)

# Grant the task role permission to query the KB directly
kb.grant_retrieve(webapp.task_role)

app.synth()
```

Your application code can then call the Bedrock Retrieve API:

```python
import os
import boto3

client = boto3.client("bedrock-agent-runtime", region_name="eu-west-2")

response = client.retrieve(
    knowledgeBaseId=os.environ["KB_ID"],
    retrievalQuery={"text": "What is the team standup schedule?"},
)

for result in response["retrievalResults"]:
    print(result["content"]["text"])
```

### WebApp with Agent example

[`examples/webapp_with_agent/`](examples/webapp_with_agent/) shows a full deployment connecting a Streamlit web app to a deployed AgentCore runtime, including local smoke testing with `idea-app`. See [`examples/webapp_with_agent/README.md`](examples/webapp_with_agent/README.md) for deployment and testing instructions.

### Configuration reference

#### `KnowledgeBaseProps`

| Property | Type | Default | Description |
|---|---|---|---|
| `storage_type` | `StorageType` | `S3_VECTORS` | Vector storage backend |
| `embedding_model` | `EmbeddingModel` | `TITAN_V2` | Bedrock embedding model |
| `embedding_dimensions` | `int \| None` | `None` (auto) | Vector dimensions (auto-detected from model) |
| `distance_metric` | `str` | `"cosine"` | Distance metric for vector index |
| `chunking` | `ChunkingConfig` | `ChunkingConfig.none()` | Document chunking strategy |
| `inclusion_prefixes` | `list[str]` | `[]` | S3 key prefixes to include (empty = all) |
| `data_deletion_policy` | `str` | `"DELETE"` | Vector cleanup when source is removed |
| `enable_auto_sync` | `bool` | `True` | SQS-debounced auto-sync on S3 upload |
| `sync_batch_window_seconds` | `int` | `300` | SQS batching window (max 300s) |
| `retain_on_delete` | `bool` | `True` | RETAIN removal policy for bucket + vectors |
| `description` | `str` | `""` | Description on the Bedrock KB resource |

#### `KnowledgeBaseConfig` (for AgentCore attachment)

| Property | Type | Default | Description |
|---|---|---|---|
| `knowledge_base` | `KnowledgeBase` | *(required)* | The KnowledgeBase stack to attach |
| `min_score` | `float` | `0.4` | Minimum relevance score threshold (0.0–1.0) |
| `enable_metadata` | `bool` | `False` | Include source metadata in retrieval results |

#### Chunking strategies

| Factory method | Key params | Description |
|---|---|---|
| `ChunkingConfig.none()` | — | No chunking; each file is one document |
| `ChunkingConfig.fixed_size(max_tokens, overlap_percentage)` | `300`, `20` | Fixed-size token chunks with overlap |
| `ChunkingConfig.hierarchical(max_tokens, overlap_percentage)` | `300`, `20` | Two-level parent/child chunks |
| `ChunkingConfig.semantic(max_tokens, buffer_size, breakpoint_percentile_threshold)` | `300`, `0`, `95` | Split on semantic boundaries |

Docs https://co-cddo.github.io/gds-idea-cdk-constructs-new/
