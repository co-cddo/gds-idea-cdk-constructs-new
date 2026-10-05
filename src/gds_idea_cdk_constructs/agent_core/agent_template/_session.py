"""Reuses one agent across the turns of a conversation.

Has no Strands or AWS imports: the agent and history loader are injected.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, Protocol

logger = logging.getLogger("agent")


class _Disposable(Protocol):
    def cleanup(self) -> None: ...


class AgentSession[AgentT: _Disposable]:
    """Holds the agent for the conversation this container is serving.

    The agent is built on the first turn and reused until the ``session_id``
    changes or a turn fails. Turns run one at a time.

    Args:
        build_agent: Creates an agent from prior messages.
        load_history: Loads saved messages for a conversation. Blocking, so it
            runs in a worker thread.
    """

    def __init__(
        self,
        build_agent: Callable[[list[dict[str, Any]]], AgentT],
        load_history: Callable[[str], list[dict[str, Any]]],
    ) -> None:
        self._build_agent = build_agent
        self._load_history = load_history
        self._lock = asyncio.Lock()
        self._agent: AgentT | None = None
        self._session_id: str | None = None

    @asynccontextmanager
    async def turn(self, session_id: str) -> AsyncIterator[AgentT]:
        """Wait for any turn in progress, then yield the agent for ``session_id``.

        The agent is discarded if the block raises or is cancelled, since its
        messages may be half-written.
        """
        async with self._lock:
            agent = await self._agent_for(session_id)
            try:
                yield agent
            except BaseException:
                logger.info(
                    "Discarding agent after failed turn | Session=%s", session_id
                )
                self._discard()
                raise

    async def _agent_for(self, session_id: str) -> AgentT:
        if self._agent is not None and self._session_id == session_id:
            return self._agent

        self._discard()
        history = await asyncio.to_thread(self._load_history, session_id)
        logger.info(
            "Building agent | Session=%s | History=%d", session_id, len(history)
        )
        self._agent = self._build_agent(history)
        self._session_id = session_id
        return self._agent

    def _discard(self) -> None:
        agent, self._agent, self._session_id = self._agent, None, None
        if agent is None:
            return
        try:
            agent.cleanup()
        except Exception:
            logger.exception("Error cleaning up agent")
