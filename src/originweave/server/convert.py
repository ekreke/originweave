"""Map domain objects / events to the generated ``originweave.v1`` messages.

The generated modules are untyped to mypy (see the ``originweave.v1.*`` override),
so the return types here are ``Any``. ``Event.payload`` is arbitrary JSON and is
placed into a ``google.protobuf.Struct`` via :func:`json_format.ParseDict`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from google.protobuf import json_format, struct_pb2

from originweave.v1 import originweave_pb2 as pb

from ..blackboard import Board, Edge, Evidence, Fact, Hint, HumanDecision, Intent, WaitingFor
from ..config import Config, ModelConfig, WorkerConfig
from ..events import Event
from ..persistence import Project, Run
from ..report import Deviation, Report, derive_report


def evidence_pb(evidence: Evidence) -> Any:
    return pb.Evidence(
        id=evidence.id,
        quote=evidence.quote,
        source_title=evidence.sourceTitle,
        url=evidence.url,
        locator=evidence.locator,
    )


def fact_pb(fact: Fact) -> Any:
    return pb.Fact(
        id=fact.id,
        label=fact.label,
        subtitle=fact.subtitle,
        kind=fact.kind,
        role=fact.role,
        status=fact.status,
        confidence=fact.confidence,
        note=fact.note,
        position=pb.Vec2(
            x=float(fact.position.get("x", 0.0)),
            y=float(fact.position.get("y", 0.0)),
        ),
        evidence=[evidence_pb(item) for item in fact.evidence],
    )


def intent_pb(intent: Intent) -> Any:
    # "from" is a Python keyword, so it cannot be a constructor kwarg; protobuf
    # exposes it as a field of that name, settable via a mapping splat.
    message = pb.Intent(
        **{
            "id": intent.id,
            "type": intent.type,
            "status": intent.status,
            "from": intent.from_,
            "question": intent.question,
            "produced_facts": list(intent.producedFacts),
            "created_at": intent.createdAt,
        }
    )
    if intent.claimedBy is not None:
        message.claimed_by = intent.claimedBy
    if intent.heartbeatAt is not None:
        message.heartbeat_at = intent.heartbeatAt
    if intent.duplicateOf is not None:
        message.duplicate_of = intent.duplicateOf
    return message


def hint_pb(hint: Hint) -> Any:
    return pb.Hint(id=hint.id, text=hint.text, author=hint.author, created_at=hint.createdAt)


def edge_pb(edge: Edge) -> Any:
    return pb.Edge(
        id=edge.id,
        source=edge.source,
        target=edge.target,
        relation=edge.relation,
        note=edge.note,
    )


def waiting_for_pb(waiting: WaitingFor) -> Any:
    return pb.WaitingFor(gate=waiting.gate, question=waiting.question)


def decision_pb(decision: HumanDecision) -> Any:
    return pb.HumanDecision(
        gate=decision.gate,
        decision=decision.decision,
        text=decision.text,
        targets=list(decision.targets),
        author=decision.author,
        at=decision.at,
    )


def deviation_pb(deviation: Deviation) -> Any:
    return pb.Deviation(
        id=deviation.id,
        title=deviation.title,
        summary=deviation.summary,
        severity=deviation.severity,
        confidence=deviation.confidence,
        node_id=deviation.nodeId,
    )


def report_pb(report: Report) -> Any:
    return pb.Report(
        run_id=report.runId,
        verdict=report.verdict,
        summary=report.summary,
        findings=[deviation_pb(finding) for finding in report.findings],
        sources=[evidence_pb(source) for source in report.sources],
    )


def session_step_pb(step: Mapping[str, Any]) -> Any:
    """Map one ``sessions/*.json`` step to a ``SessionStep``.

    ``text`` is the untruncated snapshot value (the ``WORKER_STEP`` event is the
    truncated index; the session file is the source of truth).
    """
    message = pb.SessionStep(
        seq=int(step.get("seq", 0)),
        kind=str(step.get("kind", "")),
        name=str(step.get("name", "")),
        text=str(step.get("text", "")),
    )
    ok = step.get("ok")
    if ok is not None:
        message.ok = bool(ok)
    return message


def session_pb(session: Mapping[str, Any]) -> Any:
    """Map one ``sessions/*.json`` snapshot to a ``Session`` (raw input/output)."""
    payload = struct_pb2.Struct()
    json_format.ParseDict(session.get("input") or {}, payload)
    message = pb.Session(
        id=str(session.get("id", "")),
        run_id=str(session.get("runId", "")),
        worker=str(session.get("worker", "")),
        task=str(session.get("task", "")),
        model=str(session.get("model", "")),
        input=payload,
        output=str(session.get("output", "")),
        steps=[session_step_pb(step) for step in session.get("steps") or []],
        started_at=str(session.get("startedAt", "")),
        ended_at=str(session.get("endedAt", "")),
    )
    intent_id = session.get("intentId")
    if intent_id is not None:
        message.intent_id = str(intent_id)
    return message


def worker_settings_pb(worker: WorkerConfig, model: ModelConfig) -> Any:
    """Map the ``[worker]`` + ``[capability.model]`` config onto ``WorkerSettings``."""
    return pb.WorkerSettings(
        llm=pb.LlmSettings(provider=model.provider, model=model.model, base_url=model.base_url),
        provider=worker.provider,
        max_concurrency=worker.max_concurrency,
        tools=list(worker.tools),
        heartbeat_interval=worker.heartbeat_interval,
        heartbeat_timeout=worker.heartbeat_timeout,
        heartbeat_on_timeout=worker.heartbeat_on_timeout,
        budget=pb.WorkerBudget(
            max_steps=worker.budget.max_steps,
            max_wall=worker.budget.max_wall,
            max_cost=worker.budget.max_cost,
        ),
    )


def settings_pb(config: Config) -> Any:
    """Map a :class:`Config` onto the ``Settings`` message."""
    return pb.Settings(worker=worker_settings_pb(config.worker, config.capability.model))


def event_pb(event: Event) -> Any:
    payload = struct_pb2.Struct()
    json_format.ParseDict(event.payload, payload)
    return pb.Event(
        id=event.id,
        at=event.at,
        type=event.type,
        message=event.message,
        tone=event.tone,
        payload=payload,
    )


def project_pb(project: Project) -> Any:
    return pb.Project(
        id=project.id,
        name=project.name,
        description=project.description,
        run_count=project.run_count,
        updated_at=project.updated_at,
        accent=project.accent,
    )


def run_pb(run: Run) -> Any:
    return pb.Run(
        id=run.id,
        project_id=run.project_id,
        title=run.title,
        source_type=run.source_type,
        analysis=run.analysis,
        status=run.status,
        goal=run.goal,
        facts=run.facts,
        deviations=run.deviations,
        entities=run.entities,
        relations=run.relations,
        intents=pb.IntentCounts(open=run.intents.open, done=run.intents.done),
        confidence=run.confidence,
        steps=pb.Steps(current=run.steps.current, total=run.steps.total),
        budget=pb.Budget(
            tokens=run.budget.tokens,
            cost=run.budget.cost,
            elapsed=run.budget.elapsed,
        ),
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def run_detail_pb(
    run: Run,
    board: Board,
    events: Sequence[Event],
    *,
    sessions: Sequence[Mapping[str, Any]] = (),
) -> Any:
    waiting = waiting_for_pb(board.waitingFor) if board.waitingFor is not None else None
    report = derive_report(board, run_id=run.id)
    detail = pb.RunDetail(
        run=run_pb(run),
        origin=fact_pb(board.origin),
        goal=fact_pb(board.goal),
        facts=[fact_pb(fact) for fact in board.facts],
        intents=[intent_pb(intent) for intent in board.intents],
        hints=[hint_pb(hint) for hint in board.hints],
        edges=[edge_pb(edge) for edge in board.edges],
        deviations=[deviation_pb(finding) for finding in report.findings],
        events=[event_pb(event) for event in events],
        decisions=[decision_pb(decision) for decision in board.decisions],
        sessions=[session_pb(session) for session in sessions],
        # proto3 optional *message* fields reject direct assignment; constructor kwargs
        # work (and CopyFrom below). Same applies to entity_graph when M5 lands.
        waiting_for=waiting,
    )
    if report.verdict or report.findings:
        detail.report.CopyFrom(report_pb(report))
    return detail
