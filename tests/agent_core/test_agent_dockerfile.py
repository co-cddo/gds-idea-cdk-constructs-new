"""The agent template image must build on x86 machines with no arm64 emulator.

AgentCore only runs arm64 images. The final (arm64) stage of the template
Dockerfile may therefore only copy files in: a RUN line there would execute
arm64 code during the build, which fails on x86 CI runners.
"""

from pathlib import Path

from gds_idea_cdk_constructs.agent_core import DEFAULT_AGENT_CODE_DIR

DOCKERFILE = Path(DEFAULT_AGENT_CODE_DIR) / "Dockerfile"


def _instructions() -> list[str]:
    """Return the Dockerfile instructions, one per logical line."""
    text = DOCKERFILE.read_text().replace("\\\n", " ")
    lines = (line.strip() for line in text.splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def _final_stage() -> list[str]:
    instructions = _instructions()
    last_from = max(
        i for i, line in enumerate(instructions) if line.upper().startswith("FROM ")
    )
    return instructions[last_from:]


def test_final_stage_has_no_run_lines():
    runs = [line for line in _final_stage() if line.upper().startswith("RUN ")]
    assert runs == []


def test_earlier_stages_run_on_the_build_machine():
    froms = [line for line in _instructions() if line.upper().startswith("FROM ")]
    assert froms[:-1], "expected a separate stage to install dependencies"
    assert all("--platform=$BUILDPLATFORM" in line for line in froms[:-1])


def test_dependencies_are_installed_as_arm64_wheels_only():
    text = DOCKERFILE.read_text()
    assert "--python-platform aarch64-" in text
    assert "--only-binary :all:" in text
