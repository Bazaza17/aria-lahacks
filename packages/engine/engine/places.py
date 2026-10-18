"""Place lookup: plain words -> venue-frame points ("ping a place"). Stdlib only.

    from engine.places import build_index, load_raw, search, space_at
    places = build_index()                     # every space, opening, stair end and landmark
    search(places, "stairs first floor")       # {"ambiguous": True, "matches": [4 stair feet]}
    space_at(load_raw(), 14.3, -20.2, 0.62)    # "galleria_far_end"

    uv run python -m engine.places "stairs first floor" "main entrance"
    uv run python -m engine.places --index --out ../../apps/web/public/fire/places.json

A place's `point` is [x, elevation, z] in the venue frame (VENUE.md); on the scan, Y is
`floor_y + elevation`. The words and weights live in data/places_vocab.json. Search rules:
- An id, alias or event name said in full wins outright, before floor words are read, so
  "stairs to 2nd floor" is ST-W rather than "stairs" on the 2F.
- Floor words filter by storey. A floor word on its own ("upstairs") means that floor's stairs.
- Compass words are never resolved: north is unverified and the venue's own "west" is +x
  (VENUE.md), so "west exit" searches as "exit" and the result's note says so.
- Every place tied for best is returned; more than one feature among them is `ambiguous`.
"""

from __future__ import annotations

import argparse
import difflib
import json
import math
import re
import sys
from pathlib import Path

from engine.geometry import inside, representative_point
from engine.outputs import datum_floor_y

VENUE_JSON = Path(__file__).resolve().parent.parent / "venue.json"
VOCAB = json.loads((Path(__file__).parent / "data" / "places_vocab.json").read_text("utf-8"))
SCHEMA_VERSION = "aria-places/1"
FILLER, COMPASS = set(VOCAB["filler"]), set(VOCAB["compass"])
WEIGHTS = VOCAB["weights"]
EXACT_SCORE = 200
SPACE_APPROX_M = {"scan": 0.3, "plan_traced": 1.5, "plan_bbox": 2.5}  # by geometry_source
DOOR_APPROX_M = 1.5  # an opening whose width (and so position) wasn't measured on a scan
END_APPROX_M = {"scan": 0.5, "plan": 2.0, "none": 2.5}  # a stair end: scanned, given, guessed
SPACE_TYPES = ("space", "restroom", "elevator", "outdoor")
ROOM_NUMBER = re.compile(r"\d{3}[a-z]{0,2}")
SEARCH_ONLY = ("exact", "names", "terms")


def norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", re.sub(r"['’]", "", s.lower())).split())


def stem(t: str) -> str:
    return t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t


def key(s: str) -> str:
    """The form every name and query is compared in: "Stairs to 2nd floor" -> "stair 2nd floor"."""
    return " ".join(stem(t) for t in norm(s).split() if t not in FILLER)


INTENT_TOKENS = {t for i in VOCAB["intents"].values() for w in i["words"] for t in key(w).split()}


# --- The index. ---
def load_raw(path: str | Path = VENUE_JSON) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _elevations(raw: dict) -> dict[str, float]:
    storey = {s["id"]: float(s["elevation"]) for s in raw["storeys"]}
    fe = {s["id"]: s.get("floor_elevation") for s in raw["spaces"]}
    return {
        s["id"]: float(fe[s["id"]] if fe[s["id"]] is not None else storey[s["storey"]])
        for s in raw["spaces"]
    }


def _short(s: dict) -> str:
    short = (s.get("name") or s["id"]).split(" (")[0]
    return short if s["id"] in short else f"{short} ({s['id']})"


def _title(aliases: list[str], fallback: str) -> str:
    """The first alias as a label ("main entrance" -> "Main entrance"), else the fallback."""
    return aliases[0][:1].upper() + aliases[0][1:] if aliases else fallback


def _point(xz: list[float], elevation: float) -> list[float]:
    return [round(xz[0], 2), round(elevation, 2), round(xz[1], 2)]


def _searchable(place: dict, exact: list, phrases: list) -> dict:
    """Add the phrases search compares against, all in key form."""
    exact_keys = {key(n) for n in exact if n} - {""}
    names = exact_keys | {key(n) for n in phrases if n} - {""}
    terms = {t for n in names for t in n.split()} | set(key(place["label"]).split())
    return {**place, "exact": sorted(exact_keys), "names": sorted(names), "terms": sorted(terms)}


def _space_place(s: dict, elevation: float) -> dict:
    poly = [(float(p[0]), float(p[1])) for p in s["polygon"]]
    name = s.get("name") or ""
    typ = "outdoor" if s.get("is_outdoor") else s["kind"]
    place = {
        "id": f"space:{s['id']}",
        "ref": s["id"],
        "type": typ if typ in SPACE_TYPES else "space",
        "kind": s["kind"],
        "label": _short(s),
        "storey": s["storey"],
        "point": _point(s.get("pin") or representative_point(poly), elevation),
        "space": s["id"],
        "scanned": s["storey"] == "1F" and bool(s.get("scanned_by")),
        "approx_m": SPACE_APPROX_M.get(s.get("geometry_source"), SPACE_APPROX_M["plan_bbox"]),
        "polygon": s["polygon"],
    }
    parts = re.findall(r"\(([^)]*)\)", name) + re.findall(r"\b\d{3}[A-Z]{0,2}\b", name)
    phrases = [name, place["label"], *parts, *VOCAB["kind_words"].get(s["kind"], [])]
    return _searchable(place, [s["id"], *s.get("aliases", []), s.get("event_name")], phrases)


def _opening_place(o: dict, spaces: dict, elevation: dict) -> dict:
    kind, aliases = o["kind"], o.get("aliases", [])
    sides = [sid for sid in (o["a"], o["b"]) if sid in spaces]
    kind_words = kind.replace("_", " ")
    phrases = [kind_words, *(f"{kind_words} {sid}" for sid in sides)]
    if o.get("is_exit"):
        typ = "exit"
        phrases += ["exit", f"exit {o['a']}"]
    else:
        types = {"step": "step", "ramp": "ramp", "gate": "gate", "elevator": "elevator"}
        typ = types.get(kind, "door" if "door" in kind else "opening")
    name = _title(aliases, kind_words.capitalize())
    there = " to ".join(
        "outside" if sid == "SAFE" else _short(spaces[sid]) for sid in (o["a"], o["b"])
    )
    e = [elevation[sid] for sid in sides]
    home = spaces[sides[0]]
    place = {
        "id": f"opening:{o['id']}",
        "ref": o["id"],
        "type": typ,
        "kind": kind,
        "label": f"{name} ({o['id']}), {there}",
        "storey": home["storey"],
        "point": _point(o["position"], sum(e) / len(e) if kind in ("step", "ramp") else e[0]),
        "space": sides[0],
        "scanned": home["storey"] == "1F" and any(spaces[sid].get("scanned_by") for sid in sides),
        "approx_m": SPACE_APPROX_M["scan"] if o.get("width_source") == "scan" else DOOR_APPROX_M,
    }
    return _searchable(place, [o["id"], *aliases], phrases)


def _stair_end(o: dict, sid: str, spaces: dict, elevation: dict) -> dict:
    """One end of a stair: its foot or top, on that end's storey, at `ends[sid]` if given."""
    aliases = o.get("aliases", [])
    end = o.get("ends", {}).get(sid)
    sides = [s for s in (o["a"], o["b"]) if s in spaces]
    where = "foot" if elevation[sid] <= min(elevation[s] for s in sides) else "top"
    storey = spaces[sid]["storey"]
    scanned = storey == "1F" and bool(spaces[sid].get("scanned_by"))
    place = {
        "id": f"stair:{o['id']}:{sid}",
        "ref": o["id"],
        "type": "stair",
        "kind": o["kind"],
        "label": f"{_title(aliases, 'Stair ' + o['id'])}, {where} ({storey})",
        "storey": storey,
        "point": _point(end or o["position"], elevation[sid]),
        "space": sid,
        "scanned": scanned,
        "approx_m": END_APPROX_M["none" if not end else "scan" if scanned else "plan"],
    }
    return _searchable(place, [o["id"], *aliases], ["stair", "stairs", "staircase", where])


def _landmark_place(lm: dict, spaces: dict) -> dict:
    place = {
        "id": f"landmark:{lm['id']}",
        "ref": lm["id"],
        "type": "landmark",
        "kind": lm["kind"],
        "label": lm["name"],
        "storey": lm["storey"],
        "point": _point(lm["position"], float(lm["elevation"])),
        "space": lm["space"],
        "scanned": lm["storey"] == "1F" and bool(spaces[lm["space"]].get("scanned_by")),
        "approx_m": lm["approx_m"],
        "note": lm.get("position_source"),
    }
    return _searchable(place, [lm["id"], *lm.get("aliases", [])], [lm["name"], lm["kind"]])


def build_index(raw: dict | None = None) -> list[dict]:
    """Every space (at its `pin` or a point inside), every walkable opening, both ends of every
    stair, and every landmark. Floor voids (`V-`) and the elevator shaft are left out."""
    raw = load_raw() if raw is None else raw
    spaces = {s["id"]: s for s in raw["spaces"]}
    elevation = _elevations(raw)
    places = [_space_place(s, elevation[s["id"]]) for s in raw["spaces"]]
    for o in raw["openings"]:
        sides = [sid for sid in (o["a"], o["b"]) if sid in spaces]
        shaft = o["kind"] == "elevator" and all(spaces[s]["kind"] == "elevator" for s in sides)
        if o["id"].startswith("V-") or shaft or not sides or not o.get("position"):
            continue
        if o["kind"] == "stair":
            places += [_stair_end(o, sid, spaces, elevation) for sid in sides]
        else:
            places.append(_opening_place(o, spaces, elevation))
    return places + [_landmark_place(lm, spaces) for lm in raw.get("landmarks", [])]


def index_json(raw: dict | None = None) -> dict:
    """places.json: the index plus the vocabulary and weights a port of `search` needs."""
    raw = load_raw() if raw is None else raw
    return {
        "schema_version": SCHEMA_VERSION,
        "venue": raw.get("building", {}).get("name"),
        "frame": {
            "point": "[x, elevation, z] in the venue frame, metres (packages/engine/VENUE.md)",
            "floor_y": datum_floor_y(raw),
        },
        "vocab": {k: v for k, v in VOCAB.items() if k != "about"},
        "places": build_index(raw),
    }


# --- Search. ---
def parse(query: str) -> tuple[str, str | None, dict[str, int], list[str]]:
    """Query -> (text in key form, the storey it names, type boosts, compass words dropped)."""
    q = f" {norm(query)} "
    storey = None
    for sid, words in VOCAB["storeys"].items():
        for w in sorted(words, key=len, reverse=True):
            if f" {w} " in q:
                storey = storey or sid
                q = q.replace(f" {w} ", " ")
    compass = [t for t in q.split() if t in COMPASS]
    text = key(" ".join(t for t in q.split() if t not in COMPASS))
    boosts: dict[str, int] = {}
    for intent in VOCAB["intents"].values():
        if any(f" {key(w)} " in f" {text} " for w in intent["words"]):
            for t, wgt in intent["types"].items():
                boosts[t] = max(boosts.get(t, 0), wgt)
    return text, storey, boosts, compass


def _score(p: dict, text: str, boosts: dict[str, int]) -> float:
    w, qt = WEIGHTS, set(text.split())
    s = w["exact"] if text in p["exact"] else w["name"] if text in p["names"] else 0.0
    if qt:
        s += w["terms"] * len(qt & set(p["terms"])) / len(qt)
        fuzzy = max((difflib.SequenceMatcher(None, text, n).ratio() for n in p["names"]), default=0)
        s += w["fuzzy"] * fuzzy if fuzzy > w["fuzzy_min"] else 0.0
    if boosts:
        b = boosts.get(p["type"], 0)
        if b == 0 and not (qt - INTENT_TOKENS):
            return 0.0  # the query is only an intent ("stairs"): places of that type only
        s += b
    if ROOM_NUMBER.fullmatch(text) and p["type"] in SPACE_TYPES:
        s += w["room_number"]
    return round(s, 1)


def _order(item: tuple[float, dict]) -> tuple:
    s, p = item
    return (-s, p["storey"], not p["scanned"])


def _result(query: str, storey: str | None, tier: list, rest: list, notes: list[str]) -> dict:
    def public(s: float, p: dict) -> dict:
        return {**{k: v for k, v in p.items() if k not in SEARCH_ONLY}, "score": s}

    matches = [public(s, p) for s, p in sorted(tier, key=_order)]
    return {
        "query": query,
        "storey": storey,
        "ambiguous": len({m["ref"] for m in matches}) > 1,
        "matches": matches,
        "also": [public(s, p) for s, p in rest],
        "note": " ".join(notes) or None,
    }


def search(places: list[dict], query: str, storey: str | None = None, limit: int = 5) -> dict:
    """Best places for a query: `matches` holds every place tied for best (`ambiguous` when they
    are more than one feature), `also` up to `limit` runners-up. `storey` forces a floor."""
    whole = key(query)
    exact = [p for p in places if whole in p["exact"] and storey in (None, p["storey"])]
    if whole and exact:
        return _result(query, storey, [(EXACT_SCORE, p) for p in exact], [], [])
    text, said, boosts, compass = parse(query)
    storey = storey or said
    notes = []
    if compass:
        notes.append(
            f"Compass words not used ({', '.join(compass)}): north is unverified and the "
            "venue's own 'west' is +x (VENUE.md)."
        )
    if not text and storey:
        text, boosts = "stair", VOCAB["intents"]["stair"]["types"]
        notes.append(f"A floor on its own: the stairs on {storey}.")
    scored = [(_score(p, text, boosts), p) for p in places if storey in (None, p["storey"])]
    scored = sorted([(s, p) for s, p in scored if s > 0], key=_order)
    if not scored:
        return _result(query, storey, [], [], [*notes, "No place matches."])
    cut = scored[0][0] - WEIGHTS["tie_margin"]
    tier = [(s, p) for s, p in scored if s >= cut]
    return _result(query, storey, tier, [(s, p) for s, p in scored if s < cut][:limit], notes)


# --- Reverse lookup. ---
def _seg_dist(p: tuple[float, float], a: list[float], b: list[float]) -> float:
    dx, dz = b[0] - a[0], b[1] - a[1]
    ll = dx * dx + dz * dz
    t = 0.0 if ll == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dz) / ll))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dz))


