"""Example: AgentCore runtime with a Knowledge Base.

Deploys:
    1. A Bedrock Knowledge Base (S3 source + vector storage + auto-sync)
    2. An AgentCore Runtime with the KB attached via KnowledgeBaseConfig

KnowledgeBaseConfig automatically:
    - Injects KB_ID / KB_SSM_PARAMETER env vars into the runtime
    - Grants bedrock:Retrieve permissions to the runtime role
    - Configures retrieval defaults (min_score, enable_metadata)

No manual grant_retrieve() or environment_variables wiring is needed.

Usage:
    cdk synth
    cdk deploy --all

After deployment:
    1. Upload documents to the KB data bucket (see DataBucketName output)
    2. Wait for auto-sync (~5 min batch window)
    3. Invoke the runtime and ask questions about your documents

Testing:
    echo "The team standup is every day at 9:30am." > test-doc.txt
    aws s3 cp test-doc.txt s3://<DataBucketName-output>/

    aws bedrock-agentcore invoke-agent-runtime \
        --agent-runtime-arn <RuntimeArn-output> \
        --payload "$(echo -n '{"prompt":"When is standup?"}' | base64)" \
        --region eu-west-2 \
        outfile.json

Teardown:
    cdk destroy --all --app "python examples/agent_with_kbase.py"
"""

import aws_cdk as cdk

from gds_idea_cdk_constructs import DeploymentConfig
from gds_idea_cdk_constructs.agent_core import (
    AgentCore,
    AgentCoreProperties,
    KnowledgeBaseConfig,
)
from gds_idea_cdk_constructs.knowledge_base import KnowledgeBase

app = cdk.App()
cdk_env = cdk.Environment(account="992382722318", region="eu-west-2")
config = DeploymentConfig(cdk_env)

# --- Knowledge Base (all defaults: Titan V2, S3 Vectors, no chunking, auto-sync) ---
kb = KnowledgeBase(app, deployment_config=config, app_config="my-agent-kb1")

# --- AgentCore Runtime (BuiltInAgent default + KB attached) ---
agent = AgentCore(
    app,
    "MyAgentStack",
    props=AgentCoreProperties(
        runtime_name="my_kb_agent",
        knowledge_base=KnowledgeBaseConfig(knowledge_base=kb),
    ),
    env=cdk_env,
)

app.synth()


# =============================================================================
# Alternative: CustomAgent with tuned KB retrieval
# =============================================================================
# Use CustomAgent when you bring your own agent code directory.
# KnowledgeBaseConfig works the same way — it injects KB env vars and grants
# bedrock:Retrieve to the runtime role regardless of agent type.
#
# from gds_idea_cdk_constructs.agent_core import CustomAgent
# from gds_idea_cdk_constructs.knowledge_base import (
#     ChunkingConfig,
#     KnowledgeBaseProps,
# )
#
# kb = KnowledgeBase(
#     app,
#     deployment_config=config,
#     app_config="my-agent-kb1",
#     kb_props=KnowledgeBaseProps(
#         chunking=ChunkingConfig.semantic(max_tokens=400),
#         retain_on_delete=False,
#     ),
# )
#
# agent = AgentCore(
#     app,
#     "MyAgentStack",
#     props=AgentCoreProperties(
#         runtime_name="my_kb_agent",
#         agent=CustomAgent(
#             agent_code_directory="path/to/my_agent/",
#             environment_variables={"MY_CUSTOM_VAR": "value"},
#         ),
#         knowledge_base=KnowledgeBaseConfig(
#             knowledge_base=kb,
#             min_score=0.7,
#             enable_metadata=True,
#         ),
#     ),
#     env=cdk_env,
# )
#
# app.synth()
