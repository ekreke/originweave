"""Runtime execution backend (M3a): container-per-worker.

Engine/Dispatcher stay in the server process (orchestration + the sole blackboard
writer, red lines 2/4); each :meth:`Worker.run` call is executed in one short-lived
container (red line 3). ``ContainerWorker`` implements the same ``Worker`` protocol as
the in-process ``LocalWorker``/``PiWorker``, so the engine is unchanged.
"""

from __future__ import annotations

from .container import ContainerError, ContainerHandle, ContainerManager, ContainerWorker

__all__ = [
    "ContainerError",
    "ContainerHandle",
    "ContainerManager",
    "ContainerWorker",
]
