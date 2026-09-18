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
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from .blackboard import BlackboardError, Board, Evidence, Fact, Intent
from .capabilities.base import CapabilityError, PromptProvider, PromptTemplate, SearchProvider
from .capabilities.model import ChatMessage, ModelProvider
from .reduce import reduce
from .store import RunStore

# The directive issued to a worker for one turn. This is a different axis from
# blackboard.IntentType (decompose/explore/verify): an "Explore" task executes one
# Intent whose type may be any of them.
TaskKind = Literal["Bootstrap", "Reason", "Explore", "Validate"]

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


@dataclass
class IntentDecision:
    """Validate's verdict for one candidate Intent, addressed by its index."""

    index: int
    drop: bool
    duplicate_of: str | None = None
    reason: str = ""


@dataclass
class ValidationResult:
    """Validate's decisions, one per candidate, in candidate order."""

    decisions: list[IntentDecision]

    @property
    def kept(self) -> int:
        return sum(1 for decision in self.decisions if not decision.drop)

    @property
    def dropped(self) -> int:
        return sum(1 for decision in self.decisions if decision.drop)


def parse_validation(text: str, count: int, known_intent_ids: set[str]) -> ValidationResult:
    """Parse Validate's strict-JSON reply and check it classifies every candidate once.

    ``count`` is the number of candidates; ``known_intent_ids`` bounds what a drop may
    reference. Malformed or incomplete replies raise :class:`EngineError`.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EngineError(f"validate reply is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise EngineError("validate reply must be a JSON object")
    raw_keep = data.get("keep", [])
    raw_drop = data.get("drop", [])
    if not isinstance(raw_keep, list):
        raise EngineError("'keep' must be a list")
    if not isinstance(raw_drop, list):
        raise EngineError("'drop' must be a list")

    decisions: dict[int, IntentDecision] = {}
    for raw in raw_keep:
        index = _candidate_index(raw, "keep")
        _claim_index(decisions, index)
        decisions[index] = IntentDecision(index=index, drop=False)
    for raw in raw_drop:
        if not isinstance(raw, dict):
            raise EngineError("each drop entry must be a JSON object")
        index = _candidate_index(raw.get("index"), "drop.index")
        duplicate_of = raw.get("duplicateOf")
        if duplicate_of is not None and not isinstance(duplicate_of, str):
            raise EngineError("drop.duplicateOf must be a string")
        if duplicate_of is not None and duplicate_of not in known_intent_ids:
            raise EngineError(f"drop.duplicateOf {duplicate_of!r} is not a known intent id")
        reason = raw.get("reason", "")
        if not isinstance(reason, str):
            raise EngineError("drop.reason must be a string")
        _claim_index(decisions, index)
        decisions[index] = IntentDecision(
            index=index, drop=True, duplicate_of=duplicate_of, reason=reason
        )

    expected = set(range(count))
    if set(decisions) != expected:
        missing = sorted(expected - set(decisions))
        extra = sorted(set(decisions) - expected)
        raise EngineError(
            f"validate must classify every candidate once; missing={missing} extra={extra}"
        )
    return ValidationResult(decisions=[decisions[i] for i in range(count)])


def _candidate_index(raw: Any, where: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise EngineError(f"{where} must be an integer candidate index")
    return raw


def _claim_index(decisions: dict[int, IntentDecision], index: int) -> None:
    if index in decisions:
        raise EngineError(f"candidate {index} classified more than once")


def _board_payload(board: Board) -> dict[str, Any]:
    """Render the board slice a worker observes (the Observe step)."""
    return {
        "origin": board.origin.to_dict(),
        "goal": board.goal.to_dict(),
        "facts": [fact.to_dict() for fact in board.facts],
        "intents": [intent.to_dict() for intent in board.intents],
        "hints": [hint.to_dict() for hint in board.hints],
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
    payload: dict[str, Any] = {"task": task, "board": _board_payload(board)}
    if extra:
        payload.update(extra)
    # sort_keys keeps the rendered input byte-stable, so prompts are reproducible.
    digest = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)
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
        """Run one Reason pass, then Validate its candidates before writing them.

        Reason never produces facts (that is Explore's job), and every proposed Intent
        must point at an existing fact id or ``origin``. Validate decides which
        candidates are new; duplicates are still written, but as ``dropped`` Intents, so
        the "considered but not taken" branch stays auditable. Multi-round Stigmergy
        convergence is a later concern; this is a single pass.
        """
        template = await self._prompt.get("reason")
        board = reduce(self._store.read_events())  # Observe: the current graph
        # The findings already on the board are what triggered this Reason pass.
        triggers = [fact.id for fact in board.facts]
        self._store.append_event(
            "REASON", {"phase": "start", "triggerFacts": triggers}, message="Reason: start"
        )
        reply = await self._model.complete(render_messages("Reason", template, board))
        result = parse_result(reply)
        if result.facts:
            raise EngineError("Reason must not produce facts; that is Explore's job")
        if result.complete is not None:
            if result.intents:
                raise EngineError("Reason reply must not carry both intents and complete")
            self._store.append_event(
                "REASON", {"phase": "end", "triggerFacts": triggers}, message="Reason: end"
            )
            self._store.append_event("COMPLETE", {"verdict": result.complete})
            return
        # An Intent may only hang off a finding or the origin anchor.
        known = {"origin"} | {fact.id for fact in board.facts}
        for candidate in result.intents:
            if candidate.from_ not in known:
                raise EngineError(f"intent.from {candidate.from_!r} is not a known fact id")

        decisions: list[IntentDecision] | None = None
        if result.intents:
            try:
                decisions = (await self._validate(result.intents, board)).decisions
            except (EngineError, CapabilityError, FileNotFoundError) as exc:
                # A validator we cannot run or trust ends the run rather than guessing.
                self._store.append_event("FAILED", {"reason": str(exc)})
                return
        # The model's lifecycle fields are untrusted: rebuild each candidate as a fresh
        # open/dropped Intent so only the engine controls status/claim/heartbeat.
        for position, candidate in enumerate(result.intents):
            decision = decisions[position] if decisions is not None else None
            is_dropped = decision.drop if decision is not None else False
            intent = Intent(
                id=self._next_intent_id(),
                type=candidate.type,
                from_=candidate.from_,
                question=candidate.question,
                status="dropped" if is_dropped else "open",
                duplicateOf=decision.duplicate_of if decision is not None else None,
            )
            self._store.append_event("INTENT", {"intent": intent.to_dict()})
        self._store.append_event(
            "REASON", {"phase": "end", "triggerFacts": triggers}, message="Reason: end"
        )

    async def _validate(self, candidates: list[Intent], board: Board) -> ValidationResult:
        """Ask the Validate worker which candidate Intents are new; duplicates drop."""
        template = await self._prompt.get("validate")
        candidate_payload = [
            {"index": index, "type": c.type, "from": c.from_, "question": c.question}
            for index, c in enumerate(candidates)
        ]
        self._store.append_event(
            "VALIDATE",
            {"phase": "start", "candidates": len(candidates)},
            message="Validate: start",
        )
        reply = await self._model.complete(
            render_messages("Validate", template, board, extra={"candidates": candidate_payload})
        )
        known_intent_ids = {intent.id for intent in board.intents}
        result = parse_validation(reply, len(candidates), known_intent_ids)
        self._store.append_event(
            "VALIDATE",
            {
                "phase": "end",
                "candidates": len(candidates),
                "kept": result.kept,
                "dropped": result.dropped,
                "drops": [
                    {
                        "index": decision.index,
                        "duplicateOf": decision.duplicate_of,
                        "reason": decision.reason,
                    }
                    for decision in result.decisions
                    if decision.drop
                ],
            },
            message="Validate: end",
        )
        return result

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
    "IntentDecision",
    "TaskKind",
    "ValidationResult",
    "WorkerResult",
    "parse_result",
    "parse_validation",
    "render_messages",
]
