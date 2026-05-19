# WebApp with AgentCore Runtime

This example demonstrates how to connect a web application to a deployed
AgentCore runtime with a Knowledge Base attached. All you need is a single environment variable: `AGENTCORE_RUNTIME_ARN`.

## Using with a Deployed WebApp (CDK)

When deploying a WebApp to AWS via CDK, the pattern would be:
Knowledge Base → AgentCore → WebApp, with grants wiring them together.

```python
import aws_cdk as cdk
from gds_idea_cdk_constructs import AppConfig, DeploymentConfig
from gds_idea_cdk_constructs.agent_core import (
    DEFAULT_AGENT_CODE_DIR,
    AgentCore,
    AgentCoreProperties,
    CustomAgent,
    MemoryConfig,
)
from gds_idea_cdk_constructs.knowledge_base import (
    ChunkingConfig,
    KnowledgeBase,
    KnowledgeBaseProps,
)
from gds_idea_cdk_constructs.web_app import WebApp, WebAppContainerProperties

app = cdk.App()
cdk_env = cdk.Environment(account="...", region="eu-west-2")
config = DeploymentConfig(cdk_env)
app_config = AppConfig(app_name="my-app", framework="streamlit")

# 1. Knowledge Base
kb = KnowledgeBase(
    app,
    deployment_config=config,
    app_config="my-app",
    kb_props=KnowledgeBaseProps(
        chunking=ChunkingConfig.fixed_size(max_tokens=500, overlap_percentage=10),
        description="Documents for the agent",
    ),
)

# 2. AgentCore Runtime (with KB attached)
agent = AgentCore(
    app,
    "AgentStack",
    props=AgentCoreProperties(
        runtime_name="my_agent",
        agent=CustomAgent(
            agent_code_directory=DEFAULT_AGENT_CODE_DIR,
            environment_variables=kb.environment_variables,
        ),
    ),
    env=cdk_env,
)
kb.grant_retrieve(agent.runtime_role)

# 3. WebApp — pass the runtime ARN and grant invoke permissions
webapp = WebApp(
    app,
    deployment_config=config,
    app_config=app_config,
    container_props=WebAppContainerProperties(
        environment_variables=agent.environment_variables,
    ),
)
agent.grant_invoke(webapp.task_role)

app.synth()
```

This:

- Passes `AGENTCORE_RUNTIME_ARN` into the Fargate container automatically
- Grants the task role `bedrock-agentcore:InvokeAgentRuntime` permission
- Grants the AgentCore runtime role `bedrock:Retrieve` on the Knowledge Base

## Application Code

The integration in an app is straightforward (see `app_src/streamlit_app.py`):

```python
import boto3
import json
import os

client = boto3.client("bedrock-agentcore", region_name="eu-west-2")

payload = json.dumps({
    "prompt": user_input,
    "session_id": session_id,
})

response = client.invoke_agent_runtime(
    agentRuntimeArn=os.environ["AGENTCORE_RUNTIME_ARN"],
    payload=payload.encode(),
)

# Parse the streaming response (Server-Sent Events)
body = response["response"].read().decode("utf-8")

output = ""
for line in body.splitlines():
    if not line.startswith("data: "):
        continue
    event = json.loads(line[6:])
    if event.get("type") == "text":
        output += event.get("data", "")
    elif event.get("type") == "done" and not output:
        output = event.get("response", "")
```

## Running Locally (Smoke Test)

This directory is structured as an idea-app project so you can run the app
locally with `idea-app smoke-test` against a deployed AgentCore runtime.

### Prerequisites

- `idea-app` CLI installed
- Docker running
- AWS credentials (via `aws sso login` or similar)
- AgentCore + KB deployed (see `examples/agent_with_kbase.py`)

### Steps

1. **Deploy the AgentCore + Knowledge Base** (from the repo root):

   ```bash
   cdk deploy --all --require-approval broadening \
       --app "python examples/agent_with_kbase.py"
   ```

   Note the `RuntimeArn` from the stack outputs.

2. **Upload a test document** to the KB data bucket:

   ```bash
   echo "The team standup is every day at 9:30am. The retrospective is on Fridays at 2pm." > test-doc.txt
   aws s3 cp test-doc.txt s3://<DataBucketName-output>/
   ```

   Wait ~5 minutes for auto-sync to ingest.

3. **Set the runtime ARN**:

   ```bash
   export AGENTCORE_RUNTIME_ARN="arn:aws:bedrock-agentcore:eu-west-2:992382722318:runtime/..."
   ```

4. **Provide credentials to the container**:

   ```bash
   cd examples/webapp_with_agent
   AWS_PROFILE=your-profile idea-app provide-role
   ```

5. **Run the app**:

   ```bash
   idea-app smoke-test --wait
   ```

6. **Open http://localhost:8080** and ask a question (e.g. "When is the team standup?").

   Press Enter in the terminal to stop and clean up.

7. **Destroy the example AgentCore and Knowledge base stacks** (from the repo root):

    Note: It may throw an error during deletion of the S3 bucket and you will need to delete manually in Cloudformation as versioning information may stop deletion of the bucket 
    and cause a failed stack state. The knowledge base stack implements auto_delete_objects by default when retain_on_delete is set to False.

    ```bash
    cdk destroy --all --app "python examples/agent_with_kbase.py"
    ```