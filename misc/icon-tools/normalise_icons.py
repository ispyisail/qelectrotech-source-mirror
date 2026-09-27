#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Audit and normalise optical sizing across the icon set.

Drawing 88 icons to a stroke spec keeps *weight* consistent but not *optical
size*: each glyph still ends up whatever size its own geometry happens to be.
Measured across the set the ink box ranged 10-22 wide and 2-20 tall against an
18x18 target, and several icons sat visibly off-centre or ran into the canvas
edge. In a toolbar that reads as "the sizes are wrong".

This measures the real ink extents of every icon (by rendering, not by parsing
path data) and reports which fall outside tolerance. With --apply it wraps the
content in a translate() so the ink is centred on the canvas.

Translation only, never scale: scaling a group scales its stroke widths too,
which would break the uniform 2px weight the spec exists to guarantee. Icons
that are genuinely the wrong *size* are listed for a geometry fix by hand.

    normalise_icons.py --dir ico/scalable            # audit
    normalise_icons.py --dir ico/scalable --apply    # centre them
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile

from PIL import Image

CANVAS = 22.0
SAFE = 1.0          # keep ink at least this far from the edge
TARGET_MIN = 13.0   # below this an icon looks undersized beside its neighbours
TARGET_MAX = 20.0   # above this it crowds the cell
OVERSAMPLE = 10


def ink_box(svg_path):
    """Ink extents in canvas units, measured from a 10x render."""
    px = int(CANVAS * OVERSAMPLE)
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as t:
        tmp = t.name
    try:
        r = subprocess.run(['rsvg-convert', '-w', str(px), '-h', str(px),
                            '-o', tmp, svg_path], capture_output=True)
        if r.returncode:
            return None
        bb = Image.open(tmp).convert('RGBA').getbbox()
    finally:
        os.unlink(tmp)
    if not bb:
        return None
    return tuple(v / OVERSAMPLE for v in bb)


def apply_translate(svg_path, dx, dy):
    """Wrap the drawing in a translate. Idempotent: an existing wrapper is
    replaced rather than nested, so re-running cannot drift the icon."""
    s = open(svg_path, encoding='utf-8').read()
    s = re.sub(r'<g class="nrm"[^>]*>\n?(.*)\n?</g>\n', r'\1\n',
               s, flags=re.S)
    m = re.search(r'(<svg[^>]*>)(.*)(</svg>)', s, re.S)
    if not m:
        return False
    head, body, tail = m.groups()
    wrapped = (f'{head}\n<g class="nrm" transform="translate({dx:.2f},{dy:.2f})">'
               f'{body.rstrip()}\n</g>\n{tail}')
    open(svg_path, 'w', encoding='utf-8').write(s[:m.start()] + wrapped)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--tol', type=float, default=0.5,
                    help='centre offset tolerated before re-centring')
    ap.add_argument('--skip', default='',
                    help='comma-separated icons to leave alone (families whose '
                         'off-centre placement is deliberate)')
    args = ap.parse_args()

    if subprocess.run(['which', 'rsvg-convert'], capture_output=True).returncode:
        sys.exit('rsvg-convert not found -- apt-get install librsvg2-bin')

    skip = {s for s in args.skip.split(',') if s}
    names = sorted(f[:-4] for f in os.listdir(args.dir) if f.endswith('.svg'))

    centred, small, big, clipped = [], [], [], []
    for n in names:
        p = os.path.join(args.dir, n + '.svg')
        bb = ink_box(p)
        if not bb:
            continue
        x0, y0, x1, y1 = bb
        w, h = x1 - x0, y1 - y0
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        dx, dy = CANVAS / 2 - cx, CANVAS / 2 - cy

        if x0 < SAFE - 0.01 or y0 < SAFE - 0.01 or x1 > CANVAS - SAFE + 0.01 \
                or y1 > CANVAS - SAFE + 0.01:
            clipped.append((n, x0, y0, x1, y1))
        if max(w, h) < TARGET_MIN:
            small.append((n, w, h))
        if max(w, h) > TARGET_MAX:
            big.append((n, w, h))

        if n in skip:
            continue
        if abs(dx) > args.tol or abs(dy) > args.tol:
            centred.append((n, dx, dy))
            if args.apply:
                apply_translate(p, dx, dy)

    print(f'icons measured        : {len(names)}')
    print(f'off-centre (> {args.tol})    : {len(centred)}'
          + ('  -- centred' if args.apply else '  -- run with --apply'))
    for n, dx, dy in centred[:14]:
        print(f'    {n:<24} {dx:+.1f},{dy:+.1f}')
    print(f'\nundersized (< {TARGET_MIN:.0f})     : {len(small)}   '
          f'-- need a geometry fix, not a nudge')
    for n, w, h in small:
        print(f'    {n:<24} {w:.1f}x{h:.1f}')
    print(f'\noversized  (> {TARGET_MAX:.0f})     : {len(big)}')
    for n, w, h in big:
        print(f'    {n:<24} {w:.1f}x{h:.1f}')
    print(f'\ninside the {SAFE:.0f}px margin  : {len(clipped)} breach it')
    for n, x0, y0, x1, y1 in clipped[:12]:
        print(f'    {n:<24} x {x0:.1f}-{x1:.1f}  y {y0:.1f}-{y1:.1f}')


if __name__ == '__main__':
    main()
