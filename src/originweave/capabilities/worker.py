"""Worker capability: the task execution body behind the engine.

A *worker* receives a task directive, the current board and optional task-specific
input, executes one task, and returns **raw reply text** plus the execution steps.
It never writes the blackboard: the engine parses the reply, assigns ids and
appends events (see ``docs/overview/blackboard-protocol.md`` section 4.2). Providers
are interchangeable (``local`` = one ``model`` completion; ``pi`` = the Pi agent
runtime); orchestration stays provider-agnostic (``agent-design.md`` red line 4).

Each call is one **isolated session** (M6): concurrency and context never leak
between calls. ``WorkerReply.input``/``WorkerReply.text`` are the session's raw
input/output; the engine persists them under the run dir.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from ..blackboard import Board
from .base import PromptTemplate
from .model import ChatMessage, ModelProvider, Usage

# The directive issued to a worker for one turn. This is a different axis from
# blackboard.IntentType (decompose/explore/verify): an "Explore" task executes one
# Intent whose type may be any of them.
TaskKind = Literal["Bootstrap", "Reason", "Explore", "Validate"]

# Max characters kept for a WORKER_STEP event's ``text`` (events are an index; the
# full text lives in the session snapshot under ``sessions/``).
STEP_TEXT_LIMIT = 2000


@dataclass
class WorkerStep:
    """One turn/tool-level step of a worker session (M6)."""

    seq: int
    kind: str  # turn-start | tool-call | tool-result | message | turn-end
    name: str = ""
    text: str = ""
    ok: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        """Render the step for a ``WORKER_STEP`` event payload (text truncated)."""
        payload: dict[str, Any] = {"seq": self.seq, "kind": self.kind}
        if self.name:
            payload["name"] = self.name
        if self.text:
            payload["text"] = self.text[:STEP_TEXT_LIMIT]
        if self.ok is not None:
            payload["ok"] = self.ok
        return payload

    def to_session_dict(self) -> dict[str, Any]:
        """Render the full step for the session snapshot (text untruncated)."""
        payload: dict[str, Any] = {"seq": self.seq, "kind": self.kind}
        if self.name:
            payload["name"] = self.name
        if self.text:
            payload["text"] = self.text
        if self.ok is not None:
            payload["ok"] = self.ok
        return payload


@dataclass
class WorkerReply:
    """A worker's reply: raw text plus the raw input and steps for the session.

    ``usage`` carries token counts when the provider reports them (M3b; the Pi runtime
    does not surface usage yet, so it stays ``None`` there).
    """

    text: str
    input: dict[str, Any] = field(default_factory=dict)
    steps: list[WorkerStep] = field(default_factory=list)
    usage: Usage | None = None


@runtime_checkable
class Worker(Protocol):
    name: str
    # Implementations may expose ``tools: frozenset[str]``; the engine reads it
    # (via getattr) to decide whether the worker searches itself via the ``search``
    # tool or the engine prefetches results into ``extra``.

    async def run(
        self,
        task: TaskKind,
        template: PromptTemplate,
        board: Board,
        *,
        extra: Mapping[str, Any] | None = None,
    ) -> WorkerReply:
        """Execute one task in a fresh session and return its raw reply."""
        ...


def board_payload(board: Board) -> dict[str, Any]:
    """Render the board slice a worker observes (the Observe step).

    ``decisions`` carries the human Gate rulings (Gate A/B) so a resumed worker can see
    the arbitration it must honour; ``waitingFor`` is omitted because a worker only runs
    when no gate is pending.
    """
    return {
        "origin": board.origin.to_dict(),
        "goal": board.goal.to_dict(),
        "facts": [fact.to_dict() for fact in board.facts],
        "intents": [intent.to_dict() for intent in board.intents],
        "hints": [hint.to_dict() for hint in board.hints],
        "decisions": [decision.to_dict() for decision in board.decisions],
    }


def render_messages(
    task: TaskKind,
    template: PromptTemplate,
    board: Board,
    *,
    extra: Mapping[str, Any] | None = None,
) -> list[ChatMessage]:
    """Build worker messages: the directive (system) plus the board graph (user).

    ``extra`` carries task-specific input that is not yet on the board (e.g. the
    candidate Intents handed to Validate).
    """
    payload: dict[str, Any] = {"task": task, "board": board_payload(board)}
    if extra:
        payload.update(extra)
    # sort_keys keeps the rendered input byte-stable, so prompts are reproducible.
    digest = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)
    return [
        ChatMessage(role="system", content=template.text),
        ChatMessage(role="user", content=digest),
    ]


class LocalWorker:
    """Single-turn worker: one ``model`` completion, no tools (M1 behavior)."""

    name = "local"
    # No tools: the engine does retrieval and injects it (see Engine._worker_self_search).
    tools: frozenset[str] = frozenset()

    def __init__(self, *, model: ModelProvider) -> None:
        self._model = model

    @property
    def model(self) -> str:
        # OpenAIModel exposes ``.model``; the ModelProvider protocol only promises ``.name``.
        return getattr(self._model, "model", None) or self._model.name

    async def run(
        self,
        task: TaskKind,
        template: PromptTemplate,
        board: Board,
        *,
        extra: Mapping[str, Any] | None = None,
    ) -> WorkerReply:
        messages = render_messages(task, template, board, extra=extra)
        text = await self._model.complete(messages)
        # ModelResult (a str subclass) may carry usage; plain-str providers do not.
        usage = getattr(text, "usage", None)
        return WorkerReply(
            text=text,
            input={"system": messages[0].content, "user": messages[1].content},
            usage=usage if isinstance(usage, Usage) else None,
        )


__all__ = [
    "STEP_TEXT_LIMIT",
    "LocalWorker",
    "TaskKind",
    "Worker",
    "WorkerReply",
    "WorkerStep",
    "board_payload",
    "render_messages",
]
