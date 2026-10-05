"""Tests for how the built-in agent template reuses one agent per conversation.

The template is not an importable package (its modules import each other by
bare name), so ``_session.py`` is loaded by file path. It has no SDK imports.
"""

import asyncio
import importlib.util
import logging
import threading
from pathlib import Path

import pytest

from gds_idea_cdk_constructs.agent_core import DEFAULT_AGENT_CODE_DIR


def _load_session_module():
    spec = importlib.util.spec_from_file_location(
        "_session", Path(DEFAULT_AGENT_CODE_DIR) / "_session.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AgentSession = _load_session_module().AgentSession


class FakeAgent:
    def __init__(self, messages):
        self.messages = messages
        self.cleaned_up = False

    def cleanup(self):
        self.cleaned_up = True


@pytest.fixture
def built():
    """Every agent the session has built, in order."""
    return []


@pytest.fixture
def loaded():
    """Every session_id history was loaded for, in order."""
    return []


@pytest.fixture
def session(built, loaded):
    def build_agent(messages):
        agent = FakeAgent(messages)
        built.append(agent)
        return agent

    def load_history(session_id):
        loaded.append(session_id)
        return [{"role": "user", "content": f"history of {session_id}"}]

    return AgentSession(build_agent, load_history)


async def _run_turn(session, session_id):
    async with session.turn(session_id) as agent:
        return agent


# -- Reuse --


def test_first_turn_builds_agent_from_loaded_history(session, built, loaded):
    agent = asyncio.run(_run_turn(session, "s1"))
    assert loaded == ["s1"]
    assert built == [agent]
    assert agent.messages == [{"role": "user", "content": "history of s1"}]


def test_later_turns_in_same_session_reuse_the_agent(session, built, loaded):
    async def scenario():
        return [await _run_turn(session, "s1") for _ in range(3)]

    agents = asyncio.run(scenario())
    assert agents[0] is agents[1] is agents[2]
    assert len(built) == 1
    assert loaded == ["s1"]


def test_history_is_loaded_off_the_event_loop_thread():
    seen = {}

    def load_history(session_id):
        seen["thread"] = threading.get_ident()
        return []

    session = AgentSession(FakeAgent, load_history)
    asyncio.run(_run_turn(session, "s1"))
    assert seen["thread"] != threading.get_ident()


# -- New conversation --


def test_new_session_id_rebuilds_from_that_sessions_history(session, built, loaded):
    async def scenario():
        first = await _run_turn(session, "s1")
        second = await _run_turn(session, "s2")
        return first, second

    first, second = asyncio.run(scenario())
    assert first is not second
    assert loaded == ["s1", "s2"]
    assert second.messages == [{"role": "user", "content": "history of s2"}]


def test_new_session_id_cleans_up_the_previous_agent(session):
    async def scenario():
        first = await _run_turn(session, "s1")
        await _run_turn(session, "s2")
        return first

    assert asyncio.run(scenario()).cleaned_up is True


def test_returning_to_an_earlier_session_reloads_its_history(session, loaded):
    async def scenario():
        for session_id in ("s1", "s2", "s1"):
            await _run_turn(session, session_id)

    asyncio.run(scenario())
    assert loaded == ["s1", "s2", "s1"]


# -- Failed turns --


def test_failed_turn_discards_the_agent_and_reraises(session, built, loaded):
    async def scenario():
        with pytest.raises(RuntimeError, match="boom"):
            async with session.turn("s1"):
                raise RuntimeError("boom")
        return await _run_turn(session, "s1")

    retry_agent = asyncio.run(scenario())
    assert built[0].cleaned_up is True
    assert retry_agent is built[1]
    assert loaded == ["s1", "s1"]


def test_cancelled_turn_discards_the_agent(session, built):
    """Test that a client disconnecting mid-stream drops a half-written agent."""

    async def scenario():
        with pytest.raises(asyncio.CancelledError):
            async with session.turn("s1"):
                raise asyncio.CancelledError
        await _run_turn(session, "s1")

    asyncio.run(scenario())
    assert built[0].cleaned_up is True
    assert len(built) == 2


def test_failed_build_is_not_cached_and_releases_the_lock():
    attempts = []

    def build_agent(messages):
        attempts.append(1)
        if len(attempts) == 1:
            raise ConnectionError("gateway unreachable")
        return FakeAgent(messages)

    session = AgentSession(build_agent, lambda session_id: [])

    async def scenario():
        with pytest.raises(ConnectionError):
            await _run_turn(session, "s1")
        return await asyncio.wait_for(_run_turn(session, "s1"), timeout=1)

    assert isinstance(asyncio.run(scenario()), FakeAgent)
    assert len(attempts) == 2


def test_cleanup_error_is_logged_and_does_not_block_the_next_turn(caplog):
    class BadCleanupAgent(FakeAgent):
        def cleanup(self):
            raise OSError("close failed")

    session = AgentSession(BadCleanupAgent, lambda session_id: [])

    async def scenario():
        await _run_turn(session, "s1")
        return await _run_turn(session, "s2")

    with caplog.at_level(logging.ERROR, logger="agent"):
        agent = asyncio.run(scenario())
    assert isinstance(agent, BadCleanupAgent)
    assert "Error cleaning up agent" in caplog.text


# -- Concurrency --


def test_concurrent_turns_run_one_at_a_time(session):
    events = []

    async def turn(name):
        async with session.turn("s1"):
            events.append(f"{name} start")
            await asyncio.sleep(0.01)
            events.append(f"{name} end")

    async def scenario():
        await asyncio.gather(turn("a"), turn("b"), turn("c"))

    asyncio.run(scenario())
    assert events == [
        "a start",
        "a end",
        "b start",
        "b end",
        "c start",
        "c end",
    ]


def test_queued_turns_share_the_agent_built_by_the_first(session, built):
    async def scenario():
        return await asyncio.gather(*[_run_turn(session, "s1") for _ in range(3)])

    agents = asyncio.run(scenario())
    assert len(built) == 1
    assert all(a is built[0] for a in agents)


# -- Refresh (renewing gateway connections) --


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def aging_session(built, loaded, clock):
    def build_agent(messages):
        agent = FakeAgent(list(messages))
        built.append(agent)
        return agent

    def load_history(session_id):
        loaded.append(session_id)
        return [{"role": "user", "content": "saved"}]

    return AgentSession(build_agent, load_history, max_age_seconds=900, clock=clock)


def test_agent_is_reused_before_max_age(aging_session, built, clock):
    async def scenario():
        await _run_turn(aging_session, "s1")
        clock.now += 899
        return await _run_turn(aging_session, "s1")

    agent = asyncio.run(scenario())
    assert len(built) == 1
    assert agent is built[0]


def test_agent_is_rebuilt_after_max_age_keeping_its_messages(
    aging_session, built, loaded, clock
):
    async def scenario():
        first = await _run_turn(aging_session, "s1")
        first.messages.append({"role": "assistant", "content": "from this container"})
        clock.now += 900
        return first, await _run_turn(aging_session, "s1")

    first, second = asyncio.run(scenario())
    assert second is not first
    assert second.messages == first.messages
    assert len(second.messages) == 2  # the saved one plus the live one
    assert loaded == ["s1"]  # not reloaded from Memory


def test_refresh_cleans_up_the_old_agent(aging_session, clock):
    async def scenario():
        first = await _run_turn(aging_session, "s1")
        clock.now += 900
        await _run_turn(aging_session, "s1")
        return first

    assert asyncio.run(scenario()).cleaned_up is True


def test_refresh_restarts_the_clock(aging_session, built, clock):
    async def scenario():
        await _run_turn(aging_session, "s1")
        clock.now += 900
        await _run_turn(aging_session, "s1")  # refresh
        clock.now += 899
        await _run_turn(aging_session, "s1")  # too soon for another

    asyncio.run(scenario())
    assert len(built) == 2


def test_refresh_copies_messages_so_old_agent_cleanup_cannot_affect_new(
    aging_session, clock
):
    async def scenario():
        first = await _run_turn(aging_session, "s1")
        clock.now += 900
        second = await _run_turn(aging_session, "s1")
        return first, second

    first, second = asyncio.run(scenario())
    first.messages.clear()
    assert len(second.messages) == 1


def test_failed_refresh_keeps_the_old_agent_and_retries_next_turn(built, clock, caplog):
    attempts = []

    def build_agent(messages):
        attempts.append(1)
        if len(attempts) == 2:
            raise ConnectionError("gateway unreachable")
        agent = FakeAgent(list(messages))
        built.append(agent)
        return agent

    session = AgentSession(
        build_agent, lambda session_id: [], max_age_seconds=900, clock=clock
    )

    async def scenario():
        first = await _run_turn(session, "s1")
        clock.now += 900
        with caplog.at_level(logging.ERROR, logger="agent"):
            second = await _run_turn(session, "s1")  # refresh fails
        third = await _run_turn(session, "s1")  # retries
        return first, second, third

    first, second, third = asyncio.run(scenario())
    assert second is first
    assert first.cleaned_up is True  # only once the retry succeeds
    assert third is not first
    assert "Refreshing agent failed" in caplog.text


def test_failed_refresh_does_not_clean_up_the_old_agent():
    clock = FakeClock()
    attempts = []
    agents = []

    def build_agent(messages):
        attempts.append(1)
        if len(attempts) > 1:
            raise ConnectionError("gateway unreachable")
        agents.append(FakeAgent(messages))
        return agents[0]

    session = AgentSession(
        build_agent, lambda session_id: [], max_age_seconds=900, clock=clock
    )

    async def scenario():
        await _run_turn(session, "s1")
        clock.now += 900
        await _run_turn(session, "s1")

    asyncio.run(scenario())
    assert agents[0].cleaned_up is False


def test_no_refresh_without_max_age(built):
    """Test that agents without gateways are never rebuilt on a timer."""
    clock = FakeClock()
    no_limit = AgentSession(
        lambda messages: built.append(FakeAgent(messages)) or built[-1],
        lambda session_id: [],
        clock=clock,
    )

    async def scenario():
        await _run_turn(no_limit, "s1")
        clock.now += 10**9
        await _run_turn(no_limit, "s1")

    asyncio.run(scenario())
    assert len(built) == 1


def test_new_session_after_expiry_loads_history_instead_of_refreshing(
    aging_session, loaded, clock
):
    async def scenario():
        await _run_turn(aging_session, "s1")
        clock.now += 900
        await _run_turn(aging_session, "s2")

    asyncio.run(scenario())
    assert loaded == ["s1", "s2"]
