"""The demo's headline numbers (summary dict) and their readable text (summary_text)."""

from __future__ import annotations

import re

from engine.aria_venue import NON_WALKING_KINDS, AriaVenue
from engine.fire import Timeline
from engine.routes import FLASHOVER_LAYER_C

# Open connections whose notes say they may really be closed (or not there): worth a
# `--door ID=closed` run before trusting the numbers.
_UNCERTAIN_RE = re.compile(
    r"UNVERIFIED|may be|close on alarm|medium confidence|\bLOW\b|unconfirmed", re.IGNORECASE
)
_SPEC_KEYS = ("t0_s", "plan", "counts", "occupants_at_risk", "untenable_at_departure")
_LIST_KEYS = ("trapped", "trapped_by_origin_only", "partial", "reactive_cut_off")


def _mmss(t: float | None) -> str:
    if t is None:
        return "  -  "
    t = int(round(t))
    return f"{t // 60:2d}:{t % 60:02d}"


def ways_down(av: AriaVenue) -> dict[str, list[dict]]:
    """Per upper storey, every walkable stair to a lower one, and where it lands."""
    out: dict[str, list[dict]] = {}
    for oid, o in av.openings.items():
        if o.get("kind") != "stair" or oid in av.graph.excluded:
            continue
        a, b = o.get("a"), o.get("b")
        ea, eb = (av.spaces[s].get("floor_elevation") or 0.0 for s in (a, b))
        upper, lower = (a, b) if ea > eb else (b, a)
        lands = av.room_of.get(lower, "outdoors")
        out.setdefault(av.spaces[upper].get("storey"), []).append(
            {"stair": oid, "from": upper, "to": lower, "lands_in": lands}
        )
    return out


def uncertain_open(av: AriaVenue) -> list[str]:
    return sorted(
        oid
        for oid, st in av.door_states.items()
        if st["open"]
        and st["category"] in ("event_door", "open_connection")
        and _UNCERTAIN_RE.search(av.openings[oid].get("notes") or "")
    )


def _first(rows: list[tuple[float, str]]) -> dict | None:
    rows = [r for r in rows if r[0] is not None]
    if not rows:
        return None
    t, sid = min(rows)
    return {"t_s": t, "space": sid}


def _flashovers(tl: Timeline, av: AriaVenue) -> list[dict]:
    out = []
    for rid, r in tl.rooms.items():
        t = r["flashover_s"]
        if t is None:
            continue
        before = tl.frames[max(t - 1, 0)]["rooms"][rid]["layer_temp_c"] if tl.frames else 0
        how = f"upper layer {FLASHOVER_LAYER_C:.0f} °C" if before >= FLASHOVER_LAYER_C else "Thomas"
        spaces = av.spaces_of.get(rid) or [rid]
        out.append({"t_s": t, "fire_room": rid, "spaces": spaces, "criterion": how})
    return sorted(out, key=lambda x: x["t_s"])


def _settles(counts: list[int], scan: list[dict]) -> float | None:
    """First scanned departure time from which an exit's reach stays at its final count."""
    if not counts or len(counts) != len(scan) or counts[0] == counts[-1]:
        return None
    i = len(counts) - 1
    while i > 0 and counts[i - 1] == counts[-1]:
        i -= 1
    return scan[i]["t0_s"]


