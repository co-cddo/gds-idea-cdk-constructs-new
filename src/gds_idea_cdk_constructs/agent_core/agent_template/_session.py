"""Reuses one agent across the turns of a conversation.

Has no Strands or AWS imports: the agent and history loader are injected.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, Generic, Protocol, TypeVar

logger = logging.getLogger("agent")


class _Agent(Protocol):
    messages: list[dict[str, Any]]

    def cleanup(self) -> None: ...


# TypeVar, not `class AgentSession[T]`: tests load this file on Python 3.11.
AgentT = TypeVar("AgentT", bound=_Agent)


class AgentSession(Generic[AgentT]):  # noqa: UP046 (see above)
    """Holds the agent for the conversation this container is serving.

    The agent is built on the first turn and reused until the ``session_id``
    changes or a turn fails. Turns run one at a time.

    Args:
        build_agent: Creates an agent from prior messages. Blocking, so it runs
            in a worker thread.
        load_history: Loads saved messages for a conversation. Blocking, so it
            runs in a worker thread.
        max_age_seconds: If set, an agent older than this is rebuilt with its
            current messages on the next turn, e.g. to renew connections.
        refresh_retry_seconds: After a failed refresh, how long to keep the
            current agent before trying again, so an unreachable gateway does
            not delay every turn. Also the shortest gap between two refreshes
            triggered by ``connection_lost``.
        connection_lost: Called after each successful turn with the messages
            that turn added. If it returns True, the agent is rebuilt on the
            next turn, because its tool connections look broken.
        clock: Returns the current time in seconds. Replaceable for tests.
    """

    def __init__(
        self,
        build_agent: Callable[[list[dict[str, Any]]], AgentT],
        load_history: Callable[[str], list[dict[str, Any]]],
        max_age_seconds: float | None = None,
        refresh_retry_seconds: float = 60.0,
        connection_lost: Callable[[list[dict[str, Any]]], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._build_agent = build_agent
        self._load_history = load_history
        self._max_age_seconds = max_age_seconds
        self._refresh_retry_seconds = refresh_retry_seconds
        self._connection_lost = connection_lost
        self._clock = clock
        self._lock = asyncio.Lock()
        self._agent: AgentT | None = None
        self._session_id: str | None = None
        self._built_at = 0.0
        self._no_refresh_before = 0.0
        self._needs_refresh = False

    @asynccontextmanager
    async def turn(self, session_id: str) -> AsyncIterator[AgentT]:
        """Wait for any turn in progress, then yield the agent for ``session_id``.

        The agent is discarded if the block raises or is cancelled, since its
        messages may be half-written.
        """
        async with self._lock:
            agent = await self._agent_for(session_id)
            # Hold the messages themselves, so ids cannot be reused while we
            # compare. Ids, not positions: Strands may trim old messages.
            before = list(agent.messages)
            seen = {id(message) for message in before}
            try:
                yield agent
            except BaseException:
                logger.info(
                    "Discarding agent after failed turn | Session=%s", session_id
                )
                self._discard()
                raise
            self._check_connections(
                [m for m in agent.messages if id(m) not in seen], session_id
            )

    async def _agent_for(self, session_id: str) -> AgentT:
        if self._agent is not None and self._session_id == session_id:
            if self._is_expired():
                await self._refresh()
            return self._agent

        self._discard()
        history = await asyncio.to_thread(self._load_history, session_id)
        logger.info(
            "Building agent | Session=%s | History=%d", session_id, len(history)
        )
        self._agent = await asyncio.to_thread(self._build_agent, history)
        self._session_id = session_id
        self._built_at = self._clock()
        self._no_refresh_before = 0.0
        return self._agent

    def _check_connections(
        self, new_messages: list[dict[str, Any]], session_id: str
    ) -> None:
        if self._connection_lost is None or not self._connection_lost(new_messages):
            return
        logger.warning(
            "Tool connection looks broken; agent will be rebuilt on the next "
            "turn | Session=%s",
            session_id,
        )
        self._needs_refresh = True

    def _is_expired(self) -> bool:
        now = self._clock()
        if now < self._no_refresh_before:
            return False
        if self._needs_refresh:
            return True
        if self._max_age_seconds is None:
            return False
        return now - self._built_at >= self._max_age_seconds

    async def _refresh(self) -> None:
        """Rebuild the agent with its current messages.

        If the rebuild fails, the old agent is kept and the refresh is retried
        after ``refresh_retry_seconds``.
        """
        old = self._agent
        logger.info("Refreshing agent | Session=%s", self._session_id)
        try:
            new = await asyncio.to_thread(self._build_agent, list(old.messages))
        except Exception:
            logger.exception("Refreshing agent failed; keeping the current one")
            self._no_refresh_before = self._clock() + self._refresh_retry_seconds
            return
        self._agent, self._built_at = new, self._clock()
        # After a refresh triggered by a broken connection, wait before allowing
        # another, so a tool that always errors cannot cause a rebuild per turn.
        self._no_refresh_before = (
            self._clock() + self._refresh_retry_seconds if self._needs_refresh else 0.0
        )
        self._needs_refresh = False
        _cleanup(old)

    def _discard(self) -> None:
        agent, self._agent, self._session_id = self._agent, None, None
        self._needs_refresh = False
        if agent is not None:
            _cleanup(agent)


def _cleanup(agent: _Agent) -> None:
    try:
        agent.cleanup()
    except Exception:
        logger.exception("Error cleaning up agent")
