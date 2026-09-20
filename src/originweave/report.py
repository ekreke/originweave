"""Deviation scorecard and run report (M2).

The report is a **derivation** from the board, never an event: :func:`derive_report`
folds the ``kind=deviation`` facts (and their evidence) into the ``Report`` shape frozen
in ``product-overview.md`` section 4. The engine writes ``report.md`` when a run
completes; the server maps the same object into ``RunDetail.report``. Because it is a
pure fold, ``replay`` reproduces it exactly and never rewrites the file.

Severity is encoded in ``Fact.subtitle`` as ``severity=<level> · confidence=<c>`` — the
shape the sample fixture froze (``examples/copilot_productivity``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .blackboard import Board, Evidence, Fact

# Deviation severity levels, high to low (product-overview.md section 4).
SEVERITIES: tuple[str, ...] = ("high", "medium", "low")
SEVERITY_PREFIX = "severity="
# severity -> deviation Fact.status (frozen by the sample fixture: high flags, the rest
# are left for review).
SEVERITY_STATUS: dict[str, str] = {"high": "flagged", "medium": "review", "low": "review"}


class ReportError(ValueError):
    """Raised when a deviation fact does not carry a well-formed severity."""


@dataclass
class Deviation:
    id: str
    title: str
    summary: str
    severity: str
    confidence: float
    nodeId: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "severity": self.severity,
            "confidence": self.confidence,
            "nodeId": self.nodeId,
        }


@dataclass
class Report:
    runId: str
    verdict: str
    summary: str
    findings: list[Deviation] = field(default_factory=list)
    sources: list[Evidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.runId,
            "verdict": self.verdict,
            "summary": self.summary,
            "findings": [finding.to_dict() for finding in self.findings],
            "sources": [source.to_dict() for source in self.sources],
        }


def parse_severity(fact: Fact) -> str:
    """Return the severity encoded in ``fact.subtitle`` (e.g. ``"high"``).

    Raises :class:`ReportError` when the subtitle does not start with ``severity=`` or
    names an unknown level.
    """
    subtitle = fact.subtitle or ""
    if not subtitle.startswith(SEVERITY_PREFIX):
        raise ReportError(
            f"deviation {fact.id} subtitle must start with {SEVERITY_PREFIX!r}; "
            f"got {subtitle!r}"
        )
    level = subtitle[len(SEVERITY_PREFIX) :].split("\u00b7", 1)[0].strip()
    if level not in SEVERITIES:
        raise ReportError(
            f"deviation {fact.id} severity must be one of {SEVERITIES}; got {level!r}"
        )
    return level


def _summarize(verdict: str, findings: list[Deviation]) -> str:
    """Build a deterministic one-line summary from the verdict and findings."""
    if not findings:
        return verdict or "No deviations."
    titles = "\uff1b".join(f"{finding.severity}: {finding.title}" for finding in findings)
    return f"{verdict or 'Deviations'} ({len(findings)}): {titles}"


def derive_report(board: Board, *, run_id: str) -> Report:
    """Fold a board's deviation facts into a :class:`Report` (pure, deterministic).

    Findings keep the board's fact order; sources are the findings' evidence de-duplicated
    by ``(url, quote)`` while preserving first-seen order.
    """
    findings: list[Deviation] = []
    sources: list[Evidence] = []
    seen: set[tuple[str, str]] = set()
    for fact in board.facts:
        if fact.kind != "deviation":
            continue
        findings.append(
            Deviation(
                id=fact.id,
                title=fact.label,
                summary=fact.note,
                severity=parse_severity(fact),
                confidence=fact.confidence,
                nodeId=fact.id,
            )
        )
        for evidence in fact.evidence:
            key = (evidence.url, evidence.quote)
            if key not in seen:
                seen.add(key)
                sources.append(evidence)
    verdict = board.verdict or ""
    return Report(
        runId=run_id,
        verdict=verdict,
        summary=_summarize(verdict, findings),
        findings=findings,
        sources=sources,
    )


def render_report(report: Report) -> str:
    """Render a report as the ``report.md`` text written under the run directory."""
    lines = [
        f"# Deviation scorecard \u00b7 {report.runId}",
        "",
        f"- verdict: {report.verdict or '(none)'}",
        f"- summary: {report.summary}",
        f"- findings: {len(report.findings)}",
        f"- sources: {len(report.sources)}",
        "",
        "## Findings",
        "",
    ]
    for finding in report.findings:
        lines.append(f"### {finding.id} \u00b7 {finding.title}")
        lines.append("")
        lines.append(f"- severity: {finding.severity}")
        lines.append(f"- confidence: {finding.confidence:.2f}")
        lines.append(f"- node: {finding.nodeId}")
        if finding.summary:
            lines.append(f"- note: {finding.summary}")
        lines.append("")
    lines.append("## Sources")
    lines.append("")
    for source in report.sources:
        lines.append(f"- {source.sourceTitle} \u2014 {source.url} ({source.locator})")
        lines.append(f"  > {source.quote}")
    return "\n".join(lines) + "\n"


__all__ = [
    "SEVERITIES",
    "SEVERITY_STATUS",
    "Deviation",
    "Report",
    "ReportError",
    "derive_report",
    "parse_severity",
    "render_report",
]