def build(
    av: AriaVenue,
    tl: Timeline,
    vt: dict,
    start: str,
    departures: list[dict],
    scan: list[dict],
    exits: list[dict],
) -> dict:
    drawn = [s for s in av.room_of if av.spaces[s].get("kind") not in NON_WALKING_KINDS]
    beyond = [s for s in drawn if s != start]
    sp = vt["spaces"]
    first_beyond = _first([(sp[s]["smoke_untenable_s"], s) for s in beyond])
    if first_beyond:
        first_beyond["by"] = sp[first_beyond["space"]]["untenable_by"]
    # The demo moment: where the plan saves the most people, before the first flashover (past
    # it the zone model is only indicative).
    first_fo = min(
        (r["flashover_s"] for r in tl.rooms.values() if r["flashover_s"] is not None), default=None
    )
    valid = [r for r in scan if first_fo is None or r["t0_s"] < first_fo]
    best = max(valid, key=lambda r: (r["saved_clear"], r["saved"], -r["t0_s"])) if valid else None
    moment = best if best and best["saved"] > 0 else None
    return {
        "origin": vt.get("origin"),
        "first_smoke_beyond_origin": _first([(sp[s]["smoke_enters_s"], s) for s in beyond]),
        "first_untenable": _first([(sp[s]["blocked_s"], s) for s in drawn]),
        "first_untenable_beyond_origin": first_beyond,
        "flashovers": _flashovers(tl, av),
        "merged_member_offsets": [
            {
                "space": s,
                "offset_m": sp[s]["floor_offset_m"],
                "untenable_s": sp[s]["smoke_untenable_s"],
            }
            for s in drawn
            if sp[s]["floor_offset_m"]
        ],
        "exits_lost": [e for e in exits if e["lost_s"] is not None],
        "exits_kept": [e["exit"] for e in exits if e["lost_s"] is None],
        "exit_reach": [
            {
                **{
                    k: e.get(k) for k in ("exit", "spaces_at_start", "reachable_until_s", "kept_by")
                },
                "down_to_kept_s": _settles(e.get("reachable_counts") or [], scan),
            }
            for e in exits
        ],
        "ways_down": ways_down(av),
        "uncertain_open_connections": uncertain_open(av),
        "departures": [
            {
                **{k: d[k] for k in _SPEC_KEYS},
                **{k: d[k] for k in _LIST_KEYS},
                "contrasts": d["contrasts"],
            }
            for d in departures
        ],
        "scan": [
            {k: r[k] for k in ("t0_s", "at_risk", "saved", "saved_clear", "plan")} for r in scan
        ],
        "best_moment": moment,
    }


# --- Text. ---
def text(result: dict) -> str:
    s = result["summary"]
    lines = _header(result)
    lines += ["", "Fire timeline (m:ss after ignition)", *_timeline(result)]
    lines += ["", *_exit_lines(s, result["scenario"]["departures_s"])]
    lines += ["", *_evacuation(s)]
    lines += ["", *_contrasts(s)]
    if result.get("sensitivity"):
        lines += ["", *_sensitivity(result)]
    return "\n".join(lines)


def _sensitivity(result: dict) -> list[str]:
    deps = "/".join(_mmss(t).strip() for t in result["scenario"]["departures_s"])
    lines = [f"Sensitivity: people at risk at {deps}, plan | reactive, first exit lost"]
    for row in result["sensitivity"]:
        name = "as modelled" if row["opening"] is None else f"{row['opening']} closed"
        plan = "/".join(str(x) for x in row["plan_at_risk"])
        react = "/".join(str(x) for x in row["reactive_at_risk"])
        lines.append(f"  {name:<34} {plan} | {react} | {_mmss(row['first_exit_lost_s']).strip()}")
    return lines


def _header(result: dict) -> list[str]:
    sc, ad, s = result["scenario"], result["adapter"], result["summary"]
    lines = [
        f"Aria engine slice 1: {result['building'].get('name', '')}",
        f"Fire starts in {sc['start_space']} (fire room {sc['fire_room']}), {sc['growth']} t² "
        f"growth, {sc['horizon_s']:.0f} s horizon.",
        f"Model: {ad['fire_rooms']} fire rooms, {ad['fire_doors']} fire doors, "
        f"{len(ad['stair_shafts'])} stair shafts; {ad['route_nodes']} route nodes, "
        f"{ad['route_arcs']} route arcs, {ad['route_legs']} door-to-door legs.",
    ]
    for rid, m in ad["merged_rooms"].items():
        lines.append(
            f"Merged {rid} ({m['why']}): {', '.join(m['spaces'])}; {m['floor_area_m2']:.0f} m² of "
            f"floor, {m['volume_m3']:.0f} m³ up to {m['top_elevation_m']:.2f} m, modelled as a "
            f"{m['box_area_m2']:.0f} m² x {m['box_height_m']:.2f} m box."
        )
    for storey, stairs in sorted(s["ways_down"].items()):
        down = ", ".join(f"{w['stair']} -> {w['to']} ({w['lands_in']})" for w in stairs)
        lines.append(f"Ways down from {storey}: {down}.")
    if s["uncertain_open_connections"]:
        lines.append(
            "Modelled open but uncertain in the data (try --door ID=closed): "
            + ", ".join(s["uncertain_open_connections"])
            + "."
        )
    return lines


