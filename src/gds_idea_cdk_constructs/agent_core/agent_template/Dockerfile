FROM ghcr.io/astral-sh/uv:0.9 AS uv

FROM python:3.13-slim

WORKDIR /app

COPY --from=uv /uv /usr/local/bin/uv

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 bedrock_agentcore \
    && chown -R bedrock_agentcore:bedrock_agentcore /app

COPY --chown=bedrock_agentcore:bedrock_agentcore pyproject.toml uv.lock* ./

USER bedrock_agentcore

RUN uv sync --frozen 2>/dev/null || uv sync

COPY --chown=bedrock_agentcore:bedrock_agentcore . .

EXPOSE 8080

CMD ["uv", "run", "python", "agent.py"]
