"""Library-layer OODA engine (in-process Dispatcher).

The engine is the **sole writer** of the blackboard protocol: it drives the loop and
appends events through :meth:`originweave.store.RunStore.append_event`. A worker sees
only the board plus a single task directive and returns a strict-JSON result (see
``docs/overview/blackboard-protocol.md`` section 4.2); the engine assigns ids and the
reducer derives the structural edges. The engine is not exposed via the CLI.

This is the M1/M1c-1 temporary form: container-per-run lands in M3, so the dispatcher
runs in-process here (``docs/overview/agent-design.md`` section 6).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from .blackboard import BlackboardError, Board, Evidence, Fact, Intent
from .capabilities.base import PromptProvider, PromptTemplate, SearchProvider
from .capabilities.model import ChatMessage, ModelProvider
from .reduce import reduce
from .store import RunStore

# The directive issued to a worker for one turn. This is a different axis from
# blackboard.IntentType (decompose/explore/verify): an "Explore" task executes one
# Intent whose type may be any of them.
TaskKind = Literal["Bootstrap", "Reason", "Explore"]

# Bootstrap has no Intent of its own in the protocol; it is modelled as an ``explore``
# Intent so the pass is auditable and dispatchable like any other.
BOOTSTRAP_QUESTION = "Extract document A's core abstract claim(s) (Bootstrap)."

# Human-readable id prefix per Fact.kind, so replayed ids read as f1/c1/s1/... .
_PREFIX: dict[str, str] = {
    "fact": "f",
    "citation": "c",
    "source": "s",
    "boundary": "b",
    "compare": "p",
    "deviation": "d",
}


class EngineError(ValueError):
    """Raised when a worker reply or engine input is malformed."""


@dataclass
class WorkerResult:
    """Parsed worker reply; ids are placeholders until the engine assigns them.

    Bootstrap writes ``facts``; Reason writes ``intents`` (and may set ``complete``);
    a later Explore writes the facts behind one Intent.
    """

    facts: list[Fact] = field(default_factory=list)
    intents: list[Intent] = field(default_factory=list)
    complete: str | None = None


def _parse_fact(item: Any, ev_seq: int) -> tuple[Fact, int]:
    if not isinstance(item, dict):
        raise EngineError("each fact must be a JSON object")
    raw_evidence = item.get("evidence", [])
    if not isinstance(raw_evidence, list):
        raise EngineError("fact.evidence must be a list")
    evidence: list[Evidence] = []
    # The worker omits evidence ids, so assign stable ones (ev1, ev2, ...) here.
    for entry in raw_evidence:
        if not isinstance(entry, dict):
            raise EngineError("each evidence entry must be a JSON object")
        ev_seq += 1
        try:
            evidence.append(Evidence.from_dict({**entry, "id": f"ev{ev_seq}"}))
        except BlackboardError as exc:
            raise EngineError(f"invalid evidence: {exc}") from exc
    # Fact.from_dict re-parses its own evidence, so drop the raw list first; the id
    # below is a placeholder that Engine replaces with a deterministic one.
    body = {key: value for key, value in item.items() if key != "evidence"}
    try:
        fact = Fact.from_dict({**body, "id": "?"})
    except BlackboardError as exc:
        raise EngineError(f"invalid fact: {exc}") from exc
    fact.evidence = evidence
    return fact, ev_seq


def _parse_intent(item: Any) -> Intent:
    if not isinstance(item, dict):
        raise EngineError("each intent must be a JSON object")
    try:
        return Intent.from_dict({**item, "id": "?"})
    except BlackboardError as exc:
        raise EngineError(f"invalid intent: {exc}") from exc


def parse_result(text: str) -> WorkerResult:
    """Parse a worker's strict-JSON reply into a :class:`WorkerResult`.

    The reply must be a single JSON object (no markdown fences) carrying ``facts``,
    ``intents`` and ``complete``; enum values are validated against the blackboard
    domains. Malformed replies raise :class:`EngineError`.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EngineError(f"worker reply is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise EngineError("worker reply must be a JSON object")
    raw_facts = data.get("facts", [])
    raw_intents = data.get("intents", [])
    if not isinstance(raw_facts, list):
        raise EngineError("'facts' must be a list")
    if not isinstance(raw_intents, list):
        raise EngineError("'intents' must be a list")

    facts: list[Fact] = []
    ev_seq = 0  # shared across facts so evidence ids stay unique within a reply
    for item in raw_facts:
        fact, ev_seq = _parse_fact(item, ev_seq)
        facts.append(fact)
    intents = [_parse_intent(item) for item in raw_intents]

    raw_complete = data.get("complete")
    complete: str | None = None
    if isinstance(raw_complete, dict):
        verdict = raw_complete.get("verdict", "")
        complete = verdict if isinstance(verdict, str) and verdict else None
    elif raw_complete is not None:
        raise EngineError("'complete' must be an object or null")

    return WorkerResult(facts=facts, intents=intents, complete=complete)


def _board_payload(board: Board) -> dict[str, Any]:
    """Render the board slice a worker observes (the Observe step)."""
    return {
        "origin": board.origin.to_dict(),
        "goal": board.goal.to_dict(),
        "facts": [fact.to_dict() for fact in board.facts],
        "intents": [intent.to_dict() for intent in board.intents],
        "hints": [hint.to_dict() for hint in board.hints],
    }


def render_messages(task: TaskKind, template: PromptTemplate, board: Board) -> list[ChatMessage]:
    """Build worker messages: the directive (system) plus the board graph (user)."""
    # sort_keys keeps the rendered board byte-stable, so prompts are reproducible.
    digest = json.dumps(
        {"task": task, "board": _board_payload(board)},
        sort_keys=True,
        ensure_ascii=False,
        indent=2,
    )
    return [
        ChatMessage(role="system", content=template.text),
        ChatMessage(role="user", content=digest),
    ]


class Engine:
    """Drive the OODA loop for one run, writing events to ``store``.

    OODA (``docs/overview/blackboard-protocol.md`` section 4.1):

    - Observe    -- fold the event log into the current board (``reduce``).
    - Orient     -- the worker reads that board; the directive frames the situation.
    - Decide     -- the directive picks the move: Bootstrap writes claims, Reason
                    (later) writes intents, Explore (later) claims one.
    - Act        -- call the capability (``model.complete``, later ``search.search``).
    - Write back -- append ``INTENT``/``EXECUTE``/``CONCLUDE`` events; the reducer then
                    derives the structural edges.

    Each turn is expressed as events, so the loop is replayable and the engine stays the
    sole writer of the blackboard. For a worked, number-by-number Bootstrap trace (the
    event log and the board it folds into), see ``blackboard-protocol.md`` section 4.4.
    """

    def __init__(
        self,
        *,
        model: ModelProvider,
        search: SearchProvider,
        prompt: PromptProvider,
        store: RunStore,
    ) -> None:
        self._model = model
        # search is not consumed until the Explore directive lands; wired now for parity.
        self._search = search
        self._prompt = prompt
        self._store = store
        self._fact_seq: dict[str, int] = {}
        self._intent_seq = 0

    async def run(self, *, origin: Fact, goal: Fact) -> Board:
        """Start a run: ``PROJECT``, one Bootstrap pass, one Reason pass, then reduce."""
        self._fact_seq = {}
        self._intent_seq = 0
        self._store.append_event("PROJECT", {"origin": origin.to_dict(), "goal": goal.to_dict()})
        await self._bootstrap()
        await self._reason()
        # The board is always folded from the event log, never mutated in place.
        return reduce(self._store.read_events())

    async def _bootstrap(self) -> None:
        template = await self._prompt.get("bootstrap")
        board = reduce(self._store.read_events())  # Observe: the current graph
        reply = await self._model.complete(render_messages("Bootstrap", template, board))
        result = parse_result(reply)

        # Act / write back: record the task as an Intent, claim it, then conclude.
        intent = Intent(
            id=self._next_intent_id(),
            type="explore",
            from_="origin",
            question=BOOTSTRAP_QUESTION,
        )
        self._store.append_event("INTENT", {"intent": intent.to_dict()})
        # OpenAIModel exposes ``.model``; the ModelProvider protocol only promises ``.name``.
        model_name = getattr(self._model, "model", None) or self._model.name
        self._store.append_event(
            "EXECUTE",
            {"intentId": intent.id, "worker": "worker-1", "model": model_name},
        )
        # Worker replies carry no ids; assign deterministic ones before writing back.
        for fact in result.facts:
            fact.id = self._next_fact_id(fact.kind)
        self._store.append_event(
            "CONCLUDE",
            {"intentId": intent.id, "facts": [fact.to_dict() for fact in result.facts]},
        )

    async def _reason(self) -> None:
        """Run one Reason pass: write candidate Intents, or ``COMPLETE`` if judged done.

        Reason never produces facts (that is Explore's job), and every proposed Intent
        must point at an existing fact id or ``origin``. Multi-round Stigmergy
        convergence is a later concern; this is a single pass.
        """
        template = await self._prompt.get("reason")
        board = reduce(self._store.read_events())  # Observe: the current graph
        self._store.append_event("REASON", {"phase": "start"}, message="Reason: start")
        reply = await self._model.complete(render_messages("Reason", template, board))
        result = parse_result(reply)
        if result.facts:
            raise EngineError("Reason must not produce facts; that is Explore's job")
        if result.complete is not None:
            if result.intents:
                raise EngineError("Reason reply must not carry both intents and complete")
            self._store.append_event("REASON", {"phase": "end"}, message="Reason: end")
            self._store.append_event("COMPLETE", {"verdict": result.complete})
            return
        # Validate the whole reply before writing anything, so a bad Intent leaves no
        # half-written intents behind. An Intent may only hang off a finding or origin.
        known = {"origin"} | {fact.id for fact in board.facts}
        for intent in result.intents:
            if intent.from_ not in known:
                raise EngineError(f"intent.from {intent.from_!r} is not a known fact id")
        # The model's lifecycle fields are untrusted: rebuild each Intent as a fresh
        # ``open`` candidate so only the engine controls status/claim/heartbeat.
        for intent in result.intents:
            candidate = Intent(
                id=self._next_intent_id(),
                type=intent.type,
                from_=intent.from_,
                question=intent.question,
            )
            self._store.append_event("INTENT", {"intent": candidate.to_dict()})
        self._store.append_event("REASON", {"phase": "end"}, message="Reason: end")

    def _next_intent_id(self) -> str:
        self._intent_seq += 1
        return f"i{self._intent_seq}"

    def _next_fact_id(self, kind: str) -> str:
        """Return the next deterministic id for ``kind`` (e.g. ``f1``, ``c2``)."""
        prefix = _PREFIX.get(kind, "f")
        self._fact_seq[prefix] = self._fact_seq.get(prefix, 0) + 1
        return f"{prefix}{self._fact_seq[prefix]}"


__all__ = [
    "BOOTSTRAP_QUESTION",
    "Engine",
    "EngineError",
    "TaskKind",
    "WorkerResult",
    "parse_result",
    "render_messages",
]