def _timeline(result: dict) -> list[str]:
    s = result["summary"]
    fire = result["fire"]
    rows: list[tuple[float, str]] = []
    o = s["origin"]
    if o and o["limit_s"] is not None:
        zone = _mmss(o["zone_model_blocked_s"]).strip() if o["zone_model_blocked_s"] else "never"
        rows.append(
            (
                o["limit_s"],
                f"room of origin {o['space']} untenable: the fire reaches "
                f"{o['limit_kw']} kW, 2.5 kW/m² at 3 m (zone model alone: {zone})",
            )
        )
    for label, key in (
        ("first smoke beyond the room of origin", "first_smoke_beyond_origin"),
        ("first untenable beyond the room of origin", "first_untenable_beyond_origin"),
    ):
        row = s[key]
        if row:
            how = ""
            if row.get("by"):
                how = (
                    " (smoke-logged: layer below 2 m)"
                    if row["by"] == "smoke_layer"
                    else " (hot layer)"
                )
            rows.append((row["t_s"], f"{label}: {row['space']}{how}"))
    rows += [(f["t_s"], f"flashover: {f['fire_room']} ({f['criterion']})") for f in s["flashovers"]]
    rows += [
        (
            m["untenable_s"],
            f"untenable: {m['space']} (judged from its floor, {m['offset_m']:+.2f} m)",
        )
        for m in s["merged_member_offsets"]
        if m["untenable_s"] is not None
    ]
    rows += [(e["lost_s"], f"exit lost: {e['exit']} (from {e['from']})") for e in s["exits_lost"]]
    lines = [f"  {_mmss(t)}  {text}" for t, text in sorted(rows, key=lambda x: x[0])]
    if not s["flashovers"]:
        lines.append("     -   no flashover within the horizon")
    first_fo = fire["validity"]["first_flashover_s"]
    if first_fo is not None:
        lines.append(
            f"  after {_mmss(first_fo).strip()} (first flashover) the zone model's numbers "
            "are indicative only"
        )
    lines.append(f"  exits never lost themselves: {', '.join(s['exits_kept']) or 'none'}")
    return lines


def _exit_lines(s: dict, departures: list[float]) -> list[str]:
    lines = ["Exit reach (occupied spaces that can still get through each exit in time)"]
    for e in s["exit_reach"]:
        if not e["spaces_at_start"]:
            continue
        if e["reachable_until_s"] is None:
            kept = ", ".join(e["kept_by"])
            tail = f"still reachable at the horizon from {kept}"
            if e.get("down_to_kept_s") is not None:
                when = _mmss(e["down_to_kept_s"]).strip()
                tail = f"from {when} only from {kept} (still at the horizon)"
        else:
            until = _mmss(e["reachable_until_s"]).strip()
            tail = f"unreachable from every occupied space after {until}"
        n = e["spaces_at_start"]
        lines.append(f"  {e['exit']:<25} from {n:2d} occupied spaces at 0:00; {tail}")
    return lines


