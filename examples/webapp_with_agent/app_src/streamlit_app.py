"""Minimal Streamlit app demonstrating AgentCore runtime integration.

This app shows how to call a deployed AgentCore runtime from a web application.
The AGENTCORE_RUNTIME_ARN environment variable is the contract between
infrastructure and application code:

- Locally: set via docker-compose.yml (from the RuntimeArn CDK output)
- In production: injected by CDK via agent.environment_variables passed to
  WebAppContainerProperties
"""

import json
import os
import uuid

import boto3
import streamlit as st

# --- Configuration from environment ---
RUNTIME_ARN = os.environ.get("AGENTCORE_RUNTIME_ARN", "")
REGION = os.environ.get("AWS_DEFAULT_REGION", "eu-west-2")

st.title("AgentCore Chat")

if not RUNTIME_ARN:
    st.warning(
        "AGENTCORE_RUNTIME_ARN is not set. "
        "Deploy an AgentCore runtime (see examples/agent_with_kbase.py) "
        "and set the env var in .devcontainer/docker-compose.yml."
    )
    st.stop()

# Session ID for conversation continuity (AgentCore Memory)
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

prompt = st.text_input("Ask a question:")

if prompt:
    client = boto3.client("bedrock-agentcore", region_name=REGION)

    payload = json.dumps(
        {
            "prompt": prompt,
            "session_id": st.session_state.session_id,
        }
    )

    response = client.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        payload=payload.encode(),
    )

    # Read the streaming response (Server-Sent Events)
    body = response["response"].read().decode("utf-8", errors="replace")

    # Parse SSE events — extract text chunks and assemble the response
    output = ""
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            event = json.loads(line[6:])  # strip "data: " prefix
            if event.get("type") == "text":
                output += event.get("data", "")
            elif event.get("type") == "done":
                # Use full response from "done" if no text chunks were received
                if not output:
                    output = event.get("response", "")
        except json.JSONDecodeError:
            continue

    st.write(output)
