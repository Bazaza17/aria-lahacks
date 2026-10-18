"""TigerData (TimescaleDB) features, applied at startup when the extension is available.

- incident_events, evac_events and comms_events become hypertables (append-only time series).
  comms_events holds every text and call line, in and out, for everyone in the building.
- Columnstore compression on chunks older than a day.
- evac_flow_15s: a real-time continuous aggregate of roll-call changes per exit, which is what the
  dispatcher's "most people leaving via ..." and the evacuation curve read.
- comms_1m: a real-time continuous aggregate of texts, call lines, calls, transfers and trigger
  words per minute (the comms panel and the CREAO staff read it).

Each step runs in a savepoint, so plain Postgres (or Supabase without the extension) just skips it.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncConnection

log = logging.getLogger(__name__)


async def _try(conn: AsyncConnection, label: str, *statements: str) -> bool:
    try:
        async with conn.begin_nested():
            for sql in statements:
                await conn.exec_driver_sql(sql)
        return True
    except Exception as e:  # noqa: BLE001
        log.info("TimescaleDB step %r skipped: %s", label, str(e).splitlines()[0])
        return False


# Every row the pipeline writes is streamed: INSERT -> pg_notify('creao_live', ...). Plain Postgres
# feature, so it also works on Supabase.
NOTIFY_SQL = [
    """CREATE OR REPLACE FUNCTION creao_notify_incident_event() RETURNS trigger AS $$
       DECLARE p text;
       BEGIN
         p := json_build_object(
           'type', 'incident.event', 'building_id', NEW.building_id, 'incident_id', NEW.incident_id,
           'data', json_build_object('id', NEW.id, 'kind', NEW.kind, 'role', NEW.role,
                                     'text', left(NEW.text, 1500), 'data', NEW.data),
           'at', NEW.created_at)::text;
         IF octet_length(p) > 7900 THEN  -- NOTIFY caps payloads at 8000 bytes; never fail the write
           p := json_build_object('type', 'incident.event', 'building_id', NEW.building_id,
                                  'incident_id', NEW.incident_id, 'at', NEW.created_at,
                                  'data', json_build_object('id', NEW.id, 'kind', NEW.kind, 'truncated', true))::text;
         END IF;
         PERFORM pg_notify('creao_live', p);
         RETURN NEW;
       END $$ LANGUAGE plpgsql""",
    """CREATE OR REPLACE FUNCTION creao_notify_evac_event() RETURNS trigger AS $$
       BEGIN
         PERFORM pg_notify('creao_live', json_build_object(
           'type', 'roll_call.changed', 'building_id', NEW.building_id, 'incident_id', NULL,
           'data', json_build_object('occupant_id', NEW.occupant_id, 'status', NEW.status, 'exit_id', NEW.exit_id),
           'at', NEW.created_at)::text);
         RETURN NEW;
       END $$ LANGUAGE plpgsql""",
    """CREATE OR REPLACE FUNCTION creao_notify_hazard() RETURNS trigger AS $$
       BEGIN
         PERFORM pg_notify('creao_live', json_build_object(
           'type', 'hazard.reported', 'building_id', NEW.building_id, 'incident_id', NULL,
           'data', json_build_object('hazard_id', NEW.id, 'category', NEW.category, 'zone_id', NEW.zone_id,
                                     'exit_id', NEW.exit_id, 'text', left(NEW.text, 500), 'source', NEW.source,
                                     'verification', NEW.verification),
           'at', NEW.created_at)::text);
         RETURN NEW;
       END $$ LANGUAGE plpgsql""",
    """CREATE OR REPLACE FUNCTION creao_notify_comms_event() RETURNS trigger AS $$
       BEGIN
         PERFORM pg_notify('creao_live', json_build_object(
           'type', 'comms.event', 'building_id', NEW.building_id, 'incident_id', NULL,
           'data', json_build_object('id', NEW.id, 'occupant_id', NEW.occupant_id, 'channel', NEW.channel,
                                     'direction', NEW.direction, 'role', NEW.role, 'kind', NEW.kind,
                                     'text', left(NEW.text, 600), 'trigger', NEW.trigger, 'intent', NEW.intent,
                                     'conversation_id', NEW.conversation_id),
           'at', NEW.created_at)::text);
         RETURN NEW;
       END $$ LANGUAGE plpgsql""",
    "DROP TRIGGER IF EXISTS creao_live_comms_events ON comms_events",
    "CREATE TRIGGER creao_live_comms_events AFTER INSERT ON comms_events "
    "FOR EACH ROW EXECUTE FUNCTION creao_notify_comms_event()",
    "DROP TRIGGER IF EXISTS creao_live_incident_events ON incident_events",
    "CREATE TRIGGER creao_live_incident_events AFTER INSERT ON incident_events "
    "FOR EACH ROW EXECUTE FUNCTION creao_notify_incident_event()",
    "DROP TRIGGER IF EXISTS creao_live_evac_events ON evac_events",
    "CREATE TRIGGER creao_live_evac_events AFTER INSERT ON evac_events "
    "FOR EACH ROW EXECUTE FUNCTION creao_notify_evac_event()",
    "DROP TRIGGER IF EXISTS creao_live_hazards ON hazards",
    "CREATE TRIGGER creao_live_hazards AFTER INSERT ON hazards FOR EACH ROW EXECUTE FUNCTION creao_notify_hazard()",
]


async def setup(conn: AsyncConnection) -> dict:
    status: dict = {"timescaledb": False}
    status["notify_triggers"] = await _try(conn, "notify triggers", *NOTIFY_SQL)
    available = (
        await conn.exec_driver_sql(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'"
        )
    ).scalar()
    if not (
        available and await _try(conn, "extension", "CREATE EXTENSION IF NOT EXISTS timescaledb")
    ):
        return status
    status["timescaledb"] = True
    for table, segment in (
        ("incident_events", "incident_id"),
        ("evac_events", "building_id"),
        ("comms_events", "building_id"),
    ):
        ok = await _try(
            conn,
            f"{table} hypertable",
            f"SELECT create_hypertable('{table}', by_range('created_at', INTERVAL '1 day'), "
            "if_not_exists => TRUE, migrate_data => TRUE)",
        )
        status[f"{table}_hypertable"] = ok
        if ok:
            await _try(
                conn,
                f"{table} columnstore",
                f"ALTER TABLE {table} SET (timescaledb.enable_columnstore = true, "
                f"timescaledb.segmentby = '{segment}', timescaledb.orderby = 'created_at DESC')",
                f"CALL add_columnstore_policy('{table}', after => INTERVAL '1 day', if_not_exists => true)",
            )
    status["evac_flow_15s"] = status.get("evac_events_hypertable", False) and await _try(
        conn,
        "evac_flow_15s",
        """CREATE MATERIALIZED VIEW IF NOT EXISTS evac_flow_15s
           WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
           SELECT time_bucket(INTERVAL '15 seconds', created_at) AS bucket, building_id, status, exit_id,
                  count(*) AS events
           FROM evac_events GROUP BY bucket, building_id, status, exit_id
           WITH NO DATA""",
        """SELECT add_continuous_aggregate_policy('evac_flow_15s', start_offset => INTERVAL '2 hours',
               end_offset => INTERVAL '15 seconds', schedule_interval => INTERVAL '30 seconds',
               if_not_exists => true)""",
    )
    status["comms_1m"] = status.get("comms_events_hypertable", False) and await _try(
        conn,
        "comms_1m",
        """CREATE MATERIALIZED VIEW IF NOT EXISTS comms_1m
           WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
           SELECT time_bucket(INTERVAL '1 minute', created_at) AS bucket, building_id,
                  sum(CASE WHEN channel = 'sms' AND direction = 'in' THEN 1 ELSE 0 END) AS texts_in,
                  sum(CASE WHEN channel = 'sms' AND direction = 'out' THEN 1 ELSE 0 END) AS texts_out,
                  sum(CASE WHEN kind = 'line' THEN 1 ELSE 0 END) AS call_lines,
                  sum(CASE WHEN kind = 'call_started' THEN 1 ELSE 0 END) AS calls,
                  sum(CASE WHEN kind = 'call_transferred' THEN 1 ELSE 0 END) AS transfers,
                  sum(CASE WHEN trigger IS NOT NULL THEN 1 ELSE 0 END) AS triggers
           FROM comms_events GROUP BY bucket, building_id
           WITH NO DATA""",
        """SELECT add_continuous_aggregate_policy('comms_1m', start_offset => INTERVAL '2 hours',
               end_offset => INTERVAL '1 minute', schedule_interval => INTERVAL '30 seconds',
               if_not_exists => true)""",
    )
    return status
