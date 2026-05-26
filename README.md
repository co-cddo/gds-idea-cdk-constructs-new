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
| `knowledge_base` | `KnowledgeBaseConfig \| None` | `None` | Optional KB attachment (auto-wires env vars + permissions) |
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

<<<<<<< HEAD
Docs https://co-cddo.github.io/gds-idea-cdk-constructs-new/
=======
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

Docs https://co-cddo.github.io/gds-idea-cdk-constructs/
>>>>>>> 5592a04 (Added to readme for new knowledge base config)