def _evacuation(s: dict) -> list[str]:
    lines = [
        "Evacuation by departure time. At risk = no route to SAFE, or still queued at an opening",
        "when it closes (SFPE door and stair flow). Plan = Aria's capacity-aware predictive plan.",
        "   t0    plan ok/partial/trapped (at risk) [candidate]      "
        "reactive ok/partial/cut off/trapped (at risk)",
    ]
    for d in s["departures"]:
        p, r = d["counts"]["predictive"], d["counts"]["reactive"]
        risk = d["occupants_at_risk"]
        lines.append(
            f"  {_mmss(d['t0_s'])}  {p['ok']:3d} / {p['partial']:2d} / {p['trapped']:3d} "
            f"({risk['predictive']:4d}) [{d['plan']['chosen']:<12}]   "
            f"{r['ok']:3d} / {r['partial']:2d} / {r['cut_off']:2d} / {r['trapped']:3d} "
            f"({risk['reactive']:4d})"
        )
    lines += [
        "",
        "Nobody in the group gets out under the plan (! untenable at departure; * the only way out "
        "is through the room of origin)",
    ]
    for d in s["departures"]:
        star = set(d["trapped_by_origin_only"])
        names = [f"{t}!" for t in d["untenable_at_departure"]]
        names += [f"{t}*" if t in star else t for t in d["trapped"]]
        lines.append(f"  {_mmss(d['t0_s'])}  {', '.join(names) or 'none'}")
    scan = s["scan"]
    if scan:
        pts = " ".join(
            f"{_mmss(r['t0_s']).strip()} {r['at_risk']['predictive']}/{r['at_risk']['reactive']}"
            for r in scan[:: max(1, len(scan) // 12)]
        )
        lines += ["", f"At risk by departure time, plan/reactive (scan): {pts}"]
    return lines


def _describe_reactive(r: dict) -> str:
    cut = r.get("cut_off")
    if r["status"] == "cut_off" and cut:
        return (
            f"cut off at {cut['opening']} ({_mmss(cut['reach_s']).strip()}, closed "
            f"{_mmss(cut['blocked_s']).strip()}, {cut['late_by_s']:.0f} s late)"
        )
    if r["status"] in ("partial", "trapped") and r.get("limited_by"):
        everyone = "all " if r["status"] == "trapped" else ""
        return f"{everyone}{r['at_risk']} still queued at {r['limited_by']} when it closes"
    return r["status"]


def _describe_plan(p: dict) -> str:
    if p["status"] == "trapped":
        return f"trapped ({p['reason']})"
    openings = p["path"][1:-1:2]
    inside = openings[: openings.index(p["exit"])] if p["exit"] in openings else openings
    via = inside[:4] + (["..."] if len(inside) > 4 else [])
    out = f"via {', '.join(via)} to {p['exit']}" if via else f"by {p['exit']}"
    if p["last_out_s"] is not None:
        out += f", last person out {_mmss(p['last_out_s']).strip()}"
    if p["status"] == "partial":
        out += f", {p['at_risk']} at risk"
    return out


def _contrasts(s: dict) -> list[str]:
    lines = ["Where the plan beats the reactive routes (people saved; ~ = within 10 s, marginal)"]
    rows = 0
    for d in s["departures"]:
        for c in d["contrasts"][:6]:
            mark = "~" if c["marginal"] else " "
            lines.append(
                f" {mark}{_mmss(d['t0_s'])}  {c['space']} ({c['occupants']}, saves {c['saved']}): "
                f"reactive {_describe_reactive(c['reactive'])}; "
                f"plan {_describe_plan(c['predictive'])}"
            )
            rows += 1
    if not rows:
        lines.append("  none at these departure times")
    m = s["best_moment"]
    if m:
        lines += [
            "",
            f"Best demo moment (departures scanned every {m['step_s']:.0f} s, before the first "
            f"flashover): leave at {_mmss(m['t0_s']).strip()}: the plan leaves "
            f"{m['at_risk']['predictive']} at risk, the reactive routes "
            f"{m['at_risk']['reactive']} ({m['saved_clear']} of the {m['saved']} saved by more "
            f"than 10 s). Run with --departures {m['t0_s']:.0f}.",
        ]
        for c in m["contrasts"][:4]:
            mark = "~" if c["marginal"] else " "
            r, p = c["reactive"], c["predictive"]
            lines.append(
                f"   {mark}{c['space']} ({c['occupants']}): reactive {r['status']} by "
                f"{r['exit']}, {r['at_risk']} at risk; plan {p['status']} by {p['exit']}, "
                f"{p['at_risk']} at risk"
            )
    return lines
