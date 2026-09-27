#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Icon spec + primitive library for QElectroTech's domain icons.

Why a spec rather than drawing 90 icons freehand: coherence across a set is the
thing that fails when icons are produced one at a time. Every glyph here
composes from the same primitives at the same stroke weight on the same grid,
so consistency is structural rather than a matter of care.

GROUNDING -- these values were measured from QET's existing icons, not chosen:

  #4d4d4d   base stroke; dominant colour in element/conductor/endline-*/folio-*
  #ff0000   terminal body, phase          (older icons)
  #0000f0   terminal tip, neutral         (older icons)
  #008000   ground                        (older icons)
  #3daee9   Breeze blue                   (newer icons: titleblock-*)
  #da4453   Breeze red                    (newer icons: titleblock-*)

The set is internally inconsistent: older icons use pure RGB primaries, newer
ones already use the Breeze palette. This spec keeps the *semantics* (red =
phase, blue = neutral, green = ground -- real electrical convention, not
decoration) but harmonises the values to Breeze, so the domain icons sit
correctly beside the 93 stock Breeze icons they share a toolbar with.
"""

import math

# ---------------------------------------------------------------- palette ---
BASE = '#4d4d4d'      # structural strokes -- matches the existing set exactly
BASE_LIGHT = '#797979'
PHASE = '#da4453'     # was #ff0000  -- Breeze red
NEUTRAL = '#3daee9'   # was #0000f0  -- Breeze blue
GROUND = '#27ae60'    # was #008000  -- Breeze green
ACCENT = '#f67400'    # Breeze orange, for "new"/"auto" markers
PAPER = '#fcfcfc'

# ------------------------------------------------------------------ grid ---
SIZE = 22             # design canvas; 16 and 32 are rendered from the same art
STROKE = 2.0          # matches Breeze's 22px weight
THIN = 1.0
CAP = 'butt'          # technical drawing, not a friendly UI glyph
JOIN = 'miter'


def _snap(v, w=STROKE):
    """Put a stroke centre on a half-pixel so it lands on the pixel grid."""
    return round(v * 2) / 2 + (0.5 if int(w) % 2 else 0.0)


# ------------------------------------------------------------ primitives ---
def line(x1, y1, x2, y2, color=BASE, w=STROKE):
    return (f'<line x1="{_snap(x1, w)}" y1="{_snap(y1, w)}" '
            f'x2="{_snap(x2, w)}" y2="{_snap(y2, w)}" stroke="{color}" '
            f'stroke-width="{w}" stroke-linecap="{CAP}"/>')


def polyline(pts, color=BASE, w=STROKE):
    d = ' '.join(f'{_snap(x, w)},{_snap(y, w)}' for x, y in pts)
    return (f'<polyline points="{d}" fill="none" stroke="{color}" '
            f'stroke-width="{w}" stroke-linecap="{CAP}" stroke-linejoin="{JOIN}"/>')


def rect(x, y, w, h, color=BASE, fill='none', sw=STROKE, rx=0):
    return (f'<rect x="{_snap(x, sw)}" y="{_snap(y, sw)}" width="{w}" height="{h}" '
            f'rx="{rx}" fill="{fill}" stroke="{color}" stroke-width="{sw}"/>')


def solid(x, y, w, h, color=BASE, rx=0):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{color}"/>')


def circle(cx, cy, r, color=BASE, fill='none', sw=STROKE):
    return (f'<circle cx="{_snap(cx, sw)}" cy="{_snap(cy, sw)}" r="{r}" '
            f'fill="{fill}" stroke="{color}" stroke-width="{sw}"/>')


def dot(cx, cy, r, color=BASE):
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}"/>'


def svg(body, size=SIZE):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            f'viewBox="0 0 {size} {size}">\n  '
            + '\n  '.join(body) + '\n</svg>\n')


def arc_arrow(cx, cy, r, start_deg, end_deg, color=BASE, w=STROKE, head=3.2):
    """Circular arc with an arrowhead welded to its actual end point.

    Placing the head at hand-picked coordinates does not survive any change to
    the arc -- it leaves the head floating beside the curve. Here both the tip
    position and its rotation are derived from the arc's own end angle, so they
    cannot drift apart.
    """
    def pt(a):
        t = math.radians(a)
        return (cx + r * math.cos(t), cy + r * math.sin(t))

    x1, y1 = pt(start_deg)
    x2, y2 = pt(end_deg)
    large = 1 if abs(end_deg - start_deg) > 180 else 0
    sweep = 1 if end_deg > start_deg else 0
    out = [f'<path d="M{x1:.2f},{y1:.2f} A{r},{r} 0 {large} {sweep} '
           f'{x2:.2f},{y2:.2f}" fill="none" stroke="{color}" '
           f'stroke-width="{w}" stroke-linecap="butt"/>']

    # tangent at the end, pointing the way the arc is travelling
    t = math.radians(end_deg)
    tx, ty = (-math.sin(t), math.cos(t))
    if sweep == 0:
        tx, ty = -tx, -ty
    nx, ny = -ty, tx
    tipx, tipy = x2 + tx * head, y2 + ty * head
    b1 = (x2 + nx * head * 0.8, y2 + ny * head * 0.8)
    b2 = (x2 - nx * head * 0.8, y2 - ny * head * 0.8)
    out.append(f'<polygon points="{tipx:.2f},{tipy:.2f} {b1[0]:.2f},{b1[1]:.2f} '
               f'{b2[0]:.2f},{b2[1]:.2f}" fill="{color}"/>')
    return out


def pencil(x1, y1, x2, y2, w=3.0, tip_len=3.6, body=None, tip=None):
    """A pencil: coloured tip flush and collinear with the body.

    Exists as one primitive because getting this wrong twice is easy and the
    failure is subtle. Positioning body and tip independently lets grid
    snapping shift them apart, so the tip reads as a blob floating beside the
    pencil rather than its point. Here a single axis is defined once, the split
    is computed along it, and both segments are drawn un-snapped at identical
    width -- they cannot separate.

    @param x1,y1  the writing tip;  @param x2,y2  the blunt end.
    """
    body = BASE if body is None else body
    tip = ACCENT if tip is None else tip
    ln = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
    if ln == 0:
        return []
    ux, uy = (x2 - x1) / ln, (y2 - y1) / ln
    mx, my = x1 + ux * tip_len, y1 + uy * tip_len
    return [thick_line(mx, my, x2, y2, body, w),
            thick_line(x1, y1, mx, my, tip, w)]


def thick_line(x1, y1, x2, y2, color, w):
    """Un-snapped stroke -- for segments that must stay exactly collinear with
    a neighbour (grid snapping would shift them apart)."""
    return (f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
            f'stroke="{color}" stroke-width="{w}" stroke-linecap="butt"/>')


# -------------------------------------------------- composite: a terminal ---
def terminal_stub(x, y, direction='n', length=7):
    """QET's terminal mark: a coloured stub with a contrasting tip.

    Red body + blue tip is the existing convention (measured from
    ico/22x22/terminal.png: 80% #ff0000, 20% #0000f0) and is preserved.
    """
    dx, dy = {'n': (0, -1), 's': (0, 1), 'e': (1, 0), 'w': (-1, 0)}[direction]
    tip = 2
    body = length - tip
    parts = [line(x, y, x + dx * body, y + dy * body, PHASE, STROKE)]
    parts.append(line(x + dx * body, y + dy * body,
                      x + dx * length, y + dy * length, NEUTRAL, STROKE))
    return parts
