#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""
QElectroTech domain icons (89) drawn to iconspec.py.

These are the icons the matcher correctly found no candidate for -- they encode
electrical conventions no general icon theme contains. Drawn as SVG geometry
rather than traced from the 16-22px rasters, which would bake in the existing
blur.

    ./make_domain_icons.py -o out/        # writes out/<name>.svg

Deliberately preserves the meanings already in the set: red/blue terminal
colouring, green ground, the folio-as-page metaphor. The execution changes; the
conventions users recognise do not.
"""

import argparse
import os

from iconspec import (BASE, BASE_LIGHT, PHASE, NEUTRAL, GROUND, ACCENT, PAPER,
                      SIZE, STROKE, THIN,
                      line, polyline, rect, solid, circle, dot, svg,
                      terminal_stub, arc_arrow, thick_line, pencil)


def i_terminal():
    """A terminal (borne) on an element edge.

    Drawn as element-body + stub rather than a bare stub: a bare stub is
    indistinguishable from the `north` orientation mark, which is the same
    geometry. The element body is what makes this read as "a terminal on a
    part" instead of "a direction".
    """
    return [rect(3, 6, 8, 10, BASE, 'none', STROKE)] + \
        terminal_stub(11, 11, 'e', 8)


def i_conductor():
    """A conductor: orthogonal routing between two terminals -- QET only
    draws right-angled wires, so an L is the honest shape."""
    return [polyline([(4, 5), (4, 14), (17, 14)], BASE, STROKE),
            line(4, 3, 4, 6, PHASE, STROKE),
            line(17, 14, 19, 14, NEUTRAL, STROKE)]


def i_conductor_edit():
    """Conductor + pencil.

    The tip has to sit *on* the pencil's axis. Previously body and tip were two
    independently-placed strokes and grid snapping pushed them apart, leaving
    the orange tip reading as a detached blob beside the pencil. Both are now
    derived from one axis and drawn un-snapped at the same width, so they are
    collinear and flush by construction rather than by luck.
    """
    return [polyline([(3, 4), (3, 11), (10, 11)], BASE, STROKE),
            line(3, 3, 3, 6, PHASE, STROKE)] + \
        pencil(10, 19, 18.5, 10.5, w=3.0, tip_len=3.4)


def _conductor_type(color, foot):
    """phase / neutral / ground are one family: the same conductor stem with a
    different foot. Drawing them as three unrelated metaphors (a cross, a
    lollipop, an earth symbol) is how a set stops looking like a set -- so the
    stem is shared geometry and only the terminator distinguishes them."""
    parts = [line(11, 3, 11, 12, color, STROKE)]
    return parts + foot(color)


def i_phase():
    """Phase: single full-width bar -- one conductor."""
    return _conductor_type(PHASE, lambda c: [line(4, 13, 18, 13, c, STROKE)])


def i_neutral():
    """Neutral: bar plus a return bar, distinguishing it from phase at a glance."""
    return _conductor_type(NEUTRAL, lambda c: [line(4, 13, 18, 13, c, STROKE),
                                               line(7, 17, 15, 17, c, STROKE)])


def i_ground():
    """Ground: the standard descending-rung earth symbol."""
    return _conductor_type(GROUND, lambda c: [line(4, 13, 18, 13, c, STROKE),
                                              line(7, 16, 15, 16, c, STROKE),
                                              line(9, 19, 13, 19, c, STROKE)])


def _orientation(direction):
    """Terminal orientation marks -- one shape, rotated. A family should be
    literally the same geometry, not four similar drawings."""
    rot = {'n': 0, 'e': 90, 's': 180, 'w': 270}[direction]
    body = (f'<g transform="rotate({rot} 11 11)">'
            + line(4, 15, 18, 15, BASE, STROKE)
            + line(11, 15, 11, 8, PHASE, STROKE)
            + line(11, 8, 11, 5, NEUTRAL, STROKE)
            + '</g>')
    return [body]


def i_north():
    return _orientation('n')


def i_south():
    return _orientation('s')


def i_east():
    return _orientation('e')


def i_west():
    return _orientation('w')


def i_titleblock_bottom():
    """Folio with its title block along the bottom edge."""
    return [rect(3, 3, 16, 16, BASE, PAPER, STROKE),
            solid(4, 14, 14, 4, NEUTRAL),
            line(9, 14, 9, 18, PAPER, THIN),
            line(14, 14, 14, 18, PAPER, THIN)]


# ------------------------------------------------------------- modifiers ---
# One badge vocabulary shared by every "<thing> + action" icon, so `element-new`
# and `folio-new` carry the *same* plus in the *same* corner. Drawing each
# family's badge separately is how sets lose coherence.
def badge_new(x=15, y=15):
    # 16,16 with +-4 and a 2px stroke reached x=21 and clipped on a 22 canvas.
    return [line(x - 3.5, y, x + 3.5, y, GROUND, STROKE),
            line(x, y - 3.5, x, y + 3.5, GROUND, STROKE)]


def badge_delete(x=15, y=15):
    return [line(x - 3, y - 3, x + 3, y + 3, PHASE, STROKE),
            line(x + 3, y - 3, x - 3, y + 3, PHASE, STROKE)]


def badge_edit(x=15, y=15):
    """Edit badge -- shared by element-edit and folder-edit, so both get the
    same pencil. Built from the pencil() primitive: the tip and body were
    previously placed independently and snapping pushed them apart."""
    return pencil(x - 5, y + 5, x + 4, y - 4, w=3.0, tip_len=3.4)


def props_rows(x, y, w):
    """Two setting rows, drawn inside the shape they describe.

    Tried as a corner badge twice -- bare rails, then rails on a disc. At the
    ~12px a badge gets, the rails collapse to a grey smudge no matter what is
    behind them. Inside the shape they have the full width and stay legible.
    """
    return [line(x, y, x + w, y, BASE, STROKE),
            dot(x + w * 0.68, y, 2.1, NEUTRAL),
            line(x, y + 4.5, x + w, y + 4.5, BASE, STROKE),
            dot(x + w * 0.3, y + 4.5, 2.1, NEUTRAL)]


# --------------------------------------------- drawing-primitive tools ---
# QET's editor primitives are outline shapes, unlike Breeze's filled draw-*.
# The outline convention is kept: it reads as "the shape you will draw".
def _handles(pts):
    return [solid(x - 1.5, y - 1.5, 3, 3, NEUTRAL) for x, y in pts]


def i_line():
    return [line(4, 18, 18, 4, BASE, STROKE)] + _handles([(4, 18), (18, 4)])


def i_rectangle():
    return [rect(4, 6, 14, 10, BASE, 'none', STROKE)] + _handles([(4, 6), (18, 16)])


def i_circle():
    return [circle(11, 11, 7, BASE, 'none', STROKE)] + _handles([(11, 4)])


def i_ellipse():
    return [f'<ellipse cx="11" cy="11" rx="8" ry="5.5" fill="none" '
            f'stroke="{BASE}" stroke-width="{STROKE}"/>'] + _handles([(11, 5.5)])


def i_arc():
    return [f'<path d="M4,16 A8,8 0 0 1 18,16" fill="none" stroke="{BASE}" '
            f'stroke-width="{STROKE}" stroke-linecap="butt"/>'] + \
        _handles([(4, 16), (18, 16)])


def i_polygon():
    return [f'<polygon points="11,4 18,9 15,17 7,17 4,9" fill="none" '
            f'stroke="{BASE}" stroke-width="{STROKE}" stroke-linejoin="miter"/>'] + \
        _handles([(11, 4)])


# ------------------------------------------------ conductor end styles ---
# A five-member family: identical stem, different terminator. These only make
# sense side by side, so they are generated from one function.
def _endline(term):
    return [line(3, 11, 13, 11, BASE, STROKE)] + term


def i_endline_none():
    # A bare stem measured 10x2 against a set median of 18x16, so it read as a
    # stray dash. Given the full stem width its siblings occupy.
    return [line(3, 11, 19, 11, BASE, STROKE)]


def i_endline_simple():
    return _endline([polyline([(13, 7), (18, 11), (13, 15)], BASE, STROKE)])


def i_endline_circle():
    return _endline([circle(16, 11, 3, BASE, PAPER, STROKE)])


def i_endline_diamond():
    return _endline([f'<polygon points="15,7 19,11 15,15 11,11" fill="{PAPER}" '
                     f'stroke="{BASE}" stroke-width="{STROKE}"/>'])


def i_endline_triangle():
    return _endline([f'<polygon points="13,6 20,11 13,16" fill="{BASE}"/>'])


# ------------------------------------------------------- element family ---
def _element_body(x=4, y=6, w=11, h=10):
    """A part with two terminals -- the shape every element-* icon shares."""
    return [rect(x, y, w, h, BASE, PAPER, STROKE),
            line(x - 2, y + h / 2, x, y + h / 2, PHASE, STROKE),
            line(x + w, y + h / 2, x + w + 2, y + h / 2, PHASE, STROKE)]


def i_element():
    return _element_body(6, 6, 11, 10)


def i_element_new():
    return _element_body(4, 4, 11, 10) + badge_new()


def i_element_delete():
    return _element_body(4, 4, 11, 10) + badge_delete()


def i_element_edit():
    return _element_body(4, 3, 11, 10) + badge_edit(14, 14)


def i_element_master():
    """Master drives its slaves: the link leaves the part.

    The first attempt fanned two THIN links out to small dots; below 22px that
    became an unreadable smudge and was indistinguishable from the slave icon.
    A single full-weight arrow carries the direction on its own.
    """
    return _element_body(3, 3, 11, 9) + [
        line(11, 14, 11, 19, NEUTRAL, STROKE),
        polyline([(8, 16), (11, 19), (14, 16)], NEUTRAL, STROKE)]


def i_element_slave():
    """Slave is driven: the same arrow, arriving instead of leaving."""
    return _element_body(3, 10, 11, 9) + [
        line(11, 2, 11, 7, NEUTRAL, STROKE),
        polyline([(8, 5), (11, 8), (14, 5)], NEUTRAL, STROKE)]


# --------------------------------------------------------- folio family ---
def _page(x=4, y=3, w=14, h=16):
    return [rect(x, y, w, h, BASE, PAPER, STROKE),
            line(x + 2, y + 4, x + w - 2, y + 4, BASE_LIGHT, THIN),
            line(x + 2, y + 7, x + w - 2, y + 7, BASE_LIGHT, THIN)]


def i_folio_new():
    return _page(2, 2, 13, 15) + badge_new(17, 17)


def i_folio_delete():
    return _page(2, 2, 13, 15) + badge_delete(17, 17)


def i_folio_properties():
    return [rect(3, 2, 16, 18, BASE, PAPER, STROKE)] + props_rows(6, 9, 10)


def i_folio_ref_coming():
    """A cross-reference arriving from another folio."""
    return _page(7, 3, 12, 16) + [
        polyline([(1, 11), (6, 11)], NEUTRAL, STROKE),
        polyline([(4, 8), (7, 11), (4, 14)], NEUTRAL, STROKE)]


# -------------------------------------------------------- diagram family ---
def _diagram_body(x=3, y=4, w=16, h=13):
    """A folio: a bordered sheet with a title-block strip, which is what makes
    it a *schematic* page rather than a generic document."""
    return [rect(x, y, w, h, BASE, PAPER, STROKE),
            solid(x + 1, y + h - 4, w - 2, 3, BASE_LIGHT)]


def i_diagram():
    return _diagram_body(3, 5, 16, 13)


def i_diagram_add():
    return _diagram_body(2, 3, 13, 11) + badge_new(17, 17)


def i_diagram_del():
    return _diagram_body(2, 3, 13, 11) + badge_delete(17, 17)


def i_diagram_bg():
    """White / grey folio background toggle: one sheet, split tone."""
    return [rect(3, 5, 16, 13, BASE, PAPER, STROKE),
            solid(11, 6, 7, 11, BASE_LIGHT)]


# -------------------------------------------------------- project family ---
def _project_body(x=2, y=4, w=15, h=13):
    """A project holds folios: a folder with a sheet showing above it."""
    return [rect(x + 3, y - 2, w - 6, 5, BASE, PAPER, STROKE),
            polyline([(x, y + h), (x, y + 2), (x + 5, y + 2), (x + 6, y),
                      (x + w, y), (x + w, y + h), (x, y + h)], BASE, STROKE)]


def i_project():
    return _project_body(3, 5, 16, 12)


def i_project_new():
    return _project_body(2, 4, 13, 10) + badge_new(17, 17)


def i_project_delete():
    return _project_body(2, 4, 13, 10) + badge_delete(17, 17)


def i_project_properties():
    return _project_body(2, 5, 18, 14) + props_rows(6, 12, 10)


def i_project_close():
    return _project_body(2, 4, 13, 10) + [
        line(13, 13, 20, 20, PHASE, STROKE), line(20, 13, 13, 20, PHASE, STROKE)]


# --------------------------------------------------------- folder family ---
def _folder(x=2, y=5, w=17, h=12):
    return [polyline([(x, y + h), (x, y), (x + 6, y), (x + 7, y + 2),
                      (x + w, y + 2), (x + w, y + h), (x, y + h)], BASE, STROKE)]


def i_folder_edit():
    return _folder(2, 4, 14, 10) + badge_edit(15, 14)


def i_folder_delete():
    return _folder(2, 4, 14, 10) + badge_delete(17, 17)


def i_folder_properties():
    return _folder(2, 4, 18, 15) + props_rows(6, 12, 10)


def i_folder_only_this():
    """Show only this folder. Two faint dashes did not read as "the others";
    the excluded folders are now drawn as folders, greyed back."""
    return [solid(2, 2, 18, 3, PAPER),
            polyline([(2, 5), (2, 2), (7, 2), (8, 3.5), (19, 3.5), (19, 5)],
                     BASE_LIGHT, THIN),
            solid(2, 17, 18, 3, PAPER),
            polyline([(2, 20), (2, 17), (7, 17), (8, 18.5), (19, 18.5), (19, 20)],
                     BASE_LIGHT, THIN)] + _folder(2, 7, 17, 8)


def i_folder_show_all():
    """Show every folder: a stack."""
    return [line(6, 3, 18, 3, BASE_LIGHT, STROKE),
            line(4, 6, 20, 6, BASE_LIGHT, STROKE)] + _folder(2, 8, 17, 10)


# ------------------------------------------------------- z-order family ---
def _stack(active, arrow_up):
    """Four z-order actions from one drawing: three sheets, one highlighted,
    plus a direction arrow.

    First attempt drew three diamonds at 5px spacing with the arrow at x=20:
    the diamonds merged into a blob below 22px and the arrow's stroke clipped
    off the right edge. Now flat bars at 6px spacing, arrow kept inside x<=19.
    """
    out = []
    for idx, y in enumerate((2, 8, 14)):
        col = NEUTRAL if idx == active else PAPER
        # linejoin=round, not miter: the acute corners of a parallelogram throw
        # a miter spike well past the nominal geometry, which is what pushed
        # this family's ink to the canvas edge.
        out.append(f'<polygon points="2,{y + 5} 7,{y} 16,{y} 11,{y + 5}" '
                   f'fill="{col}" stroke="{BASE}" stroke-width="1.5" '
                   f'stroke-linejoin="round"/>')
    tip, tail = (3, 19) if arrow_up else (19, 3)
    d = 3 if arrow_up else -3
    out.append(line(18, tail, 18, tip, BASE, STROKE))
    out.append(polyline([(16, tip + d), (18, tip), (20, tip + d)], BASE, STROKE))
    return out


def i_raise():
    return _stack(1, True)


def i_lower():
    return _stack(1, False)


def i_bring_forward():
    return _stack(0, True)


def i_send_backward():
    return _stack(2, False)


# ------------------------------------------------------ page count / size ---
def i_single_page():
    return [rect(7, 3, 9, 16, BASE, PAPER, STROKE)]


def i_two_pages():
    return [rect(2, 3, 8, 16, BASE, PAPER, STROKE),
            rect(12, 3, 8, 16, BASE, PAPER, STROKE)]


def i_all_pages():
    return [rect(2, 3, 8, 7, BASE, PAPER, STROKE),
            rect(12, 3, 8, 7, BASE, PAPER, STROKE),
            rect(2, 12, 8, 7, BASE, PAPER, STROKE),
            rect(12, 12, 8, 7, BASE, PAPER, STROKE)]


def i_portrait():
    """Page orientation, not page count -- a bare tall rectangle collided with
    single_page, so the orientation pair carries a fold mark and rule lines
    that the count icons do not have."""
    return [rect(5, 2, 12, 18, BASE, PAPER, STROKE),
            f'<polygon points="12,2 17,7 12,7" fill="{NEUTRAL}"/>',
            line(7, 12, 15, 12, BASE_LIGHT, THIN),
            line(7, 15, 15, 15, BASE_LIGHT, THIN)]


def i_landscape():
    return [rect(2, 5, 18, 12, BASE, PAPER, STROKE),
            f'<polygon points="15,5 20,10 15,10" fill="{NEUTRAL}"/>',
            line(5, 12, 13, 12, BASE_LIGHT, THIN),
            line(5, 15, 13, 15, BASE_LIGHT, THIN)]


def i_view_fit_window():
    return [rect(4, 5, 14, 12, BASE, 'none', STROKE)] + \
        [solid(2, 3, 4, 2, NEUTRAL), solid(2, 3, 2, 4, NEUTRAL),
         solid(16, 3, 4, 2, NEUTRAL), solid(18, 3, 2, 4, NEUTRAL),
         solid(2, 17, 4, 2, NEUTRAL), solid(2, 15, 2, 4, NEUTRAL),
         solid(16, 17, 4, 2, NEUTRAL), solid(18, 15, 2, 4, NEUTRAL)]


def i_view_fit_width():
    return [rect(5, 6, 12, 10, BASE, 'none', STROKE),
            line(3, 11, 5, 11, NEUTRAL, STROKE),
            polyline([(4.5, 9.5), (3, 11), (4.5, 12.5)], NEUTRAL, STROKE),
            line(17, 11, 19, 11, NEUTRAL, STROKE),
            polyline([(17.5, 9.5), (19, 11), (17.5, 12.5)], NEUTRAL, STROKE)]


# ---------------------------------------------------------- transform ---
def i_flip():
    """Flip across the horizontal axis: solid above, outline below."""
    return [f'<polygon points="4,9 18,9 11,3" fill="{BASE}"/>',
            f'<polygon points="4,13 18,13 11,19" fill="none" stroke="{BASE}" '
            f'stroke-width="{STROKE}"/>',
            line(2, 11, 20, 11, NEUTRAL, THIN)]


def i_mirror():
    """Mirror across the vertical axis."""
    return [f'<polygon points="9,4 9,18 3,11" fill="{BASE}"/>',
            f'<polygon points="13,4 13,18 19,11" fill="none" stroke="{BASE}" '
            f'stroke-width="{STROKE}"/>',
            line(11, 2, 11, 20, NEUTRAL, THIN)]


def _move_arrows():
    return [line(11, 4, 11, 18, BASE, STROKE), line(4, 11, 18, 11, BASE, STROKE),
            polyline([(8, 7), (11, 4), (14, 7)], BASE, STROKE),
            polyline([(8, 15), (11, 18), (14, 15)], BASE, STROKE),
            polyline([(7, 8), (4, 11), (7, 14)], BASE, STROKE),
            polyline([(15, 8), (18, 11), (15, 14)], BASE, STROKE)]


def i_move():
    return _move_arrows()


def i_item_move():
    """Move an item. A square with one diagonal arrow reads as *resize*, so
    the item carries the same four-way cross i_move() uses."""
    return [rect(2, 2, 9, 9, BASE, PAPER, STROKE),
            line(14, 9, 14, 19, BASE, STROKE),
            line(9, 14, 19, 14, BASE, STROKE),
            polyline([(12.5, 10.5), (14, 9), (15.5, 10.5)], BASE, STROKE),
            polyline([(12.5, 17.5), (14, 19), (15.5, 17.5)], BASE, STROKE),
            polyline([(10.5, 12.5), (9, 14), (10.5, 15.5)], BASE, STROKE),
            polyline([(17.5, 12.5), (19, 14), (17.5, 15.5)], BASE, STROKE)]


def i_item_copy():
    return [rect(3, 3, 9, 9, BASE_LIGHT, PAPER, STROKE),
            rect(8, 8, 9, 9, BASE, PAPER, STROKE)]


def i_item_cancel():
    return [rect(3, 3, 9, 9, BASE, PAPER, STROKE)] + badge_delete(16, 16)


# ------------------------------------------------- conductor extensions ---
def i_conductor2():
    """Two conductors -- the multi-wire variant."""
    return [polyline([(4, 4), (4, 10), (18, 10)], BASE, STROKE),
            polyline([(8, 4), (8, 15), (18, 15)], GROUND, STROKE),
            line(4, 2, 4, 5, PHASE, STROKE), line(8, 2, 8, 5, PHASE, STROKE)]


def i_conductor_reset():
    """Reset conductor properties: a conductor plus a counter-clockwise revert
    arc.

    The head used to be a hand-placed polyline that did not touch the arc's end
    point, so it floated free of the curve. arc_arrow() derives both the head's
    position and its rotation from the arc's own end angle, which makes that
    class of mistake impossible.
    """
    return [polyline([(3, 4), (3, 10), (11, 10)], BASE, STROKE),
            line(3, 3, 3, 6, PHASE, STROKE)] + \
        arc_arrow(13, 13, 5, 250, -20, ACCENT, STROKE)


def i_autoconnect():
    """Automatic conductor creation.

    The first version put a lightning bolt above two stubs; the bolt dominated
    and read as "power", not "connect". Now it shows what the feature actually
    does -- two terminals, and the conductor QET routes between them drawn in
    the accent colour to mark it as the generated part.
    """
    return [line(4, 4, 4, 7, PHASE, STROKE),
            line(18, 15, 18, 18, PHASE, STROKE),
            polyline([(4, 6), (4, 11), (18, 11), (18, 16)], ACCENT, STROKE),
            dot(4, 11, 2.0, ACCENT), dot(18, 11, 2.0, ACCENT)]


def i_terminalstrip():
    """A terminal strip: a rail carrying a row of terminals."""
    return [solid(2, 13, 18, 3, BASE_LIGHT)] + \
        [x for i in (4, 9, 14) for x in
         (solid(i, 5, 4, 8, PAPER), rect(i, 5, 4, 8, BASE, 'none', THIN),
          line(i + 2, 3, i + 2, 6, PHASE, THIN))]


def i_titleblock_right():
    return [rect(3, 3, 16, 16, BASE, PAPER, STROKE),
            solid(14, 4, 4, 14, NEUTRAL),
            line(14, 9, 18, 9, PAPER, THIN), line(14, 14, 18, 14, PAPER, THIN)]


# ----------------------------------------------------------------- text ---
def i_text():
    return [f'<text x="11" y="18" font-family="sans-serif" font-size="18" '
            f'font-weight="bold" text-anchor="middle" fill="{BASE}">A</text>']


def i_textfield():
    return [rect(2, 6, 18, 10, BASE, PAPER, STROKE),
            line(6, 9, 6, 13, BASE, STROKE), line(4, 9, 8, 9, BASE, THIN),
            line(4, 13, 8, 13, BASE, THIN)]


def i_names():
    return [line(3, 6, 8, 6, BASE, STROKE), line(11, 6, 19, 6, BASE_LIGHT, STROKE),
            line(3, 11, 8, 11, BASE, STROKE), line(11, 11, 19, 11, BASE_LIGHT, STROKE),
            line(3, 16, 8, 16, BASE, STROKE), line(11, 16, 19, 16, BASE_LIGHT, STROKE)]


def i_simplifyrichtext():
    """Rich text -> plain text. Two overlapping glyphs merged into a blob, so
    this shows formatted lines being reduced to plain ones instead."""
    return [line(3, 5, 12, 5, BASE, 3.0),
            line(3, 10, 16, 10, BASE_LIGHT, THIN),
            line(3, 15, 19, 15, BASE, STROKE),
            line(15, 3, 20, 8, PHASE, STROKE),
            line(20, 3, 15, 8, PHASE, STROKE)]


def i_table_of_content():
    return [rect(3, 2, 16, 18, BASE, PAPER, STROKE),
            line(6, 6, 9, 6, BASE, STROKE), line(11, 6, 16, 6, BASE_LIGHT, THIN),
            line(6, 11, 9, 11, BASE, STROKE), line(11, 11, 16, 11, BASE_LIGHT, THIN),
            line(6, 16, 9, 16, BASE, STROKE), line(11, 16, 16, 16, BASE_LIGHT, THIN)]


def i_export_csv():
    return [rect(2, 3, 11, 16, BASE, PAPER, STROKE),
            solid(3, 4, 9, 3, BASE_LIGHT),
            line(2, 11, 13, 11, BASE, THIN), line(2, 15, 13, 15, BASE, THIN),
            line(6, 7, 6, 19, BASE, THIN), line(9.5, 7, 9.5, 19, BASE, THIN),
            line(13, 15, 19, 15, GROUND, STROKE),
            polyline([(16.5, 12.5), (19, 15), (16.5, 17.5)], GROUND, STROKE)]


def i_run_dxf():
    """Run the DXF tool. An X in a box read as "no"; this shows a drawing
    file -- the CAD geometry DXF actually carries -- plus a run arrow."""
    return [rect(2, 3, 11, 16, BASE, PAPER, STROKE),
            line(4, 14, 8, 8, NEUTRAL, THIN),
            line(8, 8, 11, 12, NEUTRAL, THIN),
            circle(6, 7, 2, NEUTRAL, 'none', THIN),
            f'<polygon points="14,7 20,11 14,15" fill="{GROUND}"/>']


def i_grid():
    return [x for gy in (5, 10, 15) for gx in (5, 10, 15)
            for x in (dot(gx, gy, 1.6, BASE),)]


def i_hotspot():
    return [circle(11, 11, 6, BASE, 'none', STROKE),
            line(11, 1, 11, 5, PHASE, STROKE), line(11, 17, 11, 21, PHASE, STROKE),
            line(1, 11, 5, 11, PHASE, STROKE), line(17, 11, 21, 11, PHASE, STROKE)]


def i_orientations():
    return [rect(6, 6, 10, 10, BASE, 'none', STROKE),
            f'<path d="M4,8 A8,8 0 0 1 11,2" fill="none" stroke="{NEUTRAL}" '
            f'stroke-width="{STROKE}"/>',
            polyline([(8, 2), (11, 2), (11, 5)], NEUTRAL, STROKE)]


def i_start():
    """Reset to the initial state."""
    return [f'<path d="M5,14 A7,7 0 1 1 11,18" fill="none" stroke="{BASE}" '
            f'stroke-width="{STROKE}"/>',
            polyline([(2, 11), (5, 15), (9, 12)], BASE, STROKE)]


def i_settings():
    return [line(4, 6, 18, 6, BASE, STROKE), dot(14, 6, 2.8, BASE),
            line(4, 11, 18, 11, BASE, STROKE), dot(8, 11, 2.8, BASE),
            line(4, 16, 18, 16, BASE, STROKE), dot(15, 16, 2.8, BASE)]


def i_masquer():
    """Hide: the eye, struck through."""
    return [f'<path d="M3,11 Q11,4.5 19,11 Q11,17.5 3,11 Z" fill="none" '
            f'stroke="{BASE_LIGHT}" stroke-width="{STROKE}"/>',
            circle(11, 11, 2.5, BASE_LIGHT, 'none', STROKE),
            line(4, 18, 18, 4, PHASE, STROKE)]


def i_restaurer():
    """Show."""
    return [f'<path d="M3,11 Q11,4.5 19,11 Q11,17.5 3,11 Z" fill="none" '
            f'stroke="{BASE}" stroke-width="{STROKE}"/>',
            dot(11, 11, 3, BASE)]


def i_go_company():
    return [rect(3, 6, 9, 13, BASE, PAPER, STROKE),
            rect(12, 10, 7, 9, BASE, PAPER, STROKE),
            solid(5, 9, 2, 2, NEUTRAL), solid(8, 9, 2, 2, NEUTRAL),
            solid(5, 13, 2, 2, NEUTRAL), solid(14, 13, 2, 2, NEUTRAL)]


def _double_chevron(up):
    s = 1 if up else -1
    return [polyline([(4, 11 + s * 1), (11, 11 - s * 5), (18, 11 + s * 1)], BASE, STROKE),
            polyline([(4, 11 + s * 8), (11, 11 + s * 2), (18, 11 + s * 8)], BASE, STROKE)]


def i_go_up_double():
    return _double_chevron(True)


def i_go_down_double():
    return _double_chevron(False)


# ------------------------------------- mismatches worth drawing ourselves ---
# Icons whose *name* matches a Breeze icon but whose *function* does not, so no
# stock glyph is right. Checking the QAction labels first dissolved most of the
# suspected mismatches -- see README. These four survived.

def i_project_clean():
    """QET::Icons::EditClear -- "Nettoyer le projet".

    Not Breeze's edit-clear (a tag with an X): this purges unused elements from
    a project. The existing broom is the apt metaphor and is kept, just drawn
    properly and given the project it acts on.
    """
    return [rect(2, 3, 11, 14, BASE, PAPER, STROKE),
            line(4, 7, 10, 7, BASE_LIGHT, THIN),
            line(4, 10, 10, 10, BASE_LIGHT, THIN),
            thick_line(19, 5, 14.5, 12, BASE, 2.5),
            f'<polygon points="16.5,10.5 12.5,13.5 15,18 19.5,15.5" '
            f'fill="{ACCENT}"/>',
            line(13.5, 15.0, 18.2, 12.3, PAPER, THIN)]


def i_panel_projects():
    """QET::Icons::ConfigureToolbars -- "Afficher les projets".

    Nothing to do with configuring toolbars: it toggles the projects panel.
    Drawn as a window with its side panel highlighted.
    """
    return [rect(2, 4, 18, 14, BASE, PAPER, STROKE),
            solid(3, 5, 6, 12, NEUTRAL),
            line(4, 8, 8, 8, PAPER, THIN),
            line(4, 11, 8, 11, PAPER, THIN),
            line(4, 14, 8, 14, PAPER, THIN),
            line(11, 8, 18, 8, BASE_LIGHT, THIN),
            line(11, 11, 18, 11, BASE_LIGHT, THIN)]


def i_folio_list():
    """QET::Icons::listDrawings -- a list of the project's folios."""
    return [rect(2, 2, 12, 15, BASE_LIGHT, PAPER, THIN),
            rect(5, 5, 14, 15, BASE, PAPER, STROKE),
            line(8, 9, 10, 9, BASE, STROKE), line(12, 9, 17, 9, BASE_LIGHT, THIN),
            line(8, 13, 10, 13, BASE, STROKE), line(12, 13, 17, 13, BASE_LIGHT, THIN),
            line(8, 17, 10, 17, BASE, STROKE), line(12, 17, 17, 17, BASE_LIGHT, THIN)]


