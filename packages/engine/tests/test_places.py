"""Place lookup: the shared query cases, where points land, and places.json."""

import json
from pathlib import Path

import pytest

from engine.places import COMPASS, build_index, index_json, key, load_raw, main, search, space_at

CASES = json.loads((Path(__file__).parent / "places_queries.json").read_text("utf-8"))["cases"]


@pytest.fixture(scope="module")
def raw():
    return load_raw()


@pytest.fixture(scope="module")
def places(raw):
    return build_index(raw)


@pytest.mark.parametrize("case", CASES, ids=[c["query"] for c in CASES])
def test_shared_query_cases(places, case):
    res = search(places, case["query"])
    assert {m["ref"] for m in res["matches"]} == set(case["refs"])
    assert (res["matches"][0]["id"] if res["matches"] else None) == case["first"]
    assert res["ambiguous"] == case["ambiguous"]
    if "storey" in case:
        assert res["storey"] == case["storey"]
    if "scanned" in case:
        assert res["matches"][0]["scanned"] == case["scanned"]
    if "note" in case:
        assert case["note"] in (res["note"] or "")


def test_compass_words_change_nothing(places):
    west, plain = search(places, "west exit"), search(places, "exit")
    assert [m["id"] for m in west["matches"]] == [m["id"] for m in plain["matches"]]
    assert "west" in west["note"] and plain["note"] is None


def test_no_alias_uses_a_compass_word(raw):
    features = raw["spaces"] + raw["openings"] + raw.get("landmarks", [])
    for f in features:
        for alias in f.get("aliases", []):
            assert not set(key(alias).split()) & COMPASS, (f["id"], alias)


def test_points_sit_in_their_space(raw, places):
    """Space pins, given stair ends and landmarks land inside the space they name."""
    ends = {f"stair:{o['id']}:{sid}" for o in raw["openings"] for sid in o.get("ends", {})}
    for p in places:
        if p["id"].startswith(("space:", "landmark:")) or p["id"] in ends:
            x, e, z = p["point"]
            assert space_at(raw, x, z, e) == p["space"], p["id"]


def test_space_at(raw):
    assert space_at(raw, 14.3, -20.2, 0.62) == "galleria_far_end"
    assert space_at(raw, 0.25, -13.05, 5.0) == "219"  # 2F room 219 sits over 170
    assert space_at(raw, 0.25, -13.05, 0.0) == "170"
    assert space_at(raw, 200.0, 200.0, 0.0) is None


def test_index_json_is_clean(raw, tmp_path):
    out = tmp_path / "places.json"
    assert main(["--index", "--out", str(out)]) == 0
    doc = json.loads(out.read_text("utf-8"))
    assert doc == json.loads(json.dumps(index_json(raw), allow_nan=False))
    assert doc["frame"]["floor_y"] == -3.91
    ids = [p["id"] for p in doc["places"]]
    assert len(ids) == len(set(ids))
    for p in doc["places"]:
        assert len(p["point"]) == 3 and p["storey"] in ("1F", "2F", "3F"), p["id"]
        assert p["exact"] and p["terms"], p["id"]
    assert not any(p["ref"].startswith("V-") for p in doc["places"])
