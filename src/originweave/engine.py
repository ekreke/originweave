"""Library-layer OODA engine (in-process Dispatcher).

The engine is the **sole writer** of the blackboard protocol: it drives the loop and
appends events through :meth:`originweave.store.RunStore.append_event`. A worker sees
only the board plus a single task directive and returns a strict-JSON result (see
``docs/overview/blackboard-protocol.md`` section 4.2); the engine assigns ids and the
reducer derives the structural edges. The engine is not exposed via the CLI.

The worker here runs in-process; container-per-worker (``[worker].execution=container``,
M3a) is the production form and swaps the Worker backend without changing the engine
(``docs/overview/agent-design.md`` section 6).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .blackboard import (
    BlackboardError,
    Board,
    Edge,
    Entity,
    EntityGraph,
    Evidence,
    Fact,
    Hint,
    Intent,
    Relation,
    canonical_name,
)
from .capabilities.base import CapabilityError, PromptProvider, PromptTemplate, SearchProvider
from .capabilities.model import Usage
from .capabilities.worker import TaskKind, Worker, WorkerReply
from .config import BudgetConfig, parse_duration
from .events import Event, now_iso
from .pricing import PricingTable
from .reduce import reduce
from .report import SEVERITY_STATUS, ReportError, derive_report, parse_severity, render_report
from .store import RunStore

# Default worker label for the serial passes (Bootstrap/Reason/Validate). Dispatch
# hands each concurrent Explore pass a distinct ``worker-{n}`` label instead.
WORKER_ID = "worker-1"

# Bootstrap has no Intent of its own in the protocol; it is modelled as an ``explore``
# Intent so the pass is auditable and dispatchable like any other.
BOOTSTRAP_QUESTION = "Extract document A's core abstract claim(s) (Bootstrap)."

# HITL gate identifiers (frozen in proto/...:303-309): Gate A confirms the core claim,
# Gate B (verify) arbitrates a source conflict (M2), Gate C (review) confirms the final
# scorecard before ``report.md`` is written (M3).
GATE_A = "confirm-claim"
GATE_B = "arbitrate"
GATE_C = "review"

# Human-facing label per gate id, used in HUMAN_INPUT event messages.
_GATE_LABELS: dict[str, str] = {GATE_A: "Gate A", GATE_B: "Gate B", GATE_C: "Gate C"}

# Human-readable id prefix per Fact.kind, so replayed ids read as f1/c1/s1/... .
_PREFIX: dict[str, str] = {
    "fact": "f",
    "citation": "c",
    "source": "s",
    "boundary": "b",
    "compare": "p",
    "deviation": "d",
}

# Intent types the dispatcher can execute. A "verify" Intent runs the compare pass
# (M2), which scores deviations rather than chasing sources; "extract"/"relate" drive
# the entity-relation graph (M5, only when the run's ``analysis`` includes relation).
DISPATCHABLE_TYPES: tuple[str, ...] = ("explore", "decompose", "verify", "extract", "relate")

# Intent types of the entity-relation analysis (M5). They are rejected in replies of a
# provenance-only run, and their completions commit ``ENTITY``/``RELATION`` events.
GRAPH_INTENT_TYPES: frozenset[str] = frozenset({"extract", "relate"})

# Whole-run analysis modes (proto ``CreateRunRequest.analysis``): provenance only,
# entity-relation graph only, or both. ``both`` completes only when both the provenance
# and the relation stop condition hold (TODO M5 decision).
ANALYSES: frozenset[str] = frozenset({"provenance", "relation", "both"})

# What an "explore" Intent may produce (blackboard-protocol.md section 2.2): it chases
# citations/sources. "decompose" yields sub-claims, checked separately via Fact.role.
_EXPLORE_FACT_KINDS: frozenset[str] = frozenset({"citation", "source"})


def _elapsed_seconds(start: str, end: str) -> float:
    """Seconds between two ISO timestamps (0.0 when either cannot be parsed).

    Timestamps may be tz-aware (``now_iso``) or naive (some fixtures); normalise before
    subtracting so a mixed pair never raises.
    """
    try:
        first = datetime.fromisoformat(start)
        last = datetime.fromisoformat(end)
        if first.tzinfo is None and last.tzinfo is not None:
            first = first.replace(tzinfo=last.tzinfo)
        elif last.tzinfo is None and first.tzinfo is not None:
            last = last.replace(tzinfo=first.tzinfo)
        return max(0.0, (last - first).total_seconds())
    except (ValueError, TypeError):
        return 0.0


# What a "verify" Intent must produce (M2): exactly one compare node plus 0..N deviations.
_COMPARE_KIND = "compare"
_DEVIATION_KIND = "deviation"
# Fact kinds a "verify" Intent may write; the compare node is checked separately.
_VERIFY_FACT_KINDS: frozenset[str] = frozenset({_COMPARE_KIND, _DEVIATION_KIND})

# Semantic edge relations a worker may carry in its reply (M2). Structural edges
# (spawns/resolves/decomposes) are derived by the reducer and must never be supplied
# (blackboard-protocol.md section 2.4).
SEMANTIC_RELATIONS: frozenset[str] = frozenset({"main-chain", "dependency", "goal-derived"})

# HITL gates a worker may request through its reply. Gate A and Gate C are engine-issued
# (after Bootstrap / on convergence), so only Gate B (arbitrate) is worker-requested (M2).
WORKER_GATES: frozenset[str] = frozenset({"arbitrate"})


class EngineError(ValueError):
    """Raised when a worker reply or engine input is malformed."""


class _ExploreTimeout(Exception):
    """A Worker call exceeded ``[worker].heartbeat_timeout`` (I4)."""


@dataclass
class WorkerResult:
    """Parsed worker reply; ids are placeholders until the engine assigns them.

    Bootstrap writes ``facts``; Reason writes ``intents`` (and may set ``complete``,
    plus an experiential ``hint`` when the run converges, M3); Explore writes the
    facts behind one Intent; an ``extract``/``relate`` pass (M5) writes the
    ``entities``/``relations`` it found. A reply may also carry semantic ``edges``
    (section 2.4) and, for a verify pass, a ``gate`` request (Gate B). ``fact_keys``
    maps a worker-local ``key`` to the index of the fact it names, so edges can
    reference facts from the same reply before real ids are assigned.
    """

    facts: list[Fact] = field(default_factory=list)
    intents: list[Intent] = field(default_factory=list)
    complete: str | None = None
    edges: list[dict[str, Any]] = field(default_factory=list)
    gate: dict[str, str] | None = None
    hint: str | None = None
    fact_keys: dict[str, int] = field(default_factory=dict)
    entities: list[Entity] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)


def _parse_fact(item: Any, ev_seq: int) -> tuple[Fact, int, str | None]:
    if not isinstance(item, dict):
        raise EngineError("each fact must be a JSON object")
    raw_key = item.get("key")
    key: str | None = None
    if raw_key is not None:
        if not isinstance(raw_key, str) or not raw_key:
            raise EngineError("fact.key must be a non-empty string")
        key = raw_key
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
    # Fact.from_dict re-parses its own evidence, so drop the raw list first; ``key`` is a
    # worker-local reference (not a Fact field) and is dropped too. The id below is a
    # placeholder that Engine replaces with a deterministic one.
    body = {k: v for k, v in item.items() if k not in ("evidence", "key")}
    try:
        fact = Fact.from_dict({**body, "id": "?"})
    except BlackboardError as exc:
        raise EngineError(f"invalid fact: {exc}") from exc
    fact.evidence = evidence
    return fact, ev_seq, key


def _parse_edge(item: Any) -> dict[str, Any]:
    """Parse one semantic edge from a worker reply (section 2.4).

    ``source``/``target`` may be an existing fact id or a ``key`` naming a fact from
    the same reply; they are resolved to real ids later by :func:`_resolve_edges`.
    """
    if not isinstance(item, dict):
        raise EngineError("each edge must be a JSON object")
    source = item.get("source")
    target = item.get("target")
    relation = item.get("relation")
    note = item.get("note", "")
    if not isinstance(source, str) or not source:
        raise EngineError("edge.source must be a non-empty string")
    if not isinstance(target, str) or not target:
        raise EngineError("edge.target must be a non-empty string")
    if relation not in SEMANTIC_RELATIONS:
        raise EngineError(
            f"edge.relation must be one of {sorted(SEMANTIC_RELATIONS)}; got {relation!r}"
        )
    if not isinstance(note, str):
        raise EngineError("edge.note must be a string")
    return {"source": source, "target": target, "relation": relation, "note": note}


def _parse_intent(item: Any) -> Intent:
    if not isinstance(item, dict):
        raise EngineError("each intent must be a JSON object")
    try:
        return Intent.from_dict({**item, "id": "?"})
    except BlackboardError as exc:
        raise EngineError(f"invalid intent: {exc}") from exc


def _parse_entity(item: Any, ev_seq: int) -> tuple[Entity, int]:
    """Parse one entity from an ``extract`` reply (M5).

    The worker does not know entity ids (the engine merges by canonical name and
    assigns ``n*`` ids), so the id is a placeholder. Evidence ids are assigned here
    (``ev<n>`` within the reply), mirroring ``_parse_fact``.
    """
    if not isinstance(item, dict):
        raise EngineError("each entity must be a JSON object")
    raw_evidence = item.get("evidence", [])
    if not isinstance(raw_evidence, list):
        raise EngineError("entity.evidence must be a list")
    evidence: list[Evidence] = []
    for entry in raw_evidence:
        if not isinstance(entry, dict):
            raise EngineError("each evidence entry must be a JSON object")
        ev_seq += 1
        try:
            evidence.append(Evidence.from_dict({**entry, "id": f"ev{ev_seq}"}))
        except BlackboardError as exc:
            raise EngineError(f"invalid evidence: {exc}") from exc
    body = {k: v for k, v in item.items() if k != "evidence"}
    try:
        entity = Entity.from_dict({**body, "id": "?"})
    except BlackboardError as exc:
        raise EngineError(f"invalid entity: {exc}") from exc
    entity.evidence = evidence
    return entity, ev_seq


def _parse_relation(item: Any, ev_seq: int) -> tuple[Relation, int]:
    """Parse one relation from a ``relate`` reply (M5).

    ``source``/``target`` must be entity ids the worker saw on the board; existence is
    checked at commit time (the parse step has no board). An ``inferred`` relation
    (no-source judgement) must carry a confidence in (0, 1] (protocol section 2.6).
    """
    if not isinstance(item, dict):
        raise EngineError("each relation must be a JSON object")
    raw_evidence = item.get("evidence", [])
    if not isinstance(raw_evidence, list):
        raise EngineError("relation.evidence must be a list")
    evidence: list[Evidence] = []
    for entry in raw_evidence:
        if not isinstance(entry, dict):
            raise EngineError("each evidence entry must be a JSON object")
        ev_seq += 1
        try:
            evidence.append(Evidence.from_dict({**entry, "id": f"ev{ev_seq}"}))
        except BlackboardError as exc:
            raise EngineError(f"invalid evidence: {exc}") from exc
    body = {k: v for k, v in item.items() if k != "evidence"}
    try:
        relation = Relation.from_dict({**body, "id": "?"})
    except BlackboardError as exc:
        raise EngineError(f"invalid relation: {exc}") from exc
    relation.evidence = evidence
    if relation.inferred and not 0.0 < relation.confidence <= 1.0:
        raise EngineError(
            f"relation {relation.source!r}->{relation.target!r} is inferred and must "
            "carry a confidence in (0, 1]"
        )
    if relation.status == "inferred" and not relation.inferred:
        # The frozen invariant is bidirectional (protocol section 2.6): a relation is
        # rendered dashed exactly when it is inferred.
        raise EngineError(
            f"relation {relation.source!r}->{relation.target!r} has status 'inferred' "
            "but inferred is false"
        )
    return relation, ev_seq


def parse_result(
    text: str,
    *,
    allow_edges: bool = False,
    allow_gate: bool = False,
    allow_hint: bool = False,
    allow_entities: bool = False,
    allow_relations: bool = False,
) -> WorkerResult:
    """Parse a worker's strict-JSON reply into a :class:`WorkerResult`.

    The reply must be a single JSON object (no markdown fences) carrying ``facts``,
    ``intents`` and ``complete``; enum values are validated against the blackboard
    domains. An Explore reply may additionally carry semantic ``edges`` (section 2.4)
    and a ``gate`` request (Gate B); a Reason reply may carry an experiential
    ``hint`` (M3, written only when the run converges); an ``extract``/``relate``
    pass (M5) may carry ``entities``/``relations``.
    ``allow_edges``/``allow_gate``/``allow_hint``/``allow_entities``/``allow_relations``
    bound which tasks may. Malformed replies raise :class:`EngineError`.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EngineError(f"worker reply is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise EngineError("worker reply must be a JSON object")
    raw_facts = data.get("facts", [])
    raw_intents = data.get("intents", [])
    raw_edges = data.get("edges", [])
    raw_entities = data.get("entities", [])
    raw_relations = data.get("relations", [])
    if not isinstance(raw_facts, list):
        raise EngineError("'facts' must be a list")
    if not isinstance(raw_intents, list):
        raise EngineError("'intents' must be a list")
    if not isinstance(raw_edges, list):
        raise EngineError("'edges' must be a list")
    if not isinstance(raw_entities, list):
        raise EngineError("'entities' must be a list")
    if not isinstance(raw_relations, list):
        raise EngineError("'relations' must be a list")

    facts: list[Fact] = []
    fact_keys: dict[str, int] = {}
    ev_seq = 0  # shared across facts so evidence ids stay unique within a reply
    for index, item in enumerate(raw_facts):
        fact, ev_seq, key = _parse_fact(item, ev_seq)
        if key is not None:
            if key in fact_keys:
                raise EngineError(f"duplicate fact.key {key!r}")
            fact_keys[key] = index
        facts.append(fact)
    intents = [_parse_intent(item) for item in raw_intents]
    entities: list[Entity] = []
    for item in raw_entities:
        entity, ev_seq = _parse_entity(item, ev_seq)
        entities.append(entity)
    relations: list[Relation] = []
    for item in raw_relations:
        relation, ev_seq = _parse_relation(item, ev_seq)
        relations.append(relation)

    raw_complete = data.get("complete")
    complete: str | None = None
    if isinstance(raw_complete, dict):
        verdict = raw_complete.get("verdict", "")
        complete = verdict if isinstance(verdict, str) and verdict else None
    elif raw_complete is not None:
        raise EngineError("'complete' must be an object or null")

    if raw_edges and not allow_edges:
        raise EngineError("this task must not carry 'edges'")
    edges = [_parse_edge(item) for item in raw_edges]

    if raw_entities and not allow_entities:
        raise EngineError("this task must not carry 'entities'")
    if raw_relations and not allow_relations:
        raise EngineError("this task must not carry 'relations'")

    raw_gate = data.get("gate")
    gate: dict[str, str] | None = None
    if raw_gate is not None:
        if not allow_gate:
            raise EngineError("this task must not carry 'gate'")
        if isinstance(raw_gate, str):
            # The prompt documents gate as an object, but the model sometimes emits the
            # bare name (``"gate": "arbitrate"``). The name is unambiguous (WORKER_GATES),
            # so normalise it instead of failing the whole run on a formatting lapse.
            raw_gate = {"gate": raw_gate, "question": ""}
        elif not isinstance(raw_gate, dict):
            raise EngineError("'gate' must be an object or a gate name string")
        gate_name = raw_gate.get("gate")
        question = raw_gate.get("question", "")
        if gate_name not in WORKER_GATES:
            raise EngineError(f"gate.gate must be one of {sorted(WORKER_GATES)}; got {gate_name!r}")
        if not isinstance(question, str):
            raise EngineError("gate.question must be a string")
        if complete is not None:
            raise EngineError("a reply must not carry both 'gate' and 'complete'")
        if intents:
            raise EngineError("a reply must not carry both 'gate' and 'intents'")
        gate = {"gate": gate_name, "question": question}

    raw_hint = data.get("hint")
    hint: str | None = None
    if raw_hint is not None:
        if not allow_hint:
            raise EngineError("this task must not carry 'hint'")
        if not isinstance(raw_hint, str) or not raw_hint.strip():
            raise EngineError("'hint' must be a non-empty string")
        hint = raw_hint

    return WorkerResult(
        facts=facts,
        intents=intents,
        complete=complete,
        edges=edges,
        gate=gate,
        hint=hint,
        fact_keys=fact_keys,
        entities=entities,
        relations=relations,
    )


def _resolve_edges(
    raw_edges: Sequence[Mapping[str, Any]],
    fact_ids: Sequence[str],
    key_to_id: Mapping[str, str],
    board: Board,
    *,
    intent_id: str,
) -> list[Edge]:
    """Turn a worker's raw semantic edges into :class:`Edge` objects with real ids.

    ``source``/``target`` resolve from a worker-local ``key`` (a fact in this reply) or
    an existing board fact id; anything else is a malformed reply. Self-loops are
    rejected. Ids are ``<intent>-e<position>``, deterministic for a given reply.
    """
    existing = {"origin", "goal"} | {fact.id for fact in board.facts}
    for key in key_to_id:
        if key in existing:
            raise EngineError(f"fact.key {key!r} shadows an existing fact id")
    known = existing | set(fact_ids)
    edges: list[Edge] = []
    for position, raw in enumerate(raw_edges):
        source = key_to_id.get(str(raw["source"]), str(raw["source"]))
        target = key_to_id.get(str(raw["target"]), str(raw["target"]))
        if source not in known:
            raise EngineError(f"edge.source {raw['source']!r} is not a known fact or key")
        if target not in known:
            raise EngineError(f"edge.target {raw['target']!r} is not a known fact or key")
        if source == target:
            raise EngineError(f"edge cannot be a self-loop on {source!r}")
        edges.append(
            Edge(
                id=f"{intent_id}-e{position + 1}",
                source=source,
                target=target,
                relation=str(raw["relation"]),
                note=str(raw["note"]),
            )
        )
    return edges


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
    if data.get("facts") or data.get("edges") or data.get("gate") is not None:
        # Validate classifies candidate Intents; facts/edges/gate belong to other tasks.
        raise EngineError("validate reply must carry only 'keep' and 'drop'")
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
    (or without) a worker reply (e.g. a search provider error). An ``extract``/
    ``relate`` pass (M5) carries ``entities``/``relations`` instead of ``facts``
    (``intent_type`` tells the commit path which shape to fold).
    """

    intent_id: str
    worker: str
    intent_type: str = "explore"
    facts: list[Fact] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    gate: dict[str, str] | None = None
    fact_keys: dict[str, int] = field(default_factory=dict)
    entities: list[Entity] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
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
        max_rounds: int = 10,
        dispatch_width: int = 6,
        max_fanout: int = 8,
        budget: BudgetConfig | None = None,
        pricing: PricingTable | None = None,
        analysis: str = "provenance",
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
        if max_rounds <= 0:
            raise ValueError(f"max_rounds must be > 0, got {max_rounds}")
        if dispatch_width <= 0:
            raise ValueError(f"dispatch_width must be > 0, got {dispatch_width}")
        if max_fanout <= 0:
            raise ValueError(f"max_fanout must be > 0, got {max_fanout}")
        if analysis not in ANALYSES:
            raise ValueError(f"analysis must be one of {sorted(ANALYSES)}; got {analysis!r}")
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
        # Safety valve on the Stigmergy loop (I6); see ``_continue``.
        self._max_rounds = max_rounds
        # Anti-explosion brakes (M9): cap how many open Intents one dispatch round
        # runs, and how many sub-claims a single decompose may commit (see
        # docs/design/fact-explosion-control.md).
        self._dispatch_width = dispatch_width
        self._max_fanout = max_fanout
        # Budget enforcement (M3b): steps/wall/cost are checked at round boundaries.
        self._budget = budget
        self._max_wall_seconds = (
            parse_duration(budget.max_wall, "worker.budget.max_wall") if budget is not None else 0.0
        )
        self._pricing = pricing
        self._tokens_used = 0
        self._cost_used = 0.0
        # Pause request (M3b): an RPC sets it; the loop honours it at a round boundary.
        self._pause_requested = asyncio.Event()
        # Entity-relation analysis mode (M5, proto ``analysis``): provenance runs reject
        # extract/relate Intents; relation/both add the relation stop condition.
        self._analysis = analysis
        self._fact_seq: dict[str, int] = {}
        self._intent_seq = 0
        self._session_seq = 0
        self._entity_seq = 0
        self._relation_seq = 0

    @property
    def _worker_model(self) -> str:
        # Workers may expose ``.model``; the Worker protocol only promises ``.name``.
        return getattr(self._worker, "model", None) or self._worker.name

    @property
    def _worker_self_search(self) -> bool:
        """True when the worker owns retrieval (it has the ``search`` tool)."""
        return "search" in getattr(self._worker, "tools", ())

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
        self._accumulate_usage(reply)
        return reply, started, ended, session_id

    def _usage_cost(self, usage: Usage | None) -> tuple[int, float]:
        """Return ``(tokens, cost)`` for one reply (cost is 0 without a known price)."""
        if usage is None:
            return 0, 0.0
        if usage.cost is not None:
            # The provider reported the USD cost (Pi does); prefer it over the price table.
            return usage.total_tokens, usage.cost
        if self._pricing is None:
            return usage.total_tokens, 0.0
        price = self._pricing.lookup(self._worker_model)
        if price is None:
            return usage.total_tokens, 0.0
        cost = (
            usage.prompt_tokens * price.input_per_1m + usage.completion_tokens * price.output_per_1m
        ) / 1_000_000
        return usage.total_tokens, cost

    def _accumulate_usage(self, reply: WorkerReply) -> None:
        """Add one reply's token usage (and derived cost) to the run totals (M3b)."""
        tokens, cost = self._usage_cost(reply.usage)
        self._tokens_used += tokens
        self._cost_used += cost

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
        tokens, cost = self._usage_cost(reply.usage)
        session_event: dict[str, Any] = {
            "sessionId": session_id,
            "task": task,
            "worker": worker,
            "ref": f"sessions/{session_id}.json",
            # Per-call budget counters (M3b); the reducer ignores SESSION, so the board
            # is unaffected, and summarize_run sums these into Run.budget.
            "tokens": tokens,
            "cost": round(cost, 6),
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

        Dispatch runs the Stigmergy loop (I6): Reason proposes directions, Explore passes
        run concurrently up to ``max_concurrency`` and are committed in id order, then a
        new round of Reason runs on the new facts -- until Reason completes the run or
        there is no runnable direction.
        """
        self._fact_seq = {}
        self._intent_seq = 0
        self._session_seq = 0
        self._entity_seq = 0
        self._relation_seq = 0
        # A per-run override wins over the constructor default and is normalised onto the
        # instance, so the later gates (A and C) agree on whether HITL is on.
        if auto is not None:
            self._auto = auto
        self._store.append_event("PROJECT", {"origin": origin.to_dict(), "goal": goal.to_dict()})
        await self._bootstrap()
        board = reduce(self._store.read_events())
        if board.status != "running":
            # Bootstrap failed / completed: never run Reason on a dead board.
            return board
        if not self._auto:
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

        ``decision`` is ``approve`` / ``edit`` (both continue) or ``reject``. At Gate A/B
        ``reject`` stops the run as human-terminated (``STOPPED``); at Gate C it instead
        asks for a re-check (``blackboard-protocol.md`` section 7). ``edit`` is currently
        **record-only**: ``text`` / ``targets`` land in the ``HUMAN_INPUT`` payload, but
        changing a Fact needs a fact-supersession event the contract does not have yet, so
        the board is unchanged. The board is the source of truth for where we paused, and
        the id counters are rebuilt from it, so resuming works even on a fresh ``Engine``
        over the same run directory. Gate A (``confirm-claim``), Gate B (``arbitrate``,
        M2) and Gate C (``review``, M3) are supported.
        """
        if decision not in ("approve", "edit", "reject"):
            raise EngineError(f"unknown decision {decision!r}; expected approve|edit|reject")
        events = self._store.read_events()
        board = reduce(events)
        if board.status != "awaiting_human" or board.waitingFor is None:
            raise EngineError("no human gate is awaiting input")
        gate = board.waitingFor.gate
        if gate not in (GATE_A, GATE_B, GATE_C):
            raise EngineError(f"unsupported gate {gate!r}")
        self._restore_counters(board, events)
        label = _GATE_LABELS[gate]
        self._store.append_event(
            "HUMAN_INPUT",
            {
                "gate": gate,
                "decision": decision,
                "text": text,
                "targets": list(targets),
                "author": "human",
            },
            message=f"{label}: {decision}",
        )
        if gate == GATE_C:
            return await self._resume_review(decision, text=text, targets=targets, events=events)
        if decision == "reject":
            self._store.append_event("STOPPED", {"reason": f"{label} rejected by human"})
            return reduce(self._store.read_events())
        return await self._continue()

    async def _resume_review(
        self, decision: str, *, text: str, targets: Sequence[str], events: Sequence[Event]
    ) -> Board:
        """Resolve Gate C: write the scorecard, or spawn re-check Intents and continue.

        ``approve`` / ``edit`` echo the Reason verdict (carried on the pending
        ``REQUEST_HUMAN`` event) into ``COMPLETE`` and write ``report.md``. ``reject`` asks
        for a re-check: every ``targets`` fact id on the board becomes a ``verify`` Intent
        (the compare pass re-scores it); with no valid target the engine falls back to one
        ``explore`` Intent off ``origin``. Either way the loop continues, so a later
        convergence reaches Gate C again.
        """
        if decision != "reject":
            payload = self._pending_review(events)
            hint = payload.get("hint")
            if isinstance(hint, str) and hint:
                self._write_agent_hint(hint)
            verdict = payload.get("verdict")
            self._store.append_event(
                "COMPLETE", {"verdict": verdict if isinstance(verdict, str) else ""}
            )
            self._write_report()
            return reduce(self._store.read_events())
        board = reduce(self._store.read_events())
        question = text.strip() or "Human requested a re-check at final review."
        known = {fact.id for fact in board.facts}
        # De-duplicate while preserving order: the same target must not spawn two verifies.
        recheck = list(dict.fromkeys(t for t in targets if isinstance(t, str) and t in known))
        # One verify per targeted fact (the compare pass re-judges it); with no usable
        # target, fall back to a single explore pass that re-scans from the document.
        pending = [("verify", target) for target in recheck] if recheck else [("explore", "origin")]
        for intent_type, from_ in pending:
            intent = Intent(
                id=self._next_intent_id(),
                type=intent_type,
                from_=from_,
                question=question,
            )
            self._store.append_event("INTENT", {"intent": intent.to_dict()})
        # Run the re-check before the next Reason pass: the structural stop condition still
        # holds, so a Reason-first loop could complete again and strand the open Intent,
        # silently skipping the re-check the human asked for.
        await self._dispatch()
        return await self._continue()

    @staticmethod
    def _pending_review(events: Sequence[Event]) -> Mapping[str, Any]:
        """Payload of the latest pending Gate C ``REQUEST_HUMAN`` event ({} if none)."""
        for event in reversed(list(events)):
            if event.type == "REQUEST_HUMAN" and event.payload.get("gate") == GATE_C:
                return event.payload
        return {}

    async def resume_from_pause(self) -> Board:
        """Continue a run paused via ``PAUSED`` (M3b).

        Writes ``RESUMED`` then re-enters the Stigmergy loop. Counters are rebuilt from
        the board, so this works on a fresh ``Engine`` over the same run directory.
        """
        events = self._store.read_events()
        board = reduce(events)
        if board.status != "paused":
            raise EngineError("run is not paused")
        self._restore_counters(board, events)
        self._pause_requested.clear()  # otherwise the loop would pause again immediately
        self._store.append_event("RESUMED", {}, message="resumed")
        return await self._continue()

    async def fail_runtime(self, reason: str) -> Board:
        """Record a server-owned runtime shutdown through the Engine write path."""
        board = reduce(self._store.read_events())
        if board.status not in {"completed", "failed", "stopped"}:
            self._store.append_event("FAILED", {"reason": reason})
        return reduce(self._store.read_events())

    def request_pause(self) -> None:
        """Ask the running loop to pause at the next round boundary (M3b)."""
        self._pause_requested.set()

    def _budget_exceeded(self, board: Board) -> dict[str, Any] | None:
        """Budget-breach details for a ``STOPPED`` event, or ``None`` when within budget."""
        if self._budget is None:
            return None
        events = self._store.read_events()
        started_at = events[0].at if events else ""
        elapsed = _elapsed_seconds(started_at, now_iso())
        steps = self._session_seq
        cost = round(self._cost_used, 6)
        if not (
            steps >= self._budget.max_steps
            or elapsed >= self._max_wall_seconds
            or cost >= self._budget.max_cost
        ):
            return None
        return {
            "steps": steps,
            "wall_seconds": round(elapsed, 3),
            "cost": cost,
            "limits": {
                "max_steps": self._budget.max_steps,
                "max_wall": self._budget.max_wall,
                "max_cost": self._budget.max_cost,
            },
        }

    def _stop_for_budget(self, info: dict[str, Any]) -> None:
        self._store.append_event(
            "STOPPED",
            {"reason": "budget exceeded", "budget": info},
            message="budget exceeded",
        )

    def _stop(self, reason: str, **extra: Any) -> Board:
        """Write a terminal ``STOPPED`` (dead-end / no progress / max rounds) and fold.

        The Stigmergy loop has three non-``COMPLETE`` exits besides failure: no runnable
        Intent, a round that added no facts, and the ``max_rounds`` safety valve. Recording
        ``STOPPED`` for each keeps the run out of a permanent ``running`` limbo that no
        resume path could reach.
        """
        self._store.append_event("STOPPED", {"reason": reason, **extra}, message=reason)
        return reduce(self._store.read_events())

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
        # Entity/relation ids (M5) are contiguous (``n<N>``/``r<N>`` assigned per new
        # object; ENTITY only ever upserts a previously assigned id), so counting the
        # unique objects on the board reconstructs the next value.
        self._entity_seq = len(board.entities)
        self._relation_seq = len(board.relations)
        self._session_seq = max(
            (
                _session_suffix(str(event.payload.get("sessionId", "")))
                for event in events
                if event.type == "SESSION"
            ),
            default=0,
        )
        # Rebuild the budget counters too (M3b): a resume runs on a fresh Engine, so
        # without this the cost/token totals — and thus max_cost — would reset to zero.
        tokens = 0
        cost = 0.0
        for event in events:
            if event.type != "SESSION":
                continue
            raw_tokens = event.payload.get("tokens")
            if isinstance(raw_tokens, int):
                tokens += raw_tokens
            raw_cost = event.payload.get("cost")
            if isinstance(raw_cost, (int, float)):
                cost += float(raw_cost)
        self._tokens_used = tokens
        self._cost_used = cost

    async def _continue(self) -> Board:
        """Run the Stigmergy loop: Reason, dispatch, then Reason again on new facts (I6).

        Each round re-reasons only when the previous dispatch added facts, so the run
        converges to ``COMPLETE`` (Reason judges the goal met) or stops at a dead-end (no
        runnable open Intent). A dead-end, a round that added no facts, and hitting
        ``max_rounds`` each record a terminal ``STOPPED``, so the run never sits in
        ``running`` with no way forward. The board is always folded from the event log,
        never mutated.
        """
        reasoned: set[str] = set()
        rounds = 0
        while True:
            before = reduce(self._store.read_events())
            # M3b: honour a pause request and the budget at this round boundary, before
            # starting any new work (never mid-Worker-call).
            if self._pause_requested.is_set():
                self._store.append_event(
                    "PAUSED", {"reason": "paused by request"}, message="paused"
                )
                return reduce(self._store.read_events())
            breach = self._budget_exceeded(before)
            if breach is not None:
                self._stop_for_budget(breach)
                return reduce(self._store.read_events())
            # ``reasoned`` starts empty on entry (including resume). Gate A precedes the
            # loop, so the first pass legitimately triggers on every fact on the board.
            new_facts = [fact.id for fact in before.facts if fact.id not in reasoned]
            reasoned.update(new_facts)
            await self._reason(trigger_facts=new_facts)
            board = reduce(self._store.read_events())
            if board.status != "running":
                # Reason failed the run or judged the goal met (COMPLETE).
                return board
            pending = [
                intent
                for intent in board.intents
                if intent.status == "open" and intent.type in DISPATCHABLE_TYPES
            ]
            if not pending:
                # Dead-end: Reason offered no runnable direction.
                return self._stop("dead-end: no runnable intent")
            throttled = await self._dispatch()
            board = reduce(self._store.read_events())
            if board.status != "running":
                return board
            if (
                len(board.facts) == len(before.facts)
                and len(board.entities) == len(before.entities)
                and len(board.relations) == len(before.relations)
            ):
                # No new facts and no new entities/relations (M5) -> nothing to reason
                # about next round; stop. Facts/relations are append-only and entities
                # only grow (upsert), so length comparison is exact. (An entity that only
                # gained an alias is not a new object and does not count as progress.)
                # If the width cap (M9) deferred runnable Intents, keep going so they get
                # their turn; a RELEASE'd Intent is *not* retried here (protocol section 8
                # retries it only once a later round's new facts trigger Reason).
                if throttled:
                    rounds += 1
                    if rounds >= self._max_rounds:
                        return self._stop("max rounds reached", rounds=rounds)
                    continue
                return self._stop("stalled: dispatch produced no new facts")
            rounds += 1
            if rounds >= self._max_rounds:
                return self._stop("max rounds reached", rounds=rounds)

    def _goal_satisfied(self, board: Board) -> bool:
        """Whether the structural stop condition holds (M2, protocol section 4.3 step 8).

        A run may complete only when the goal is *provenance-complete*: every main-claim
        was decomposed into sub-claims, every sub-claim has been chased (an ``explore``
        pass) or judged (a ``verify`` pass), and at least one compare pass scored
        deviations. This keeps Reason from declaring completion while gaps remain. When
        the run's ``analysis`` includes relation (M5), the relation stop condition must
        hold too: every known entity has been covered by a dispatched ``relate`` Intent
        (TODO M5 decision; a ``both`` run needs both conditions).
        """
        decomposed: set[str] = set()
        handled: set[str] = set()
        for intent in board.intents:
            if not intent.producedFacts:
                continue
            if intent.type == "decompose":
                decomposed.add(intent.from_)
            elif intent.type in ("explore", "verify"):
                # A sub-claim counts as handled once chased or judged; a pass that found
                # nothing still counts as an attempt, so an unsourceable sub-claim does
                # not block completion forever.
                handled.add(intent.from_)
        if not self._relations_satisfied(board):
            return False
        if self._analysis != "relation":
            # A provenance or both run still needs the full provenance chain; a
            # relation-only run skips the scorecard entirely.
            if not any(fact.kind == _COMPARE_KIND for fact in board.facts):
                return False
            for fact in board.facts:
                if fact.role == "main-claim" and fact.id not in decomposed:
                    return False
                if fact.role == "sub-claim" and fact.id not in handled:
                    return False
        return True

    def _relations_satisfied(self, board: Board) -> bool:
        """Whether every known entity has been covered by a dispatched ``relate`` Intent.

        "Dispatched" is a claimed or done Intent (TODO M5 decision): an ``open`` one has
        not run yet, and a ``dropped`` one was rejected by Validate, so neither counts.
        With no entities on the board the condition is trivially true (an analysis run
        over a document without entities can complete).
        """
        if self._analysis == "provenance":
            return True
        related = {
            intent.from_
            for intent in board.intents
            if intent.type == "relate" and intent.status in ("claimed", "done")
        }
        return all(entity.id in related for entity in board.entities)

    def _write_agent_hint(self, text: str) -> None:
        """Write Reason's convergence note as an agent-authored hint (M3).

        Ids come from the event log (``RunStore.next_hint_id``), so an agent hint
        cannot collide with a human hint added mid-run through ``AddHint``.
        """
        hint = Hint(id=self._store.next_hint_id(), text=text, author="agent", createdAt=now_iso())
        self._store.append_event("HINT", {"hint": hint.to_dict()}, message="Reason left a hint")

    def _write_report(self) -> None:
        """Write ``report.md`` for a completed run (a derived artifact, never an event)."""
        board = reduce(self._store.read_events())
        report = derive_report(board, run_id=self._store.root.name)
        self._store.write_report(render_report(report))

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
            result = parse_result(reply.text, allow_edges=True)
            if result.intents:
                raise EngineError("Bootstrap must not produce intents")
            for fact in result.facts:
                if fact.kind != "fact" or fact.role != "main-claim":
                    raise EngineError(
                        "Bootstrap must produce fact/main-claim facts; "
                        f"got kind={fact.kind!r} role={fact.role!r}"
                    )
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
        key_to_id = {key: result.facts[index].id for key, index in result.fact_keys.items()}
        try:
            edges = _resolve_edges(
                result.edges,
                [fact.id for fact in result.facts],
                key_to_id,
                board,
                intent_id=intent.id,
            )
        except EngineError as exc:
            self._fail(
                exc,
                reply=reply,
                session_id=session_id,
                task="Bootstrap",
                intent_id=intent.id,
                started=started,
                ended=ended,
            )
            return
        self._store.append_event(
            "CONCLUDE",
            {
                "intentId": intent.id,
                "facts": [fact.to_dict() for fact in result.facts],
                "edges": [edge.to_dict() for edge in edges],
            },
        )
        self._record_session(
            reply,
            session_id=session_id,
            task="Bootstrap",
            intent_id=intent.id,
            started=started,
            ended=ended,
        )

    async def _reason(self, *, trigger_facts: Sequence[str]) -> None:
        """Run one Reason pass, then Validate its candidates before writing them.

        Reason never produces facts (that is Explore's job), and every proposed Intent
        must point at an existing fact id or ``origin``. Validate decides which
        candidates are new; duplicates are still written, but as ``dropped`` Intents, so
        the "considered but not taken" branch stays auditable. ``trigger_facts`` are the
        facts added since the previous Reason pass (all findings on the first pass); they
        are recorded in the ``REASON`` events so the Stigmergy loop is auditable (I6).
        """
        try:
            template = await self._prompt.get("reason")
        except (CapabilityError, FileNotFoundError) as exc:
            # A missing template is a provider failure: terminal, on the board.
            self._store.append_event("FAILED", {"reason": str(exc)})
            return
        board = reduce(self._store.read_events())  # Observe: the current graph
        triggers = list(trigger_facts)
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
            result = parse_result(reply.text, allow_hint=True)
            if result.facts:
                raise EngineError("Reason must not produce facts; that is Explore's job")
            if result.complete is not None and result.intents:
                raise EngineError("Reason reply must not carry both intents and complete")
            # An Intent may only hang off a finding or the origin anchor; a ``relate``
            # Intent (M5) hangs off a known entity instead. Graph Intents are rejected
            # outright in a provenance-only run. A ``decompose`` candidate (M9) that
            # targets anything but a main-claim is not a malformed reply -- it is a
            # runaway subdivision -- so it is recorded as a ``dropped`` Intent (below)
            # rather than killing the run.
            known = {"origin"} | {fact.id for fact in board.facts}
            entity_ids = {entity.id for entity in board.entities}
            roles = {fact.id: fact.role for fact in board.facts}
            guarded: dict[int, str] = {}
            for index, candidate in enumerate(result.intents):
                if candidate.type in GRAPH_INTENT_TYPES and self._analysis == "provenance":
                    raise EngineError(
                        f"intent type {candidate.type!r} requires analysis=relation|both"
                    )
                if candidate.type == "relate" and candidate.from_ not in entity_ids:
                    raise EngineError(
                        f"relate intent.from {candidate.from_!r} is not a known entity id"
                    )
                if candidate.from_ not in known and candidate.type != "relate":
                    raise EngineError(f"intent.from {candidate.from_!r} is not a known fact id")
                if candidate.type == "decompose" and roles.get(candidate.from_) != "main-claim":
                    # Only the core claim decomposes (two-level tree, M9): a sub-claim or
                    # the origin is explored/verified, never split again.
                    guarded[index] = "decompose targets a non main-claim fact"
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
            satisfied = self._goal_satisfied(board)
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
            if not satisfied:
                # The model judged the goal met, but the structural stop condition is not
                # satisfied yet (every claim decomposed and sourced, deviations scored).
                # Keep the run going instead of completing early; a later round can still
                # complete once the gaps are filled (blackboard-protocol section 4.3).
                return
            if not self._auto:
                # Gate C: the goal is proven complete, but HITL is on, so the human
                # confirms the final scorecard before it is written. The Reason verdict and
                # its convergence hint ride on the REQUEST_HUMAN payload (the reducer
                # ignores the extra keys) so a fresh Engine on resume can echo them without
                # re-running a model; ``reject`` instead spawns re-check Intents (resume).
                payload: dict[str, Any] = {
                    "gate": GATE_C,
                    "question": "Confirm the final scorecard",
                    "verdict": result.complete,
                }
                if result.hint is not None:
                    payload["hint"] = result.hint
                self._store.append_event(
                    "REQUEST_HUMAN",
                    payload,
                    message="Gate C: confirm the final scorecard",
                )
                return
            if result.hint is not None:
                # Reason's convergence note (M3): only a convergence that actually ends
                # the run leaves a hint, so intermediate "complete" calls add no noise.
                self._write_agent_hint(result.hint)
            self._store.append_event("COMPLETE", {"verdict": result.complete})
            self._write_report()
            return

        # Only the candidates the M9 guard did not already reject go through Validate;
        # a guarded candidate is dropped regardless, so asking the validator about it is
        # pointless (and would make its kept/dropped counts lie). Decisions are mapped
        # back to the original candidate positions.
        decisions: dict[int, IntentDecision] = {}
        to_validate = [
            (position, candidate)
            for position, candidate in enumerate(result.intents)
            if position not in guarded
        ]
        if to_validate:
            try:
                validated = (
                    await self._validate([candidate for _, candidate in to_validate], board)
                ).decisions
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
            decisions = {
                position: decision
                for (position, _), decision in zip(to_validate, validated, strict=True)
            }
        # The model's lifecycle fields are untrusted: rebuild each candidate as a fresh
        # open/dropped Intent so only the engine controls status/claim/heartbeat. A
        # candidate the M9 guard rejected (runaway decompose) is dropped too, with its
        # motive on the event message for audit.
        for position, candidate in enumerate(result.intents):
            decision = decisions.get(position)
            is_dropped = decision.drop if decision is not None else False
            guard_reason = guarded.get(position)
            dropped = is_dropped or guard_reason is not None
            intent = Intent(
                id=self._next_intent_id(),
                type=candidate.type,
                from_=candidate.from_,
                question=candidate.question,
                status="dropped" if dropped else "open",
                duplicateOf=decision.duplicate_of if decision is not None else None,
            )
            self._store.append_event(
                "INTENT",
                {"intent": intent.to_dict()},
                message=f"dropped: {guard_reason}" if guard_reason else "",
            )
        if result.hint is not None and not result.intents:
            # Dead-end convergence (no runnable direction was offered): keep Reason's
            # note on the board. A hint alongside Intents is ignored (M3).
            self._write_agent_hint(result.hint)
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

    async def _dispatch(self) -> bool:
        """Run one dispatch round: every open Intent the engine can execute.

        The round works on a snapshot of the board as Reason left it (a later Reason
        round handles the facts it produces, I6). ``explore``/``decompose`` chase
        sources; ``verify`` runs the compare pass and scores deviations (M2);
        ``extract``/``relate`` drive the entity-relation graph (M5). At most
        ``dispatch_width`` open Intents are claimed this round (M9), in id order; the
        rest stay ``open`` for a later round. The claimed passes run concurrently,
        bounded by ``max_concurrency``. Outcomes are committed back in id order, so the
        Board (fact ids, entity ids and semantic edges) is deterministic even though
        completion order is not; the round stops committing at the first hard failure.
        A verify pass may request **Gate B** through its reply; the round then commits
        every fact first and pauses afterwards, so the gate loses nothing.

        Returns ``True`` when the width cap left runnable Intents for a later round, so
        the loop keeps going even if this round produced no new facts.
        """
        board = reduce(self._store.read_events())
        pending = [
            intent
            for intent in board.intents
            if intent.status == "open" and intent.type in DISPATCHABLE_TYPES
        ]
        if not pending:
            return False
        # Width cap (M9): run at most ``dispatch_width`` open Intents per round, in id
        # order. The rest stay ``open`` and are picked up by a later round -- throttling,
        # not dropping, so the board keeps every direction.
        throttled = len(pending) > self._dispatch_width
        if throttled:
            pending = pending[: self._dispatch_width]
        try:
            # Fetched once for the whole round; a missing template is a provider failure,
            # written before any Intent is claimed. Each kind is fetched only when needed.
            templates: dict[str, PromptTemplate] = {}
            if any(intent.type in ("explore", "decompose") for intent in pending):
                templates["explore"] = await self._prompt.get("explore")
            if any(intent.type == "verify" for intent in pending):
                templates["verify"] = await self._prompt.get("compare")
            if any(intent.type == "extract" for intent in pending):
                templates["extract"] = await self._prompt.get("extract")
            if any(intent.type == "relate" for intent in pending):
                templates["relate"] = await self._prompt.get("relate")
        except (CapabilityError, FileNotFoundError) as exc:
            self._store.append_event("FAILED", {"reason": str(exc)})
            return False

        def template_for(intent: Intent) -> PromptTemplate:
            if intent.type in ("explore", "decompose"):
                return templates["explore"]
            return templates[intent.type]

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
                self._guarded_run_explore(
                    intent, board, template_for(intent), worker, session_id, semaphore
                )
                for intent, worker, session_id in zip(pending, workers, session_ids, strict=True)
            )
        )
        # Worker replies carry no ids; assign them at commit time, in id order, so the
        # resulting fact ids never depend on which pass happened to finish first.
        gate: dict[str, str] | None = None
        # The graph so far, advanced as extract/relate outcomes commit in id order, so a
        # later pass can reference an entity an earlier one in the same round produced.
        graph_entities = list(board.entities)
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
                return False
            if outcome.intent_type in GRAPH_INTENT_TYPES:
                # An extract/relate pass produces no facts; it re-emits/merges entities or
                # writes judged relations, then concludes like any other Intent.
                try:
                    graph_entities = self._commit_graph_pass(outcome, graph_entities)
                except EngineError as exc:
                    self._fail(
                        exc,
                        reply=outcome.reply,
                        session_id=outcome.session_id,
                        task="Explore",
                        intent_id=outcome.intent_id,
                        started=outcome.started,
                        ended=outcome.ended,
                        worker=outcome.worker,
                    )
                    return False
                # Refresh the derived ``entity-graph.json`` right after this pass commits,
                # so a later failure in the same round cannot leave it stale (M5).
                self._flush_entity_graph()
                self._store.append_event(
                    "CONCLUDE",
                    {"intentId": outcome.intent_id, "facts": [], "edges": []},
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
                continue
            facts = outcome.facts
            fact_keys = outcome.fact_keys
            edges_raw = outcome.edges
            conclude_message = ""
            if outcome.intent_type == "decompose" and len(facts) > self._max_fanout:
                # Fanout cap (M9): one decompose may commit at most ``max_fanout``
                # sub-claims, in reply order; the surplus is dropped (the raw reply stays in
                # the session snapshot). Drop edges that referenced a surplus fact too, so
                # the cap never turns an otherwise valid reply into a terminal failure.
                surplus = {
                    key for key, index in fact_keys.items() if index >= self._max_fanout
                }
                facts = facts[: self._max_fanout]
                fact_keys = {
                    key: index for key, index in fact_keys.items() if index < self._max_fanout
                }
                edges_raw = [
                    edge
                    for edge in edges_raw
                    if str(edge["source"]) not in surplus and str(edge["target"]) not in surplus
                ]
                conclude_message = f"decompose capped at {self._max_fanout} sub-claims"
            for fact in facts:
                fact.id = self._next_fact_id(fact.kind)
            key_to_id = {key: facts[index].id for key, index in fact_keys.items()}
            try:
                edges = _resolve_edges(
                    edges_raw,
                    [fact.id for fact in facts],
                    key_to_id,
                    board,
                    intent_id=outcome.intent_id,
                )
            except EngineError as exc:
                # An edge that cannot be resolved is a malformed reply: terminal, and
                # the session is kept for the audit, like any other bad reply.
                self._fail(
                    exc,
                    reply=outcome.reply,
                    session_id=outcome.session_id,
                    task="Explore",
                    intent_id=outcome.intent_id,
                    started=outcome.started,
                    ended=outcome.ended,
                    worker=outcome.worker,
                )
                return False
            self._store.append_event(
                "CONCLUDE",
                {
                    "intentId": outcome.intent_id,
                    "facts": [fact.to_dict() for fact in facts],
                    "edges": [edge.to_dict() for edge in edges],
                },
                message=conclude_message,
            )
            if gate is None and outcome.gate is not None:
                gate = outcome.gate
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
        if gate is not None:
            # Gate B: a verify pass hit an ambiguity or source conflict it cannot settle.
            # Every fact of the round is already committed, so pausing loses nothing.
            self._store.append_event(
                "REQUEST_HUMAN",
                {"gate": gate["gate"], "question": gate["question"]},
                message="Gate B: arbitrate a source conflict",
            )
        return throttled

    def _commit_graph_pass(self, outcome: _ExploreOutcome, entities: list[Entity]) -> list[Entity]:
        """Commit one ``extract``/``relate`` outcome; return the advanced graph.

        ``extract`` merges its entities by canonical name (re-emitting a survivor with
        accumulated aliases, or allocating a fresh ``n*`` id); ``relate`` validates its
        references against the known entities and writes fresh ``r*`` relations. A
        reference to an unknown entity is a malformed reply (:class:`EngineError`),
        handled by the caller like any other bad reply.
        """
        if outcome.intent_type == "extract":
            return self._commit_extract(outcome.entities, entities)
        return self._commit_relate(outcome.relations, entities)

    def _commit_extract(self, reply_entities: list[Entity], entities: list[Entity]) -> list[Entity]:
        """Merge the entities of one extract reply into ``entities`` (M5).

        An entity whose name (or an accumulated alias) canonicalizes to one already on
        the board merges into it: the survivor keeps its id, its name (first-seen wins,
        so replay never flips) and status; ``aliases`` accumulate, ``type`` upgrades from
        ``other`` when the reply is more specific, ``confidence`` takes the max and
        evidence is unioned. A new name gets a fresh ``n<N>`` id. Every touched entity is
        re-emitted as an ``ENTITY`` event (the reducer upserts by id).
        """
        merged = list(entities)
        for reply_entity in reply_entities:
            key = canonical_name(reply_entity.name)
            target = self._find_entity(merged, key)
            if target is None:
                entity = Entity(
                    id=self._next_entity_id(),
                    name=reply_entity.name,
                    type=reply_entity.type,
                    aliases=self._distinct_aliases(reply_entity.name, reply_entity.aliases),
                    status=reply_entity.status,
                    confidence=reply_entity.confidence,
                    note=reply_entity.note,
                    position=dict(reply_entity.position),
                )
                entity.evidence = self._renumber_evidence(reply_entity.evidence, entity.id)
                self._store.append_event("ENTITY", {"entity": entity.to_dict()})
                merged.append(entity)
                continue
            index = merged.index(target)
            self._merge_into(target, reply_entity)
            self._store.append_event("ENTITY", {"entity": target.to_dict()})
            merged[index] = target
        return merged

    @staticmethod
    def _find_entity(entities: list[Entity], key: str) -> Entity | None:
        """The entity whose name or any alias canonicalizes to ``key`` (first match)."""
        for entity in entities:
            names = [entity.name, *entity.aliases]
            if any(canonical_name(name) == key for name in names):
                return entity
        return None

    @staticmethod
    def _distinct_aliases(name: str, aliases: Sequence[str]) -> list[str]:
        """Strip and dedupe ``aliases`` against ``name`` by canonical key (M5).

        A case/width/whitespace variant of the name is not a distinct alias, so it is
        dropped; the survivors are stored in first-seen order (deterministic).
        """
        known = {canonical_name(name)}
        distinct: list[str] = []
        for alias in aliases:
            stripped = alias.strip()
            if stripped and canonical_name(stripped) not in known:
                distinct.append(stripped)
                known.add(canonical_name(stripped))
        return distinct

    def _merge_into(self, target: Entity, reply: Entity) -> None:
        """Fold a reply entity into an existing survivor in place (M5 merge).

        First-seen fields win (``name``/``status``/``note``/``position``) so replay is
        stable. The survivor gains every genuinely distinct alias from the reply
        (deduped by canonical name against the survivor's name and aliases). ``type``
        upgrades from ``other`` when the reply is more specific, ``confidence`` takes the
        max and evidence is unioned (re-numbered under the survivor's id). The reply's
        own name is the merge key, so it is already represented and never restated.
        """
        known = {canonical_name(name) for name in [target.name, *target.aliases]}
        for alias in reply.aliases:
            stripped = alias.strip()
            if stripped and canonical_name(stripped) not in known:
                target.aliases.append(stripped)
                known.add(canonical_name(stripped))
        if target.type == "other" and reply.type != "other":
            target.type = reply.type
        target.confidence = max(target.confidence, reply.confidence)
        target.evidence = self._renumber_evidence([*target.evidence, *reply.evidence], target.id)

    def _commit_relate(
        self, reply_relations: list[Relation], entities: list[Entity]
    ) -> list[Entity]:
        """Write the relations of one relate reply as fresh ``r*`` events (M5).

        Each ``source``/``target`` must name a known entity (entities committed earlier
        in the same round are visible). An ``inferred`` relation is normalized to
        ``status=inferred`` (protocol section 2.6). References are validated here because
        parsing has no board. Entities are returned unchanged.
        """
        known = {entity.id for entity in entities}
        for reply in reply_relations:
            if reply.source not in known:
                raise EngineError(f"relation.source {reply.source!r} is not a known entity id")
            if reply.target not in known:
                raise EngineError(f"relation.target {reply.target!r} is not a known entity id")
            if reply.source == reply.target:
                raise EngineError(f"relation cannot be a self-loop on {reply.source!r}")
            relation_id = self._next_relation_id()
            relation = Relation(
                id=relation_id,
                source=reply.source,
                target=reply.target,
                type=reply.type,
                label=reply.label,
                status="inferred" if reply.inferred else reply.status,
                confidence=reply.confidence,
                inferred=reply.inferred,
                note=reply.note,
                evidence=self._renumber_evidence(reply.evidence, relation_id),
            )
            self._store.append_event("RELATION", {"relation": relation.to_dict()})
        return entities

    @staticmethod
    def _renumber_evidence(evidence: Sequence[Evidence], owner: str) -> list[Evidence]:
        """Give each evidence entry a deterministic id scoped to ``owner`` (M5).

        Reply evidence ids are per-reply placeholders; once evidence lands on an entity
        or relation, the id is derived from the owning object so merges never collide.
        """
        return [
            Evidence(
                id=f"{owner}-ev{index}",
                quote=entry.quote,
                sourceTitle=entry.sourceTitle,
                url=entry.url,
                locator=entry.locator,
            )
            for index, entry in enumerate(evidence, start=1)
        ]

    def _flush_entity_graph(self) -> None:
        """Rewrite ``entity-graph.json`` from the board (a derived artifact, M5)."""
        board = reduce(self._store.read_events())
        graph = EntityGraph(entities=board.entities, relations=board.relations)
        self._store.write_entity_graph(
            json.dumps(graph.to_dict(), sort_keys=True, ensure_ascii=False, indent=2) + "\n"
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
            intent_type=intent.type,
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
        and passes the results to the worker via ``extra`` -- unless the worker owns
        retrieval (it has the ``search`` tool, e.g. Pi with ``[worker].tools=["search"]``),
        in which case the agent searches itself and no ``extra["search"]`` is injected.
        An ``extract``/``relate`` Intent (M5) does no retrieval: it reads document A and
        the board (which carries the known entities) and returns entities/relations.
        The worker never touches providers otherwise. Every blackboard write happens
        later, in :meth:`_dispatch`. The heartbeat lease covers the whole pass (search
        included), so a hung search cannot hold a claimed Intent without a heartbeat or
        a timeout either.
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
                if intent.type == "explore" and not self._worker_self_search:
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
                    # A shared run container is tainted by a cancelled call: it must
                    # fail the run rather than reuse a potentially wedged runtime.
                    timeout = self._timeout_outcome(intent, worker)
                    abort = getattr(self._worker, "abort", None)
                    if abort is not None:
                        await abort()
                        timeout.error = CapabilityError(str(timeout.error))
                    return timeout
                except CapabilityError as exc:
                    return _ExploreOutcome(intent_id=intent.id, worker=worker, error=exc)
            finally:
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat
            try:
                if intent.type in GRAPH_INTENT_TYPES:
                    # extract/relate carry entities/relations instead of facts/edges; which
                    # of the two a given pass may yield is enforced by ``_check_graph_pass``.
                    result = parse_result(
                        reply.text, allow_entities=True, allow_relations=True
                    )
                else:
                    result = parse_result(reply.text, allow_edges=True, allow_gate=True)
                if result.intents:
                    raise EngineError("Explore must not produce intents; direction is Reason's job")
                if result.complete is not None:
                    raise EngineError("Explore must not judge completion; that is Reason's job")
                if result.gate is not None and intent.type != "verify":
                    raise EngineError("only a verify pass may request a human gate")
                if intent.type in GRAPH_INTENT_TYPES:
                    self._check_graph_pass(intent, result)
                else:
                    self._check_explored_facts(intent, result.facts)
            except EngineError as exc:
                # An unusable reply ends the run; keep the session for the audit.
                return _ExploreOutcome(
                    intent_id=intent.id,
                    worker=worker,
                    intent_type=intent.type,
                    reply=reply,
                    session_id=session_id,
                    started=started,
                    ended=ended,
                    error=exc,
                )
            return _ExploreOutcome(
                intent_id=intent.id,
                worker=worker,
                intent_type=intent.type,
                facts=result.facts,
                edges=result.edges,
                gate=result.gate,
                fact_keys=result.fact_keys,
                entities=result.entities,
                relations=result.relations,
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

    def _check_graph_pass(self, intent: Intent, result: WorkerResult) -> None:
        """Check an ``extract``/``relate`` reply yields only what its Intent may (M5).

        An ``extract`` pass produces entities only; a ``relate`` pass relations only.
        Both must stay out of the fact graph: a stray fact would pollute the provenance
        DAG the Stigmergy loop and stop condition run on.
        """
        if result.facts:
            raise EngineError(f"{intent.type} intent {intent.id} must not produce facts")
        if intent.type == "extract" and result.relations:
            raise EngineError(f"extract intent {intent.id} must not produce relations")
        if intent.type == "relate" and result.entities:
            raise EngineError(f"relate intent {intent.id} must not produce entities")

    def _check_explored_facts(self, intent: Intent, facts: list[Fact]) -> None:
        """Check a batch of produced facts against what the Intent type may yield."""
        if intent.type == "verify":
            self._check_verified_facts(intent, facts)
            return
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

    def _check_verified_facts(self, intent: Intent, facts: list[Fact]) -> None:
        """Check a verify pass: exactly one compare node plus well-formed deviations (M2).

        The compare node is the pass's own summary and must be ``verified``. Every
        deviation needs evidence and a ``severity=`` subtitle whose level maps to its
        ``status`` (high flags; medium/low are left for review). The frozen shape is the
        sample fixture (``examples/copilot_productivity``).
        """
        compares = [fact for fact in facts if fact.kind == _COMPARE_KIND]
        if len(compares) != 1:
            raise EngineError(
                f"verify intent {intent.id} must produce exactly one {_COMPARE_KIND} fact; "
                f"got {len(compares)}"
            )
        for fact in facts:
            if fact.kind == _COMPARE_KIND:
                if fact.role != "none" or fact.status != "verified":
                    raise EngineError(
                        f"verify intent {intent.id}: {_COMPARE_KIND} fact must be "
                        f"role=none/status=verified; got role={fact.role!r} "
                        f"status={fact.status!r}"
                    )
                continue
            if fact.kind != _DEVIATION_KIND:
                raise EngineError(
                    f"verify intent {intent.id} must produce {sorted(_VERIFY_FACT_KINDS)} "
                    f"facts; got kind={fact.kind!r}"
                )
            if fact.role != "none":
                raise EngineError(
                    f"verify intent {intent.id} must produce role=none deviations; "
                    f"got {fact.label!r} with role={fact.role!r}"
                )
            if not fact.evidence:
                raise EngineError(
                    f"verify intent {intent.id}: deviation {fact.label!r} needs at least "
                    "one evidence entry"
                )
            try:
                severity = parse_severity(fact)
            except ReportError as exc:
                raise EngineError(str(exc)) from exc
            expected = SEVERITY_STATUS[severity]
            if fact.status != expected:
                raise EngineError(
                    f"verify intent {intent.id}: deviation severity={severity} must have "
                    f"status={expected}; got {fact.status!r}"
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
        # A ``dropped`` Intent was never executed, so it is not a real duplicate target:
        # a candidate the model dropped against one (e.g. a redo now that new evidence has
        # arrived) is kept. This is deterministic -- never trust the model's obedience --
        # and the flipped verdict is recorded on the VALIDATE event, so it stays auditable.
        status_by_id = {intent.id: intent.status for intent in board.intents}
        overridden: list[dict[str, Any]] = []
        for decision in result.decisions:
            if (
                decision.drop
                and decision.duplicate_of is not None
                and status_by_id.get(decision.duplicate_of) == "dropped"
            ):
                overridden.append(
                    {
                        "index": decision.index,
                        "duplicateOf": decision.duplicate_of,
                        "reason": decision.reason,
                    }
                )
                decision.drop = False
                decision.duplicate_of = None
                decision.reason = ""
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
                "overridden": overridden,
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

    def _next_entity_id(self) -> str:
        self._entity_seq += 1
        return f"n{self._entity_seq}"

    def _next_relation_id(self) -> str:
        self._relation_seq += 1
        return f"r{self._relation_seq}"

    def _next_fact_id(self, kind: str) -> str:
        """Return the next deterministic id for ``kind`` (e.g. ``f1``, ``c2``)."""
        prefix = _PREFIX.get(kind, "f")
        self._fact_seq[prefix] = self._fact_seq.get(prefix, 0) + 1
        return f"{prefix}{self._fact_seq[prefix]}"


__all__ = [
    "ANALYSES",
    "BOOTSTRAP_QUESTION",
    "DISPATCHABLE_TYPES",
    "GATE_A",
    "GATE_B",
    "GATE_C",
    "Engine",
    "EngineError",
    "IntentDecision",
    "ValidationResult",
    "WorkerResult",
    "parse_result",
    "parse_validation",
]