def i_export_pdf():
    """QET::Icons::PDF -- "Exporter en pdf".

    Same page + green arrow construction as export-csv, so the two export
    actions read as a pair. Lettering was tried and dropped: "PDF" overflowed
    its band and is illegible at 16px regardless, so the red band alone
    carries the cue and distinguishes this from export-csv's table grid.
    """
    return [rect(2, 3, 12, 16, BASE, PAPER, STROKE),
            solid(1, 11, 14, 5, PHASE),
            line(3, 6, 11, 6, BASE_LIGHT, THIN),
            line(3, 8.5, 9, 8.5, BASE_LIGHT, THIN),
            line(13, 8, 19, 8, GROUND, STROKE),
            polyline([(16.5, 5.5), (19, 8), (16.5, 10.5)], GROUND, STROKE)]


ICONS = {
    'project-clean': i_project_clean,
    'panel-projects': i_panel_projects,
    'folio-list': i_folio_list,
    'export-pdf': i_export_pdf,
    'diagram': i_diagram,
    'diagram_add': i_diagram_add,
    'diagram_del': i_diagram_del,
    'diagram_bg': i_diagram_bg,
    'project': i_project,
    'project-new': i_project_new,
    'project-delete': i_project_delete,
    'project-properties': i_project_properties,
    'project-close': i_project_close,
    'folder-edit': i_folder_edit,
    'folder-delete': i_folder_delete,
    'folder-properties': i_folder_properties,
    'folder-only-this': i_folder_only_this,
    'folder-show-all': i_folder_show_all,
    'raise': i_raise,
    'lower': i_lower,
    'bring_forward': i_bring_forward,
    'send_backward': i_send_backward,
    'single_page': i_single_page,
    'two_pages': i_two_pages,
    'all_pages': i_all_pages,
    'portrait': i_portrait,
    'landscape': i_landscape,
    'view-fit-window': i_view_fit_window,
    'view_fit_width': i_view_fit_width,
    'flip': i_flip,
    'mirror': i_mirror,
    'move': i_move,
    'item-move': i_item_move,
    'item-copy': i_item_copy,
    'item-cancel': i_item_cancel,
    'conductor2': i_conductor2,
    'conductor-reset': i_conductor_reset,
    'autoconnect': i_autoconnect,
    'terminalstrip': i_terminalstrip,
    'titleblock-right': i_titleblock_right,
    'text': i_text,
    'textfield': i_textfield,
    'names': i_names,
    'simplifyrichtext': i_simplifyrichtext,
    'table-of-content': i_table_of_content,
    'export-csv': i_export_csv,
    'run-dxf': i_run_dxf,
    'grid': i_grid,
    'hotspot': i_hotspot,
    'orientations': i_orientations,
    'start': i_start,
    'settings': i_settings,
    'masquer': i_masquer,
    'restaurer': i_restaurer,
    'go-company': i_go_company,
    'go-up-double': i_go_up_double,
    'go-down-double': i_go_down_double,
    'line': i_line,
    'rectangle': i_rectangle,
    'circle': i_circle,
    'ellipse': i_ellipse,
    'arc': i_arc,
    'polygon': i_polygon,
    'endline-none': i_endline_none,
    'endline-simple': i_endline_simple,
    'endline-circle': i_endline_circle,
    'endline-diamond': i_endline_diamond,
    'endline-triangle': i_endline_triangle,
    'element': i_element,
    'element-new': i_element_new,
    'element-delete': i_element_delete,
    'element-edit': i_element_edit,
    'element-master': i_element_master,
    'element-slave': i_element_slave,
    'folio-new': i_folio_new,
    'folio-delete': i_folio_delete,
    'folio-properties': i_folio_properties,
    'folio-ref-coming': i_folio_ref_coming,
    'terminal': i_terminal,
    'conductor': i_conductor,
    'conductor-edit': i_conductor_edit,
    'ground': i_ground,
    'phase': i_phase,
    'neutral': i_neutral,
    'north': i_north,
    'south': i_south,
    'east': i_east,
    'west': i_west,
    'titleblock-bottom': i_titleblock_bottom,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-o', '--outdir', default='domain-svg')
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    for name, fn in ICONS.items():
        p = os.path.join(args.outdir, name + '.svg')
        open(p, 'w').write(svg(fn(), SIZE))
    print(f'wrote {len(ICONS)} icons to {args.outdir}/')


if __name__ == '__main__':
    main()
