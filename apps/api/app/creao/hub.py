"""Live events, streamed out of TigerData.

On TigerData (Postgres) every live message travels through the database:

- Triggers on incident_events, evac_events and hazards call pg_notify('creao_live', ...) on every
  INSERT. So whatever writes the ElevenLabs/Photon data into TigerData (this API, or Sai's
  pipeline writing rows directly), the change is streamed.
- Decisions made in the API (route approved, evacuation started, ...) are published with
  SELECT pg_notify(...) too.
- One LISTEN connection per API instance fans the messages out to the dashboard's SSE stream and
  to the CREAO orchestrator.

With SQLite (laptop without a database) the same messages go through an in-process queue.
Message shape: {"type", "building_id", "incident_id", "data", "at"}.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator

from sqlalchemy import text

from app.creao.db import engine, utcnow

log = logging.getLogger(__name__)
CHANNEL = "creao_live"
MAX_PAYLOAD = 7500  # Postgres NOTIFY payloads must stay under 8000 bytes

_subscribers: set[asyncio.Queue] = set()
_listener: asyncio.Task | None = None
state = {"backend": "memory", "listening": False}


def _fanout(message: dict) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(message)
        except asyncio.QueueFull:
            log.warning("live subscriber is behind; dropping %s", message.get("type"))


def _encode(message: dict) -> str:
    raw = json.dumps(message, default=str)
    if len(raw.encode()) <= MAX_PAYLOAD:
        return raw
    slim = {**message, "data": {"truncated": True}}  # readers refetch the full state
    return json.dumps(slim, default=str)


async def publish(
    kind: str,
    *,
    building_id: str | None = None,
    incident_id: str | None = None,
    data: dict | None = None,
) -> None:
    message = {
        "type": kind,
        "building_id": building_id,
        "incident_id": incident_id,
        "data": data or {},
        "at": utcnow().isoformat(),
    }
    if state["backend"] != "tigerdata":
        _fanout(message)
        return
    try:
        async with engine().connect() as conn:
            await conn.execute(
                text("SELECT pg_notify(:c, :p)"), {"c": CHANNEL, "p": _encode(message)}
            )
            await conn.commit()
    except Exception:  # live fan-out must never break a write
        log.exception("pg_notify failed; delivering locally")
        _fanout(message)


async def send_texts(building_id: str, recipients: list[dict], reason: str) -> None:
    """One occupant.message per person (the messenger texts each). One event per text keeps every
    payload far under NOTIFY's 8 KB, however many people are in the building."""
    for r in recipients:
        await publish("occupant.message", building_id=building_id, data={**r, "reason": reason})


async def _listen_forever(dsn: str) -> None:
    import asyncpg

    def on_notify(_conn, _pid, _channel, payload: str) -> None:
        try:
            _fanout(json.loads(payload))
        except ValueError:
            log.warning("bad live payload: %s", payload[:200])

    while True:
        try:
            conn = await asyncpg.connect(dsn)
            await conn.add_listener(CHANNEL, on_notify)
            state["listening"] = True
            log.info("Listening to TigerData channel %s", CHANNEL)
            while not conn.is_closed():
                await asyncio.sleep(5)
                await conn.execute("SELECT 1")  # keepalive; raises if the link dropped
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("TigerData LISTEN dropped (%s); reconnecting", e)
        state["listening"] = False
        await asyncio.sleep(2)


async def start() -> None:
    global _listener
    url = engine().url
    if url.get_backend_name() != "postgresql":
        return
    state["backend"] = "tigerdata"
    # ?ssl=require is SQLAlchemy's asyncpg spelling; a raw asyncpg DSN only knows libpq's sslmode and
    # sends ssl to the server as a setting, which Tiger Cloud refuses (no LISTEN, so no live events)
    query = dict(url.query)
    if "ssl" in query and "sslmode" not in query:
        query["sslmode"] = query.pop("ssl")
    dsn = url.set(drivername="postgresql", query=query).render_as_string(hide_password=False)
    _listener = asyncio.create_task(_listen_forever(dsn), name="tigerdata-listen")


async def stop() -> None:
    if _listener:
        _listener.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _listener


@contextlib.asynccontextmanager
async def subscribe() -> AsyncIterator[asyncio.Queue]:
    q: asyncio.Queue = asyncio.Queue(maxsize=1000)
    _subscribers.add(q)
    try:
        yield q
    finally:
        _subscribers.discard(q)


def subscriber_count() -> int:
    return len(_subscribers)
