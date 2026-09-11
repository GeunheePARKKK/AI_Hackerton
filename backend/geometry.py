"""Exact geometry primitives for clash / clearance detection.

All math here is deterministic - no AI involved. Units: meters.
"""
from __future__ import annotations

import math

Vec3 = tuple[float, float, float]


def sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def scale(a: Vec3, s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def norm(a: Vec3) -> float:
    return math.sqrt(dot(a, a))


def lerp(a: Vec3, b: Vec3, t: float) -> Vec3:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def clamp_to_box(p: Vec3, bmin: Vec3, bmax: Vec3) -> Vec3:
    return (
        min(max(p[0], bmin[0]), bmax[0]),
        min(max(p[1], bmin[1]), bmax[1]),
        min(max(p[2], bmin[2]), bmax[2]),
    )


def point_box_distance(p: Vec3, bmin: Vec3, bmax: Vec3) -> float:
    """Distance from point to AABB surface (0 if inside)."""
    return norm(sub(p, clamp_to_box(p, bmin, bmax)))


def segment_box_distance(a: Vec3, b: Vec3, bmin: Vec3, bmax: Vec3) -> tuple[float, Vec3, Vec3]:
    """Min distance between segment [a,b] and AABB.

    point_box_distance is convex along the segment, so ternary search is exact.
    Returns (distance, closest point on segment, closest point on box).
    """
    lo, hi = 0.0, 1.0
    for _ in range(100):
        m1 = lo + (hi - lo) / 3
        m2 = hi - (hi - lo) / 3
        if point_box_distance(lerp(a, b, m1), bmin, bmax) <= point_box_distance(lerp(a, b, m2), bmin, bmax):
            hi = m2
        else:
            lo = m1
    p_seg = lerp(a, b, (lo + hi) / 2)
    p_box = clamp_to_box(p_seg, bmin, bmax)
    return norm(sub(p_seg, p_box)), p_seg, p_box


def segment_segment_distance(p1: Vec3, q1: Vec3, p2: Vec3, q2: Vec3) -> tuple[float, Vec3, Vec3]:
    """Min distance between segments [p1,q1] and [p2,q2] (Ericson, RTCD 5.1.9).

    Returns (distance, closest point on seg1, closest point on seg2).
    """
    d1 = sub(q1, p1)
    d2 = sub(q2, p2)
    r = sub(p1, p2)
    a = dot(d1, d1)
    e = dot(d2, d2)
    f = dot(d2, r)
    EPS = 1e-12

    if a <= EPS and e <= EPS:
        s = t = 0.0
    elif a <= EPS:
        s = 0.0
        t = min(max(f / e, 0.0), 1.0)
    else:
        c = dot(d1, r)
        if e <= EPS:
            t = 0.0
            s = min(max(-c / a, 0.0), 1.0)
        else:
            b = dot(d1, d2)
            denom = a * e - b * b
            s = min(max((b * f - c * e) / denom, 0.0), 1.0) if denom > EPS else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t = 0.0
                s = min(max(-c / a, 0.0), 1.0)
            elif t > 1.0:
                t = 1.0
                s = min(max((b - c) / a, 0.0), 1.0)

    c1 = lerp(p1, q1, s)
    c2 = lerp(p2, q2, t)
    return norm(sub(c1, c2)), c1, c2


def box_box_distance(amin: Vec3, amax: Vec3, bmin: Vec3, bmax: Vec3) -> float:
    """Min distance between two AABBs (0 if overlapping/touching)."""
    d2 = 0.0
    for i in range(3):
        gap = max(amin[i] - bmax[i], bmin[i] - amax[i], 0.0)
        d2 += gap * gap
    return math.sqrt(d2)


def boxes_overlap(amin: Vec3, amax: Vec3, bmin: Vec3, bmax: Vec3) -> bool:
    return all(amin[i] <= bmax[i] and bmin[i] <= amax[i] for i in range(3))


def midpoint(a: Vec3, b: Vec3) -> Vec3:
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2)
