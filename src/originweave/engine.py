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

import asyncio
import contextlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .blackboard import BlackboardError, Board, Evidence, Fact, Intent
from .capabilities.base import CapabilityError, PromptProvider, PromptTemplate, SearchProvider
from .capabilities.worker import TaskKind, Worker, WorkerReply
from .events import Event, now_iso
from .reduce import reduce
from .store import RunStore

# Default worker label for the serial passes (Bootstrap/Reason/Validate). Dispatch
# hands each concurrent Explore pass a distinct ``worker-{n}`` label instead.
WORKER_ID = "worker-1"

# Bootstrap has no Intent of its own in the protocol; it is modelled as an ``explore``
# Intent so the pass is auditable and dispatchable like any other.
BOOTSTRAP_QUESTION = "Extract document A's core abstract claim(s) (Bootstrap)."

# HITL gate identifiers (frozen in proto/...:303-309): Gate A confirms the core claim.
GATE_A = "confirm-claim"

# Human-readable id prefix per Fact.kind, so replayed ids read as f1/c1/s1/... .
_PREFIX: dict[str, str] = {
    "fact": "f",
    "citation": "c",
    "source": "s",
    "boundary": "b",
    "compare": "p",
    "deviation": "d",
}

# Intent types the dispatcher can execute in this slice. A "verify" Intent needs the
# compare capability (M2), so it stays open until then instead of failing the run.
DISPATCHABLE_TYPES: tuple[str, ...] = ("explore", "decompose")

# What an "explore" Intent may produce (blackboard-protocol.md section 2.2): it chases
# citations/sources. "decompose" yields sub-claims, checked separately via Fact.role.
_EXPLORE_FACT_KINDS: frozenset[str] = frozenset({"citation", "source"})


class EngineError(ValueError):
    """Raised when a worker reply or engine input is malformed."""


class _ExploreTimeout(Exception):
    """A Worker call exceeded ``[worker].heartbeat_timeout`` (I4)."""


