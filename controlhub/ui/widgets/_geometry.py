"""Gauge / speed-dial geometry, shared by Gauge and SpeedDial.

A straight port of Gauge.tsx / SpeedDial.tsx in the Electron app: a 240 degree
scale starting at 150 degrees (clockwise from +x, i.e. lower-left), drawn in a
200 x 150 box whose origin is (0, 12). Screen coordinates: y grows downwards,
so "clockwise" angles work directly with cos/sin.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

CX = 100.0
CY = 100.0
R = 80.0
START = 150.0  # degrees, clockwise from +x
SWEEP = 240.0
VIEW_X, VIEW_Y, VIEW_W, VIEW_H = 0.0, 12.0, 200.0, 150.0
# Presses nearer the centre than this (the readout, the hub) don't grab the dial
GRAB_RADIUS = R - 30

def polar(r: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return CX + r * math.cos(a), CY + r * math.sin(a)


def frac(v: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return min(1.0, max(0.0, (v - lo) / (hi - lo)))


def angle(v: float, lo: float, hi: float) -> float:
    return START + frac(v, lo, hi) * SWEEP


def fmt_tick(v: float) -> str:
    if abs(v) >= 1000:
        s = f"{v / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{s}k"
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s or "0"


@dataclass(frozen=True)
class Tick:
    major: bool
    x0: float
    y0: float
    x1: float
    y1: float
    label: str | None = None
    lx: float = 0.0
    ly: float = 0.0


def ticks(lo: float, hi: float, major_ticks: int = 6, minor_per_major: int = 4) -> list[Tick]:
    out: list[Tick] = []
    n = major_ticks * minor_per_major
    for i in range(n + 1):
        v = lo + (hi - lo) * i / n
        a = START + SWEEP * i / n
        major = i % minor_per_major == 0
        x0, y0 = polar(R - (10 if major else 5), a)
        x1, y1 = polar(R, a)
        if major:
            lx, ly = polar(R - 20, a)
            out.append(Tick(True, x0, y0, x1, y1, fmt_tick(v), lx, ly))
        else:
            out.append(Tick(False, x0, y0, x1, y1))
    return out


def view_scale(width: float, height: float) -> tuple[float, float, float]:
    """viewBox 'xMidYMid meet': (scale, offset_x, offset_y) from view units to pixels."""
    s = min(width / VIEW_W, height / VIEW_H)
    ox = (width - VIEW_W * s) / 2 - VIEW_X * s
    oy = (height - VIEW_H * s) / 2 - VIEW_Y * s
    return s, ox, oy


def point_at(px: float, py: float, width: float, height: float) -> tuple[float, float] | None:
    """A pixel position in a width x height widget -> (degrees past START, distance from centre)."""
    s, ox, oy = view_scale(width, height)
    if s <= 0:
        return None
    x = (px - ox) / s
    y = (py - oy) / s
    deg = math.degrees(math.atan2(y - CY, x - CX))
    rel = ((deg - START) % 360 + 360) % 360
    return rel, math.hypot(x - CX, y - CY)


def value_of(rel: float, lo: float, hi: float) -> float:
    """While dragging, the gap at the bottom snaps to the nearer end."""
    if rel <= SWEEP:
        t = rel / SWEEP
    else:
        t = 1.0 if rel - SWEEP < 360 - rel else 0.0
    return lo + t * (hi - lo)


def arc_points(r: float, a0: float, a1: float, steps: int = 64) -> list[tuple[float, float]]:
    """A polyline along an arc, for toolkits with no arc primitive."""
    if a1 <= a0:
        return [polar(r, a0)]
    n = max(2, int(steps * (a1 - a0) / SWEEP) + 1)
    return [polar(r, a0 + (a1 - a0) * i / (n - 1)) for i in range(n)]
