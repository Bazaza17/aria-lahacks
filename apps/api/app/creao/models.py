"""Tables for the CREAO layer.

incidents        one per caller or texter who reports something (a pin on the scan)
incident_events  everything they said and everything that happened to them (hypertable)
occupants        the roll call: who is in the building and whether they're confirmed out
hazards          what people reported, what the fire model predicts, what a dispatcher verified
evac_events      every roll-call change, with the exit used (hypertable -> exit flow aggregate)
evacuations      a declared fire or labeled drill: the approved routes and the live report
route_proposals  route changes waiting for a dispatcher
agent_runs       every task the CREAO command staff worked on, and each tool call they made
inbound_events   idempotency for Sai's event envelope
"""

import enum
import uuid

from sqlalchemy import JSON, Boolean, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.creao.db import Base, UTCDateTime, utcnow

JSONType = JSON().with_variant(JSONB(), "postgresql")


def _id() -> str:
    return uuid.uuid4().hex


class Severity(enum.StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class OccupantStatus(enum.StrEnum):
    unconfirmed = "unconfirmed"  # the default: silence is never safe
    contacted = "contacted"  # replied or answered, not confirmed out
    needs_help = "needs_help"
    confirmed_safe = "confirmed_safe"  # only the person (SAFE) or a dispatcher


class Verification(enum.StrEnum):
    reported = "reported"
    model_predicted = "model_predicted"
    dispatcher_verified = "dispatcher_verified"


class ProposalStatus(enum.StrEnum):
    proposed = "proposed"
    approved = "approved"
    rejected = "rejected"
    stale = "stale"


def _enum(e):
    return Enum(e, native_enum=False, length=32)


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    building_id: Mapped[str] = mapped_column(String(64), index=True)
    channel: Mapped[str] = mapped_column(String(16), default="voice")  # voice | sms
    caller: Mapped[str | None] = mapped_column(String(32), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | ended
    severity: Mapped[Severity] = mapped_column(_enum(Severity), default=Severity.low)
    headline: Mapped[str | None] = mapped_column(String(300))
    category: Mapped[str | None] = mapped_column(String(32))
    facts: Mapped[dict] = mapped_column(JSONType, default=dict)
    location: Mapped[dict | None] = mapped_column(JSONType)
    handoff: Mapped[dict | None] = mapped_column(JSONType)
    acknowledged_by: Mapped[str | None] = mapped_column(String(64))
    assigned_unit: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[object] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    updated_at: Mapped[object] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    ended_at: Mapped[object | None] = mapped_column(UTCDateTime())


class IncidentEvent(Base):
    __tablename__ = "incident_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    created_at: Mapped[object] = mapped_column(UTCDateTime(), primary_key=True, default=utcnow)
    incident_id: Mapped[str] = mapped_column(String(32), index=True)
    building_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(
        String(24)
    )  # transcript | sms_in | sms_out | detail | flag | note | status
    role: Mapped[str | None] = mapped_column(
        String(16)
    )  # caller | agent | dispatcher | system | creao
    text: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSONType, default=dict)


class CommsEvent(Base):
    """Every text and call line, in and out, for everyone in the building (a TigerData hypertable)."""

    __tablename__ = "comms_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    created_at: Mapped[object] = mapped_column(UTCDateTime(), primary_key=True, default=utcnow)
    building_id: Mapped[str] = mapped_column(String(64), index=True)
    evacuation_id: Mapped[str | None] = mapped_column(String(32))
    occupant_id: Mapped[str | None] = mapped_column(String(32), index=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    channel: Mapped[str] = mapped_column(String(8))  # sms | voice
    direction: Mapped[str] = mapped_column(String(4))  # in | out
    role: Mapped[str] = mapped_column(String(16))  # person | agent | aria | dispatcher
    kind: Mapped[str] = mapped_column(
        String(24)
    )  # text | line | call_started | call_ended | call_transferred
    text: Mapped[str | None] = mapped_column(Text)
    conversation_id: Mapped[str | None] = mapped_column(String(128))
    trigger: Mapped[str | None] = mapped_column(String(64))  # words that bring in a human
    intent: Mapped[str | None] = mapped_column(String(24))  # evacuating | directions | help | safe


class Occupant(Base):
    __tablename__ = "occupants"
    __table_args__ = (UniqueConstraint("building_id", "phone"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    building_id: Mapped[str] = mapped_column(String(64), index=True)
    phone: Mapped[str] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[OccupantStatus] = mapped_column(
        _enum(OccupantStatus), default=OccupantStatus.unconfirmed
    )
    mobility: Mapped[list] = mapped_column(JSONType, default=list)
    location: Mapped[dict | None] = mapped_column(JSONType)
    exit_id: Mapped[str | None] = mapped_column(String(64))
    incident_id: Mapped[str | None] = mapped_column(String(32))
    last_instruction: Mapped[str | None] = mapped_column(Text)
    alerted_at: Mapped[object | None] = mapped_column(UTCDateTime())
    last_contact_at: Mapped[object | None] = mapped_column(UTCDateTime())
    call_requested_at: Mapped[object | None] = mapped_column(UTCDateTime())
    updated_at: Mapped[object] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class Hazard(Base):
    __tablename__ = "hazards"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    building_id: Mapped[str] = mapped_column(String(64), index=True)
    zone_id: Mapped[str | None] = mapped_column(String(64))
    exit_id: Mapped[str | None] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32))  # fire_hazard | blocked | violence
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(64))  # sms | call | dispatcher | creao:<role>
    verification: Mapped[Verification] = mapped_column(
        _enum(Verification), default=Verification.reported
    )
    verified_by: Mapped[str | None] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[object] = mapped_column(UTCDateTime(), default=utcnow)


class EvacEvent(Base):
    __tablename__ = "evac_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    created_at: Mapped[object] = mapped_column(UTCDateTime(), primary_key=True, default=utcnow)
    building_id: Mapped[str] = mapped_column(String(64), index=True)
    occupant_id: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    exit_id: Mapped[str | None] = mapped_column(String(64))


class Evacuation(Base):
    __tablename__ = "evacuations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    building_id: Mapped[str] = mapped_column(String(64), index=True)
    mode: Mapped[str] = mapped_column(String(8), default="drill")  # drill | live
    status: Mapped[str] = mapped_column(String(8), default="active")  # active | ended
    origin_label: Mapped[str | None] = mapped_column(String(120))
    origin_zone: Mapped[str | None] = mapped_column(String(64))
    origin_exit: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    started_by: Mapped[str | None] = mapped_column(String(64))
    approved_routes: Mapped[dict] = mapped_column(JSONType, default=dict)  # zone_id -> exit_id
    fire_model: Mapped[dict | None] = mapped_column(JSONType)
    hazard_version: Mapped[int] = mapped_column(Integer, default=0)
    report: Mapped[dict] = mapped_column(JSONType, default=dict)  # section -> {text, role, by, at}
    started_at: Mapped[object] = mapped_column(UTCDateTime(), default=utcnow)
    ended_at: Mapped[object | None] = mapped_column(UTCDateTime())


class RouteProposal(Base):
    __tablename__ = "route_proposals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    evacuation_id: Mapped[str] = mapped_column(ForeignKey("evacuations.id"), index=True)
    building_id: Mapped[str] = mapped_column(String(64), index=True)
    zone_id: Mapped[str] = mapped_column(String(64))
    from_exit_id: Mapped[str | None] = mapped_column(String(64))
    to_exit_id: Mapped[str | None] = mapped_column(String(64))  # None = shelter in place
    rationale: Mapped[str] = mapped_column(Text)
    affected: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[ProposalStatus] = mapped_column(
        _enum(ProposalStatus), default=ProposalStatus.proposed
    )
    proposed_by: Mapped[str] = mapped_column(String(64), default="rules")
    hazard_version: Mapped[int] = mapped_column(Integer, default=0)
    decided_by: Mapped[str | None] = mapped_column(String(64))
    decided_at: Mapped[object | None] = mapped_column(UTCDateTime())
    created_at: Mapped[object] = mapped_column(UTCDateTime(), default=utcnow)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    building_id: Mapped[str | None] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(32))
    parent_id: Mapped[str | None] = mapped_column(String(32))
    task: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), default="queued"
    )  # queued | running | done | failed
    trigger: Mapped[str | None] = mapped_column(String(200))
    creao_run_id: Mapped[str | None] = mapped_column(String(128))
    summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    actions: Mapped[list] = mapped_column(JSONType, default=list)
    created_at: Mapped[object] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    finished_at: Mapped[object | None] = mapped_column(UTCDateTime())


class InboundEvent(Base):
    __tablename__ = "inbound_events"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    event_type: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[object] = mapped_column(UTCDateTime(), default=utcnow)
