"""Startup and shutdown for the CREAO layer (wired into app.main's lifespan)."""

import asyncio
import contextlib
import logging

from app.creao import bridge, db, dispatch, hub
from app.creao.mcp import mount as mcp_mount

log = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def lifespan(app):
    tasks: list[asyncio.Task] = []
    stack = contextlib.AsyncExitStack()
    try:
        await db.init_db()
        await hub.start()
        tasks.append(asyncio.create_task(dispatch.run_chase_loop(), name="chase"))
        await bridge.orchestrator.start()
        if mcp_mount is not None:
            await stack.enter_async_context(mcp_mount.lifespan())
    except Exception:  # the pre-plan agent must keep working even if the live layer can't start
        log.exception("CREAO layer failed to start")
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        await stack.aclose()
        await bridge.orchestrator.stop()
        await hub.stop()
