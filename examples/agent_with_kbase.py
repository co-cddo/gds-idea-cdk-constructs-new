"""Example: AgentCore runtime with a Knowledge Base attached
Usage:
    cdk synth          # Verify CloudFormation templates
    cdk deploy --all   # Deploy both stacks to AWS
After deployment:
    1. Upload documents to the KB data bucket (see DataBucketName output)
    2. Wait for auto-sync to ingest (default 5 min batch window)
    3. Invoke the AgentCore runtime and ask questions about your documents

    Deploy/Test with
    cdk deploy --all --require-approval broadening --app "python agent_with_kb.app.py"

    1) Set up a small knowledge base file in terminal for the dev account
    # Testing it

    echo "The team standup is every day at 9:30am. The retrospective is on Fridays at 2pm." > test-doc.txt
    aws s3 cp test-doc.txt s3://my-agent-kb-kb-data-development/

    2) Run from the terminal with bedrock-agentcore cli (assuming deployed in dev account), runtime arn is provided during deployment
    aws bedrock-agentcore invoke-agent-runtime \
    --agent-runtime-arn <RUNTIME-ARN> \
    --payload "$(echo -n '{"prompt":"When is the team standup?","session_id":"test-kb-1"}' | base64)" \
    --region eu-west-2 \
    outfile.json


"""

import aws_cdk as cdk

from gds_idea_cdk_constructs import DeploymentConfig
from gds_idea_cdk_constructs.agent_core import AgentCore, AgentCoreProperties
from gds_idea_cdk_constructs.knowledge_base import (
    ChunkingConfig,
    KnowledgeBase,
    KnowledgeBaseProps,
)

app = cdk.App()
# --- Environment ---
cdk_env = cdk.Environment(
    account="992382722318",
    region="eu-west-2",
)
# --- Shared config (resolves from Secrets Manager) ---
config = DeploymentConfig(cdk_env)
# --- Knowledge Base ---
kb = KnowledgeBase(
    app,
    deployment_config=config,
    app_config="my-agent-kb",
    kb_props=KnowledgeBaseProps(
        chunking=ChunkingConfig.fixed_size(max_tokens=500, overlap_percentage=10),
        description="Knowledge base for the agent demo",
        retain_on_delete=False,
    ),
)
# --- AgentCore Runtime (with KB attached) ---
agent = AgentCore(
    app,
    "MyAgentStack",
    props=AgentCoreProperties(
        runtime_name="my_kb_agent",
        memory_name="my_kb_agent_session_store",
        environment_variables=kb.environment_variables,
    ),
    env=cdk_env,
)
# --- Cross-stack: grant the agent permission to query the KB ---
kb.grant_retrieve(agent.runtime_role)

app.synth()
