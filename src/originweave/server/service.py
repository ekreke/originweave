"""Connect service implementation (M1c-1).

The generated ``originweave.v1`` module provides ``OriginweaveService`` as a
:class:`typing.Protocol` whose default methods raise ``UNIMPLEMENTED``. We subclass
it so unimplemented RPCs keep that behaviour while we implement them milestone by
milestone; C1 only needs ``ListProjects`` (C2/C3 add persistence and the engine
wiring, which will inject providers/config here).
"""

from __future__ import annotations

from originweave.v1 import originweave_pb2 as pb
from originweave.v1.originweave_connect import OriginweaveService


class Service(OriginweaveService):  # type: ignore[misc]  # generated base is Any (mypy skips gen)
    """Minimal Connect service: an empty project registry for now (C2 fills it)."""

    async def list_projects(
        self, request: pb.ListProjectsRequest, ctx: object
    ) -> pb.ListProjectsResponse:
        return pb.ListProjectsResponse()
