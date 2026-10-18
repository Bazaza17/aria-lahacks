"""Plan-polygon helpers in the venue frame ([x, z] metres). Pure functions, stdlib only."""

from __future__ import annotations

import math

Point = tuple[float, float]


def _edges(poly: list[Point]) -> zip:
    return zip(poly, poly[1:] + poly[:1], strict=True)


def shoelace(poly: list[Point]) -> float:
    """Signed area (positive for counter-clockwise in x, z math axes)."""
    return 0.5 * sum(x0 * z1 - x1 * z0 for (x0, z0), (x1, z1) in _edges(poly))


def perimeter(poly: list[Point]) -> float:
    return sum(math.dist(p, q) for p, q in _edges(poly)) if len(poly) > 1 else 0.0


def centroid(poly: list[Point]) -> Point:
    a = shoelace(poly)
    if abs(a) < 1e-9:
        return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))
    cx = cz = 0.0
    for (x0, z0), (x1, z1) in _edges(poly):
        cross = x0 * z1 - x1 * z0
        cx += (x0 + x1) * cross
        cz += (z0 + z1) * cross
    return (cx / (6.0 * a), cz / (6.0 * a))


def inside(p: Point, poly: list[Point]) -> bool:
    x, z = p
    hit = False
    for (x0, z0), (x1, z1) in _edges(poly):
        if (z0 > z) != (z1 > z) and x < x0 + (z - z0) * (x1 - x0) / (z1 - z0):
            hit = not hit
    return hit


def representative_point(poly: list[Point]) -> Point:
    """A point inside the polygon: its centroid, or (for an L or C shape whose centroid falls
    outside) the middle of the widest inside run along the centroid's z line."""
    c = centroid(poly)
    if inside(c, poly):
        return c
    z = c[1] + 1e-7
    xs = sorted(
        x0 + (z - z0) * (x1 - x0) / (z1 - z0)
        for (x0, z0), (x1, z1) in _edges(poly)
        if (z0 > z) != (z1 > z)
    )
    runs = [(xs[i], xs[i + 1]) for i in range(0, len(xs) - 1, 2)]
    if not runs:
        return c
    lo, hi = max(runs, key=lambda r: r[1] - r[0])
    return ((lo + hi) / 2.0, c[1])


def bbox(polys: list[list[Point]]) -> tuple[float, float, float, float] | None:
    pts = [p for poly in polys for p in poly]
    if not pts:
        return None
    xs, zs = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), max(xs), min(zs), max(zs))


def segment_inside(
    p: Point, q: Point, poly: list[Point], samples: int = 16, end_margin_m: float = 0.75
) -> bool:
    """Whether the straight walk p -> q stays inside the polygon. The end points are openings
    on (or, with tracing error, just off) its boundary, so samples within end_margin_m of
    either end are skipped."""
    length = math.dist(p, q)
    if len(poly) < 3 or length <= 2.0 * end_margin_m:
        return True
    for i in range(1, samples):
        f = i / samples
        if min(f, 1.0 - f) * length < end_margin_m:
            continue
        if not inside((p[0] + f * (q[0] - p[0]), p[1] + f * (q[1] - p[1])), poly):
            return False
    return True
