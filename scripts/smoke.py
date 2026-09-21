"""Smoke test for the run API: boot the ASGI app with a fake worker and drive a run.

It runs entirely in-process (no network, no real provider): start a run, resolve Gate A
(and Gate C), and print the resulting board summary. Exits non-zero when the run does not
reach the expected terminal state. This is the `make smoke` target (M1c-2b 2b-5).
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

from originweave.capabilities.base import PromptTemplate
from originweave.capabilities.worker import LocalWorker
from originweave.config import Config, WorkerConfig
from originweave.persistence import Project, ProjectRegistry
from originweave.server import Providers, ServerContext, create_app
from originweave.server.service import Service

SERVICE = "/originweave.v1.OriginweaveService"
HEADERS = {"Content-Type": "application/json"}
NO_REASON = json.dumps({"facts": [], "intents": [], "complete": None})


class _ScriptedModel:
    name = "smoke"

    def __init__(self, *replies: str) -> None:
        self._replies = list(replies)

    async def complete(self, messages: Sequence[object]) -> str:
        return self._replies.pop(0) if self._replies else NO_REASON


class _NoSearch:
    name = "smoke"

    async def search(self, query: str, *, num_results: int = 8) -> str:
        return ""


class _FakePrompt:
    name = "smoke"

    async def get(self, name: str) -> PromptTemplate:
        return PromptTemplate(name=name, text=name.upper())


def _replies() -> tuple[str, ...]:
    """A scripted run: Bootstrap → decompose → verify/compare → COMPLETE."""
    bootstrap = json.dumps(
        {
            "facts": [
                {
                    "label": "Copilot cut task time by 55%",
                    "kind": "fact",
                    "role": "main-claim",
                    "status": "open",
                    "confidence": 0.6,
                }
            ],
            "intents": [],
            "complete": None,
        }
    )
    reason_decompose = json.dumps(
        {
            "facts": [],
            "intents": [{"type": "decompose", "from": "f1", "question": "Split f1."}],
            "complete": None,
        }
    )
    keep = json.dumps({"keep": [0], "drop": []})
    sub_claim = json.dumps(
        {
            "facts": [
                {
                    "label": "the 55% figure is well scoped",
                    "kind": "fact",
                    "role": "sub-claim",
                    "status": "open",
                    "confidence": 0.5,
                }
            ],
            "intents": [],
            "complete": None,
        }
    )
    reason_verify = json.dumps(
        {
            "facts": [],
            "intents": [{"type": "verify", "from": "f2", "question": "Compare f2."}],
            "complete": None,
        }
    )
    compare = json.dumps(
        {
            "facts": [
                {
                    "key": "cmp",
                    "label": "compare (facts x sources x goal)",
                    "kind": "compare",
                    "role": "none",
                    "status": "verified",
                    "confidence": 0.8,
                },
                {
                    "key": "dev1",
                    "label": "wrong attribution",
                    "kind": "deviation",
                    "role": "none",
                    "status": "flagged",
                    "confidence": 0.9,
                    "subtitle": "severity=high \u00b7 confidence=0.90",
                    "evidence": [
                        {
                            "quote": "55%",
                            "sourceTitle": "Lab study",
                            "url": "https://example.com/lab",
                            "locator": "p.1",
                        }
                    ],
                },
            ],
            "edges": [
                {"source": "f2", "target": "cmp", "relation": "dependency", "note": "verify"},
                {"source": "goal", "target": "dev1", "relation": "goal-derived", "note": "dev"},
            ],
            "intents": [],
            "complete": None,
        }
    )
    complete = json.dumps(
        {"facts": [], "intents": [], "complete": {"verdict": "\u90e8\u5206\u504f\u5dee"}}
    )
    return (bootstrap, reason_decompose, keep, sub_claim, reason_verify, keep, compare, complete)


async def _post(client: httpx.AsyncClient, method: str, body: dict[str, Any]) -> httpx.Response:
    return await client.post(f"{SERVICE}/{method}", content=json.dumps(body), headers=HEADERS)


async def _main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ProjectRegistry(root / "projects", root / "runs").write(Project(id="smoke", name="Smoke"))
        providers = Providers(
            worker=LocalWorker(model=_ScriptedModel(*_replies())),
            search=_NoSearch(),
            prompt=_FakePrompt(),
        )
        ctx = ServerContext.build(
            # The smoke run is in-process by design: force the injected fake worker
            # instead of the production container backend (the config default).
            config=Config(worker=WorkerConfig(execution="in-process", container_scope="per-call")),
            providers=providers,
            root=root,
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(service=Service(ctx))),
            base_url="http://smoke",
        ) as client:
            created = await _post(
                client,
                "CreateRun",
                {
                    "projectId": "smoke",
                    "sourceType": "text",
                    "sourceText": "Copilot cut task time by 55%.",
                    "goal": "Every claim is sourced.",
                },
            )
            if created.status_code != 200:
                print(f"FAIL CreateRun: {created.status_code} {created.text}", file=sys.stderr)
                return 1
            run_id = str((created.json().get("run") or {}).get("id", ""))
            if not run_id:
                print("FAIL: CreateRun returned no run id", file=sys.stderr)
                return 1
            await ctx.scheduler.wait(run_id)

            paused = (await _post(client, "GetRun", {"runId": run_id})).json()["runDetail"]
            status = paused["run"]["status"]
            if status != "awaiting_human":
                print(
                    f"FAIL: expected awaiting_human after Bootstrap, got {status}",
                    file=sys.stderr,
                )
                return 1
            gate = (paused.get("waitingFor") or {}).get("gate", "")
            print(f"run {run_id}: status={status} gate={gate}")

            approved = await _post(
                client,
                "SubmitHumanInput",
                {"runId": run_id, "gate": "confirm-claim", "decision": "approve"},
            )
            if approved.status_code != 200:
                print(
                    f"FAIL SubmitHumanInput: {approved.status_code} {approved.text}",
                    file=sys.stderr,
                )
                return 1
            await ctx.scheduler.drain()

            detail = (await _post(client, "GetRun", {"runId": run_id})).json()["runDetail"]

            # Gate C: confirm the final scorecard before COMPLETE and report.md are written.
            if detail["run"]["status"] == "awaiting_human":
                review = (detail.get("waitingFor") or {}).get("gate", "")
                print(f"run {run_id}: status=awaiting_human gate={review}")
                confirmed = await _post(
                    client,
                    "SubmitHumanInput",
                    {"runId": run_id, "gate": review, "decision": "approve"},
                )
                if confirmed.status_code != 200:
                    print(
                        f"FAIL SubmitHumanInput: {confirmed.status_code} {confirmed.text}",
                        file=sys.stderr,
                    )
                    return 1
                await ctx.scheduler.drain()
                detail = (await _post(client, "GetRun", {"runId": run_id})).json()["runDetail"]

    status = detail["run"]["status"]
    kinds = [fact["kind"] for fact in detail["facts"]]
    verdict = detail.get("report", {}).get("verdict", "")
    findings = len(detail.get("report", {}).get("findings", []))
    print(f"run {run_id}: status={status} facts={len(detail['facts'])} kinds={sorted(set(kinds))}")
    print(f"report.md verdict={verdict!r} findings={findings}")

    if status != "completed" or "compare" not in kinds or "deviation" not in kinds:
        print("FAIL: run did not reach a scored COMPLETE", file=sys.stderr)
        return 1
    print("smoke OK")
    return 0


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