def space_at(raw: dict, x: float, z: float, elevation: float, tol_m: float = 0.3) -> str | None:
    """The space under a venue-frame point (a click on the scan): inside its polygon or within
    tol_m of an edge, on the floor nearest the elevation (within 1.5 m)."""
    elevations = _elevations(raw)
    best = None
    for sp in raw["spaces"]:
        poly, de = sp["polygon"], abs(elevation - elevations[sp["id"]])
        if de > 1.5 or not poly:
            continue
        if inside((x, z), [(q[0], q[1]) for q in poly]):
            d = 0.0
        else:
            d = min(_seg_dist((x, z), a, b) for a, b in zip(poly, poly[1:] + poly[:1], strict=True))
        if d <= tol_m and (best is None or (d, de) < best[0]):
            best = ((d, de), sp["id"])
    return best[1] if best else None


# --- CLI. ---
def _print(res: dict) -> None:
    n = len({m["ref"] for m in res["matches"]})
    flag = f"  AMBIGUOUS ({n} features)" if res["ambiguous"] else ""
    print(f"\n> {res['query']!r}  storey={res['storey']}{flag}")
    for tag, rows in (("", res["matches"]), ("also ", res["also"])):
        for m in rows:
            x, e, z = m["point"]
            src = "scan" if m["scanned"] else "plan"
            print(
                f"  {tag}{m['score']:6.1f}  {m['id']:42s} {m['storey']} [{x:6.1f},{e:5.2f},"
                f"{z:6.1f}] {src} +/-{m['approx_m']}  {m['label']}"
            )
    if res["note"]:
        print(f"  note: {res['note']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m engine.places", description=__doc__.split("\n")[0])
    ap.add_argument("queries", nargs="*", help='e.g. "stairs first floor"')
    ap.add_argument("--venue", default=str(VENUE_JSON), help="venue.json to read")
    ap.add_argument("--storey", help="force a storey (1F, 2F, 3F)")
    ap.add_argument("--json", action="store_true", help="print each result as JSON")
    ap.add_argument("--index", action="store_true", help="write the place index (places.json)")
    ap.add_argument("--out", help="with --index: the file to write (default: stdout)")
    ap.add_argument("--at", nargs="+", metavar="X,ELEVATION,Z", help="the space under a point")
    args = ap.parse_args(argv)
    raw = load_raw(args.venue)
    if args.index:
        doc = index_json(raw)
        text = json.dumps(doc, ensure_ascii=False, allow_nan=False)
        if args.out:
            Path(args.out).write_text(text + "\n", encoding="utf-8")
            print(f"{len(doc['places'])} places -> {args.out}", file=sys.stderr)
        else:
            print(text)
    for spec in args.at or []:
        x, e, z = (float(v) for v in spec.split(","))
        print(f"space_at({x}, {e}, {z}) -> {space_at(raw, x, z, e)}")
    places = build_index(raw) if args.queries else []
    for q in args.queries:
        res = search(places, q, storey=args.storey)
        if args.json:
            print(json.dumps(res, ensure_ascii=False))
        else:
            _print(res)
    if not (args.index or args.at or args.queries):
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
