# AgentCore runs arm64 only, but CI machines are often x86 with no emulator.
# So the image is built without running any arm64 code:
#   - the "deps" stage runs on the build machine's own CPU and downloads
#     ready-made arm64 wheels (nothing is compiled or run for arm64),
#   - the final arm64 stage only copies files in. It must have no RUN lines.

FROM --platform=$BUILDPLATFORM ghcr.io/astral-sh/uv:0.9-python3.13-bookworm-slim AS deps

WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-hashes --no-emit-project -o requirements.txt \
    && uv pip install --target /deps -r requirements.txt \
        --python-platform aarch64-manylinux_2_28 \
        --python-version 3.13 \
        --only-binary :all:

FROM python:3.13-slim

WORKDIR /app
ENV PYTHONPATH=/app/deps \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp

COPY --from=deps --chown=1000:1000 /deps /app/deps
COPY --chown=1000:1000 . .

USER 1000:1000

EXPOSE 8080

CMD ["python", "agent.py"]