@dataclass
class WorkerResult:
    """Parsed worker reply; ids are placeholders until the engine assigns them.

    Bootstrap writes ``facts``; Reason writes ``intents`` (and may set ``complete``);
    Explore writes the facts behind one Intent.
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


def _session_suffix(session_id: str) -> int:
    """Return the numeric part of a ``"sess_007"`` id (0 when it is not one)."""
    _, _, digits = session_id.partition("_")
    return int(digits) if digits.isdigit() else 0


@dataclass
class _ExploreOutcome:
    """Result of one concurrent Explore pass, before the engine commits it.

    Nothing here is written to the blackboard until :meth:`Engine._dispatch` folds
    every outcome back in Intent id order; that ordering is what keeps a concurrent
    round's Board deterministic. ``reply`` is ``None`` when the failure happened before
    (or without) a worker reply (e.g. a search provider error).
    """

    intent_id: str
    worker: str
    facts: list[Fact] = field(default_factory=list)
    reply: WorkerReply | None = None
    session_id: str = ""
    started: str = ""
    ended: str = ""
    error: Exception | None = None


class Engine:
    """Drive the OODA loop for one run, writing events to ``store``.

    OODA (``docs/overview/blackboard-protocol.md`` section 4.1):

    - Observe    -- fold the event log into the current board (``reduce``).
    - Orient     -- the worker reads that board; the directive frames the situation.
    - Decide     -- the directive picks the move: Bootstrap writes claims, Reason
                    (later) writes intents, Explore claims and executes one.
    - Act        -- call the worker (``Worker.run``) in a fresh isolated session.
    - Write back -- append ``INTENT``/``EXECUTE``/``CONCLUDE`` events; the reducer then
                    derives the structural edges.

    Each turn is expressed as events, so the loop is replayable and the engine stays the
    sole writer of the blackboard. For a worked, number-by-number Bootstrap trace (the
    event log and the board it folds into), see ``blackboard-protocol.md`` section 4.4.
    """

    def __init__(
        self,
        *,
        worker: Worker,
        search: SearchProvider,
        prompt: PromptProvider,
        store: RunStore,
        max_concurrency: int = 1,
        heartbeat_interval: float = 15.0,
        heartbeat_timeout: float = 300.0,
        heartbeat_on_timeout: str = "release",
        auto: bool = False,
    ) -> None:
        if max_concurrency <= 0:
            raise ValueError(f"max_concurrency must be > 0, got {max_concurrency}")
        if heartbeat_interval <= 0:
            raise ValueError(f"heartbeat_interval must be > 0, got {heartbeat_interval}")
        if heartbeat_timeout <= heartbeat_interval:
            raise ValueError(
                "heartbeat_timeout must be > heartbeat_interval, "
                f"got {heartbeat_timeout} <= {heartbeat_interval}"
            )
        if heartbeat_on_timeout not in ("release", "fail"):
            raise ValueError(
                f"heartbeat_on_timeout must be 'release' or 'fail'; got {heartbeat_on_timeout!r}"
            )
        self._worker = worker
        # The engine picks the search provider (agent-design.md red line 4): Explore
        # passes call it and hand the results to the worker as context.
        self._search = search
        self._prompt = prompt
        self._store = store
        # Upper bound on Explore passes running at once in a dispatch round (I4).
        self._max_concurrency = max_concurrency
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_timeout = heartbeat_timeout
        self._heartbeat_on_timeout = heartbeat_on_timeout
        # HITL: when false the engine pauses at Gate A for human confirmation. The
        # product default ([hitl].auto=false) is passed by the server (M1c-1).
        self._auto = auto
        self._fact_seq: dict[str, int] = {}
        self._intent_seq = 0
        self._session_seq = 0

    @property
    def _worker_model(self) -> str:
        # Workers may expose ``.model``; the Worker protocol only promises ``.name``.
        return getattr(self._worker, "model", None) or self._worker.name

    async def _invoke(
        self,
        task: TaskKind,
        template: PromptTemplate,
        board: Board,
        *,
        extra: Mapping[str, Any] | None = None,
        session_id: str | None = None,
    ) -> tuple[WorkerReply, str, str, str]:
        """Run one worker task in a fresh session, timing it for the snapshot.

        The worker returns raw text plus its steps; parsing and all writes stay here
        so the engine remains the sole writer of the blackboard. The session id is
        allocated *before* the await when the caller did not reserve one, so ids follow
        submission order even under I4 concurrency (Validate records its snapshot before
        Reason, but its id is still allocated in invocation order).
        """
        if session_id is None:
            session_id = self._next_session_id()
        started = now_iso()
        reply = await self._worker.run(task, template, board, extra=extra)
        ended = now_iso()
        return reply, started, ended, session_id

    def _next_session_id(self) -> str:
        self._session_seq += 1
        return f"sess_{self._session_seq:03d}"

    def _worker_label(self, index: int) -> str:
        """Deterministic worker label for the ``index``-th pending Intent (1-based)."""
        return f"worker-{index + 1}"

    def _record_session(
        self,
        reply: WorkerReply,
        *,
        session_id: str,
        task: TaskKind,
        intent_id: str | None,
        started: str,
        ended: str,
        worker: str = WORKER_ID,
    ) -> None:
        """Persist one worker session: snapshot file first, then the event index.

        The snapshot holds the untruncated raw input/output and steps; the events are
        an index the UI/replay can group by worker. Neither event type affects the board.
        """
        session: dict[str, Any] = {
            "id": session_id,
            "runId": self._store.root.name,
            "worker": worker,
            "task": task,
            "model": self._worker_model,
            "input": reply.input,
            "output": reply.text,
            "steps": [step.to_session_dict() for step in reply.steps],
            "startedAt": started,
            "endedAt": ended,
        }
        if intent_id is not None:
            session["intentId"] = intent_id
        self._store.write_session(session_id, session)
        session_event: dict[str, Any] = {
            "sessionId": session_id,
            "task": task,
            "worker": worker,
            "ref": f"sessions/{session_id}.json",
        }
        if intent_id is not None:
            session_event["intentId"] = intent_id
        self._store.append_event("SESSION", session_event)
        for step in reply.steps:
            payload: dict[str, Any] = {"sessionId": session_id, "worker": worker}
            payload.update(step.to_dict())
            if intent_id is not None:
                payload["intentId"] = intent_id
            self._store.append_event("WORKER_STEP", payload)

    def _fail(
        self,
        exc: Exception,
        *,
        reply: WorkerReply | None,
        session_id: str,
        task: TaskKind,
        intent_id: str | None,
        started: str,
        ended: str,
        worker: str = WORKER_ID,
    ) -> None:
        """Record the unusable reply as a session, then write the terminal ``FAILED``.

        A bad reply / template failure ends the run on the board rather than raising,
        so the failure stays replayable; the raw reply lives in the session snapshot.
        When the failure happened before a reply (e.g. a search provider error) there is
        no session to keep, so only ``FAILED`` is written.
        """
        if reply is not None:
            self._record_session(
                reply,
                session_id=session_id,
                task=task,
                intent_id=intent_id,
                started=started,
                ended=ended,
                worker=worker,
            )
        self._store.append_event("FAILED", {"reason": str(exc)})

    async def run(self, *, origin: Fact, goal: Fact, auto: bool | None = None) -> Board:
        """Start a run: ``PROJECT``, Bootstrap, then Reason + one dispatch round.

        When HITL is on (``auto`` false, the default) the run stops right after Bootstrap
        by writing ``REQUEST_HUMAN`` for **Gate A** and returns an ``awaiting_human``
        board; call :meth:`resume` with the human decision to continue. ``auto=True``
        (constructor or per-run override, wired from ``[hitl].auto``) skips the gate.

        Dispatch executes one round of every open Intent the engine can run (Explore
        passes run concurrently up to ``max_concurrency``, committed in id order); a
        multi-round Stigmergy convergence loop is a later slice.
        """
        self._fact_seq = {}
        self._intent_seq = 0
        self._session_seq = 0
        self._store.append_event("PROJECT", {"origin": origin.to_dict(), "goal": goal.to_dict()})
        await self._bootstrap()
        board = reduce(self._store.read_events())
        if board.status != "running":
            # Bootstrap failed / completed: never run Reason on a dead board.
            return board
        if not (self._auto if auto is None else auto):
            # Gate A: confirm the core abstract claim(s) before decomposing them. It fires
            # whenever HITL is on, even if Bootstrap found no claim, so the human is never
            # silently bypassed.
            claim_ids = [fact.id for fact in board.facts if fact.role == "main-claim"]
            question = "Confirm the core claim(s)"
            question += f": {', '.join(claim_ids)}" if claim_ids else " (none were extracted)"
            self._store.append_event(
                "REQUEST_HUMAN",
                {"gate": GATE_A, "question": question},
                message="Gate A: confirm the core claim(s)",
            )
            return reduce(self._store.read_events())
        return await self._continue()

    async def resume(
        self,
        *,
        decision: str,
        text: str = "",
        targets: Sequence[str] = (),
    ) -> Board:
        """Resolve a paused HITL gate and continue the run (programmatic resume).

        ``decision`` is ``approve`` / ``edit`` (both continue) or ``reject`` (the run
        stops as human-terminated, ``STOPPED``). ``edit`` is currently **record-only**:
        ``text`` / ``targets`` land in the ``HUMAN_INPUT`` payload, but changing a Fact
        needs a fact-supersession event the contract does not have yet, so the board is
        unchanged (``blackboard-protocol.md`` section 7). The board is the source of truth
        for where we paused, and the id counters are rebuilt from it, so resuming works
        even on a fresh ``Engine`` over the same run directory.
        """
        if decision not in ("approve", "edit", "reject"):
            raise EngineError(f"unknown decision {decision!r}; expected approve|edit|reject")
        events = self._store.read_events()
        board = reduce(events)
        if board.status != "awaiting_human" or board.waitingFor is None:
            raise EngineError("no human gate is awaiting input")
        gate = board.waitingFor.gate
        if gate != GATE_A:
            raise EngineError(f"unsupported gate {gate!r}")
        self._restore_counters(board, events)
        self._store.append_event(
            "HUMAN_INPUT",
            {
                "gate": gate,
                "decision": decision,
                "text": text,
                "targets": list(targets),
                "author": "human",
            },
            message=f"Gate A: {decision}",
        )
        if decision == "reject":
            self._store.append_event("STOPPED", {"reason": "Gate A rejected by human"})
            return reduce(self._store.read_events())
        return await self._continue()

    def _restore_counters(self, board: Board, events: Sequence[Event]) -> None:
        """Rebuild the deterministic id counters from an existing run (I5 resume).

        Fact and Intent ids are contiguous on the board, so counting reconstructs the next
        value. Session ids are allocated up-front but only recorded when a pass commits, so
        a gap is possible (a released/failed pass); the counter is restored from the **max
        numeric suffix** seen in ``SESSION`` events, not an event count, to avoid reusing a
        suffix. This lets resume continue without colliding on ``f1``/``i1``/``sess_001``
        when it runs on a fresh ``Engine``.
        """
        fact_seq: dict[str, int] = {}
        for fact in board.facts:
            prefix = _PREFIX.get(fact.kind, "f")
            fact_seq[prefix] = fact_seq.get(prefix, 0) + 1
        self._fact_seq = fact_seq
        self._intent_seq = len(board.intents)
        self._session_seq = max(
            (
                _session_suffix(str(event.payload.get("sessionId", "")))
                for event in events
                if event.type == "SESSION"
            ),
            default=0,
        )

    async def _continue(self) -> Board:
        """Run Reason and one dispatch round, stopping early on any terminal state."""
        await self._reason()
        board = reduce(self._store.read_events())
        if board.status != "running":
            # Reason failed / judged the goal met: nothing left to dispatch.
            return board
        await self._dispatch()
        # The board is always folded from the event log, never mutated in place.
        return reduce(self._store.read_events())

    async def _bootstrap(self) -> None:
        try:
            template = await self._prompt.get("bootstrap")
        except (CapabilityError, FileNotFoundError) as exc:
            # A missing template is a provider failure: terminal, on the board.
            self._store.append_event("FAILED", {"reason": str(exc)})
            return
        board = reduce(self._store.read_events())  # Observe: the current graph
        try:
            reply, started, ended, session_id = await self._invoke("Bootstrap", template, board)
        except CapabilityError as exc:
            # A worker/provider failure still ends the run loudly and terminal.
            self._store.append_event("FAILED", {"reason": str(exc)})
            return
        try:
            result = parse_result(reply.text)
        except EngineError as exc:
            # An unusable reply ends the run; keep the session for the audit.
            self._fail(
                exc,
                reply=reply,
                session_id=session_id,
                task="Bootstrap",
                intent_id=None,
                started=started,
                ended=ended,
            )
            return

        # Act / write back: record the task as an Intent, claim it, then conclude.
        intent = Intent(
            id=self._next_intent_id(),
            type="explore",
            from_="origin",
            question=BOOTSTRAP_QUESTION,
        )
        self._store.append_event("INTENT", {"intent": intent.to_dict()})
        self._store.append_event(
            "EXECUTE",
            {"intentId": intent.id, "worker": WORKER_ID, "model": self._worker_model},
        )
        # Worker replies carry no ids; assign deterministic ones before writing back.
        for fact in result.facts:
            fact.id = self._next_fact_id(fact.kind)
        self._store.append_event(
            "CONCLUDE",
            {"intentId": intent.id, "facts": [fact.to_dict() for fact in result.facts]},
        )
        self._record_session(
            reply,
            session_id=session_id,
            task="Bootstrap",
            intent_id=intent.id,
            started=started,
            ended=ended,
        )

    async def _reason(self) -> None:
        """Run one Reason pass, then Validate its candidates before writing them.

        Reason never produces facts (that is Explore's job), and every proposed Intent
        must point at an existing fact id or ``origin``. Validate decides which
        candidates are new; duplicates are still written, but as ``dropped`` Intents, so
        the "considered but not taken" branch stays auditable. Multi-round Stigmergy
        convergence is a later concern; this is a single pass.
        """
        try:
            template = await self._prompt.get("reason")
        except (CapabilityError, FileNotFoundError) as exc:
            # A missing template is a provider failure: terminal, on the board.
            self._store.append_event("FAILED", {"reason": str(exc)})
            return
        board = reduce(self._store.read_events())  # Observe: the current graph
        # The findings already on the board are what triggered this Reason pass.
        triggers = [fact.id for fact in board.facts]
        self._store.append_event(
            "REASON", {"phase": "start", "triggerFacts": triggers}, message="Reason: start"
        )
        try:
            reply, started, ended, session_id = await self._invoke("Reason", template, board)
        except CapabilityError as exc:
            # A worker/provider failure still ends the run loudly and terminal.
            self._store.append_event("FAILED", {"reason": str(exc)})
            return
        try:
            result = parse_result(reply.text)
            if result.facts:
                raise EngineError("Reason must not produce facts; that is Explore's job")
            if result.complete is not None and result.intents:
                raise EngineError("Reason reply must not carry both intents and complete")
            # An Intent may only hang off a finding or the origin anchor.
            known = {"origin"} | {fact.id for fact in board.facts}
            for candidate in result.intents:
                if candidate.from_ not in known:
                    raise EngineError(f"intent.from {candidate.from_!r} is not a known fact id")
        except EngineError as exc:
            # An unusable reply ends the run; keep the session for the audit. The reply
            # is written as FAILED rather than raised, so the board records the death.
            self._fail(
                exc,
                reply=reply,
                session_id=session_id,
                task="Reason",
                intent_id=None,
                started=started,
                ended=ended,
            )
            return
        if result.complete is not None:
            self._store.append_event(
                "REASON", {"phase": "end", "triggerFacts": triggers}, message="Reason: end"
            )
            self._record_session(
                reply,
                session_id=session_id,
                task="Reason",
                intent_id=None,
                started=started,
                ended=ended,
            )
            self._store.append_event("COMPLETE", {"verdict": result.complete})
            return

        decisions: list[IntentDecision] | None = None
        if result.intents:
            try:
                decisions = (await self._validate(result.intents, board)).decisions
            except (EngineError, CapabilityError, FileNotFoundError) as exc:
                # A validator we cannot run or trust ends the run rather than guessing.
                self._fail(
                    exc,
                    reply=reply,
                    session_id=session_id,
                    task="Reason",
                    intent_id=None,
                    started=started,
                    ended=ended,
                )
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
        self._record_session(
            reply,
            session_id=session_id,
            task="Reason",
            intent_id=None,
            started=started,
            ended=ended,
        )

    async def _dispatch(self) -> None:
        """Run one dispatch round: every open Intent the engine can execute.

        The round works on a snapshot of the board as Reason left it (multi-round
        Stigmergy convergence is a later slice); ``verify`` Intents stay open until M2
        wires the compare capability. Every pending Intent is claimed up front (id
        order), then the Explore passes run concurrently, bounded by ``max_concurrency``.
        Outcomes are committed back in id order, so the Board (fact ids and structural
        edges) is deterministic even though completion order is not; the round stops
        committing at the first hard failure.
        """
        board = reduce(self._store.read_events())
        pending = [
            intent
            for intent in board.intents
            if intent.status == "open" and intent.type in DISPATCHABLE_TYPES
        ]
        if not pending:
            return
        try:
            # Fetched once for the whole round; a missing template is a provider
            # failure, written before any Intent is claimed.
            template = await self._prompt.get("explore")
        except (CapabilityError, FileNotFoundError) as exc:
            self._store.append_event("FAILED", {"reason": str(exc)})
            return
        # Claim each Intent up front, in id order, with a deterministic worker label;
        # a later provider/worker failure is then auditable as "claimed, then ...".
        workers = [self._worker_label(index) for index in range(len(pending))]
        session_ids = [self._next_session_id() for _ in pending]
        for intent, worker in zip(pending, workers, strict=True):
            self._store.append_event(
                "EXECUTE",
                {"intentId": intent.id, "worker": worker, "model": self._worker_model},
            )
        semaphore = asyncio.Semaphore(self._max_concurrency)
        outcomes = await asyncio.gather(
            *(
                self._guarded_run_explore(intent, board, template, worker, session_id, semaphore)
                for intent, worker, session_id in zip(pending, workers, session_ids, strict=True)
            )
        )
        # Worker replies carry no ids; assign them at commit time, in id order, so the
        # resulting fact ids never depend on which Explore happened to finish first.
        for outcome in outcomes:
            if outcome.error is not None:
                if (
                    isinstance(outcome.error, _ExploreTimeout)
                    and self._heartbeat_on_timeout == "release"
                ):
                    # Lease expired: hand the Intent back to the board as ``open`` and
                    # keep committing the rest of the round (protocol section 8).
                    self._store.append_event(
                        "RELEASE",
                        {"intentId": outcome.intent_id, "reason": str(outcome.error)},
                    )
                    continue
                self._fail(
                    outcome.error,
                    reply=outcome.reply,
                    session_id=outcome.session_id,
                    task="Explore",
                    intent_id=outcome.intent_id,
                    started=outcome.started,
                    ended=outcome.ended,
                    worker=outcome.worker,
                )
                return
            for fact in outcome.facts:
                fact.id = self._next_fact_id(fact.kind)
            self._store.append_event(
                "CONCLUDE",
                {
                    "intentId": outcome.intent_id,
                    "facts": [fact.to_dict() for fact in outcome.facts],
                },
            )
            assert outcome.reply is not None  # a success outcome always carries a reply
            self._record_session(
                outcome.reply,
                session_id=outcome.session_id,
                task="Explore",
                intent_id=outcome.intent_id,
                started=outcome.started,
                ended=outcome.ended,
                worker=outcome.worker,
            )

    async def _guarded_run_explore(
        self,
        intent: Intent,
        board: Board,
        template: PromptTemplate,
        worker: str,
        session_id: str,
        semaphore: asyncio.Semaphore,
    ) -> _ExploreOutcome:
        """Run one Explore pass, turning any escaping exception into an outcome.

        A pass must never let an unexpected exception (a provider bug, an ``OSError``,
        ...) abort ``asyncio.gather`` and leave its siblings running after ``run()``
        returns -- that would write to the blackboard after the run is over. Whatever
        escapes becomes a committed terminal failure instead.
        """
        try:
            return await self._run_explore(intent, board, template, worker, session_id, semaphore)
        except Exception as exc:
            return _ExploreOutcome(intent_id=intent.id, worker=worker, error=exc)

    def _timeout_outcome(self, intent: Intent, worker: str) -> _ExploreOutcome:
        return _ExploreOutcome(
            intent_id=intent.id,
            worker=worker,
            error=_ExploreTimeout(
                f"intent {intent.id} exceeded heartbeat_timeout ({self._heartbeat_timeout:g}s)"
            ),
        )

    async def _run_explore(
        self,
        intent: Intent,
        board: Board,
        template: PromptTemplate,
        worker: str,
        session_id: str,
        semaphore: asyncio.Semaphore,
    ) -> _ExploreOutcome:
        """Execute one Intent without writing anything; return an outcome to commit.

        For an ``explore`` Intent the engine calls ``search`` with the intent's question
        and passes the results to the worker via ``extra``; the worker itself never
        touches providers. Every blackboard write happens later, in :meth:`_dispatch`.
        The heartbeat lease covers the whole pass (search included), so a hung search
        cannot hold a claimed Intent without a heartbeat or a timeout either.
        """
        async with semaphore:
            extra: dict[str, Any] = {
                "intent": {
                    "id": intent.id,
                    "type": intent.type,
                    "from": intent.from_,
                    "question": intent.question,
                }
            }
            heartbeat = asyncio.create_task(self._heartbeat(intent.id))
            try:
                if intent.type == "explore":
                    try:
                        # The query is the intent's auditable question (protocol 2.2).
                        extra["search"] = await asyncio.wait_for(
                            self._search.search(intent.question),
                            timeout=self._heartbeat_timeout,
                        )
                    except TimeoutError:
                        return self._timeout_outcome(intent, worker)
                    except CapabilityError as exc:
                        return _ExploreOutcome(intent_id=intent.id, worker=worker, error=exc)
                try:
                    reply, started, ended, _ = await asyncio.wait_for(
                        self._invoke(
                            "Explore", template, board, extra=extra, session_id=session_id
                        ),
                        timeout=self._heartbeat_timeout,
                    )
                except TimeoutError:
                    # The lease expired; the dispatcher decides release vs. fail.
                    return self._timeout_outcome(intent, worker)
                except CapabilityError as exc:
                    return _ExploreOutcome(intent_id=intent.id, worker=worker, error=exc)
            finally:
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat
            try:
                result = parse_result(reply.text)
                if result.intents:
                    raise EngineError("Explore must not produce intents; direction is Reason's job")
                if result.complete is not None:
                    raise EngineError("Explore must not judge completion; that is Reason's job")
                self._check_explored_facts(intent, result.facts)
            except EngineError as exc:
                # An unusable reply ends the run; keep the session for the audit.
                return _ExploreOutcome(
                    intent_id=intent.id,
                    worker=worker,
                    reply=reply,
                    session_id=session_id,
                    started=started,
                    ended=ended,
                    error=exc,
                )
            return _ExploreOutcome(
                intent_id=intent.id,
                worker=worker,
                facts=result.facts,
                reply=reply,
                session_id=session_id,
                started=started,
                ended=ended,
            )

    async def _heartbeat(self, intent_id: str) -> None:
        """Emit ``HEARTBEAT`` for one in-flight Intent until the caller cancels it (I4).

        The engine (the sole writer) is the one keeping the lease alive; a worker never
        heartbeats. If the call outlives ``heartbeat_timeout`` the caller cancels this
        task and the dispatcher commits ``RELEASE`` or ``FAILED``.
        """
        while True:
            await asyncio.sleep(self._heartbeat_interval)
            self._store.append_event(
                "HEARTBEAT", {"intentId": intent_id}, message=f"{intent_id} heartbeat"
            )

    def _check_explored_facts(self, intent: Intent, facts: list[Fact]) -> None:
        """Check a batch of produced facts against what the Intent type may yield."""
        for fact in facts:
            if intent.type == "decompose":
                if fact.kind != "fact" or fact.role != "sub-claim":
                    raise EngineError(
                        f"decompose intent {intent.id} must produce fact/sub-claim facts; "
                        f"got kind={fact.kind!r} role={fact.role!r}"
                    )
                continue
            if fact.kind not in _EXPLORE_FACT_KINDS:
                raise EngineError(
                    f"explore intent {intent.id} must produce "
                    f"{sorted(_EXPLORE_FACT_KINDS)} facts; got kind={fact.kind!r}"
                )
            if fact.role != "none":
                # A claiming role here would pollute the main-claim set Reason reacts to.
                raise EngineError(
                    f"explore intent {intent.id} must produce role=none facts; "
                    f"got {fact.label!r} with role={fact.role!r}"
                )
            if not fact.evidence:
                raise EngineError(
                    f"explore intent {intent.id}: {fact.kind} fact "
                    f"{fact.label!r} needs at least one evidence entry"
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
        reply, started, ended, session_id = await self._invoke(
            "Validate", template, board, extra={"candidates": candidate_payload}
        )
        known_intent_ids = {intent.id for intent in board.intents}
        result = parse_validation(reply.text, len(candidates), known_intent_ids)
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
        self._record_session(
            reply,
            session_id=session_id,
            task="Validate",
            intent_id=None,
            started=started,
            ended=ended,
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
    "DISPATCHABLE_TYPES",
    "GATE_A",
    "Engine",
    "EngineError",
    "IntentDecision",
    "ValidationResult",
    "WorkerResult",
    "parse_result",
    "parse_validation",
]
