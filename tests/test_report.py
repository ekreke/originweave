"""M2 tests for the deviation scorecard (report module)."""

from __future__ import annotations

import pytest

from originweave.blackboard import Board, Fact
from originweave.report import ReportError, derive_report, parse_severity, render_report


def _deviation(
    fid: str, *, severity: str, confidence: float, url: str, quote: str = "q"
) -> Fact:
    return Fact.from_dict(
        {
            "id": fid,
            "kind": "deviation",
            "label": f"deviation {fid}",
            "subtitle": f"severity={severity} \u00b7 confidence={confidence:.2f}",
            "status": "flagged" if severity == "high" else "review",
            "confidence": confidence,
            "note": f"note {fid}",
            "evidence": [
                {"id": "ev1", "quote": quote, "sourceTitle": "src", "url": url, "locator": "p.1"}
            ],
        }
    )


def _board(*facts: Fact, verdict: str | None = None) -> Board:
    origin = Fact.from_dict({"id": "origin", "kind": "origin", "label": "A"})
    goal = Fact.from_dict({"id": "goal", "kind": "goal", "label": "G"})
    return Board(origin=origin, goal=goal, facts=list(facts), verdict=verdict)


def test_parse_severity_reads_the_subtitle() -> None:
    fact = _deviation("d1", severity="medium", confidence=0.7, url="u")
    assert parse_severity(fact) == "medium"


def test_parse_severity_rejects_a_missing_prefix() -> None:
    fact = _deviation("d1", severity="high", confidence=0.9, url="u")
    fact.subtitle = "no severity here"
    with pytest.raises(ReportError, match="severity="):
        parse_severity(fact)


def test_parse_severity_rejects_an_unknown_level() -> None:
    fact = _deviation("d1", severity="high", confidence=0.9, url="u")
    fact.subtitle = "severity=critical \u00b7 confidence=0.90"
    with pytest.raises(ReportError):
        parse_severity(fact)


def test_derive_report_collects_findings_and_dedups_sources() -> None:
    d1 = _deviation("d1", severity="high", confidence=0.9, url="https://a", quote="x")
    d2 = _deviation("d2", severity="low", confidence=0.6, url="https://a", quote="x")
    report = derive_report(_board(d1, d2, verdict="部分偏差"), run_id="run_001")

    assert [finding.id for finding in report.findings] == ["d1", "d2"]
    assert [finding.severity for finding in report.findings] == ["high", "low"]
    assert report.verdict == "部分偏差"
    assert report.runId == "run_001"
    assert len(report.sources) == 1  # same (url, quote) dedups


def test_derive_report_is_deterministic() -> None:
    board = _board(_deviation("d1", severity="high", confidence=0.9, url="u"), verdict="v")
    first = derive_report(board, run_id="r1").to_dict()
    second = derive_report(board, run_id="r1").to_dict()
    assert first == second


def test_derive_report_without_deviations() -> None:
    report = derive_report(_board(verdict="clean"), run_id="r1")
    assert report.findings == []
    assert report.sources == []


def test_render_report_contains_verdict_and_findings() -> None:
    board = _board(_deviation("d1", severity="high", confidence=0.9, url="https://a"))
    text = render_report(derive_report(board, run_id="run_001"))
    assert "run_001" in text
    assert "d1" in text
    assert "high" in text
    assert "https://a" in text
