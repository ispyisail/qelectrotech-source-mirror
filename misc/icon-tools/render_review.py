#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Stage 3 of the icon audit: render current icon vs proposed candidates.

The matcher ranks by *name* semantics; whether a candidate actually reads as
the right thing, and looks good, can only be judged by eye. This builds
contact sheets so that judgement is cheap to make.

Requires rsvg-convert (librsvg2-bin) and Pillow.

Usage:
    render_review.py --candidates candidates.json --theme /path/to/breeze-icons \\
                     --qet-ico /path/to/qelectrotech/ico [--changed-only] -o review
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict

from PIL import Image, ImageDraw

PX = 22           # logical icon size to compare at
ZOOM = 4          # magnification for legibility
COLS = 1
PER_SHEET = 14


def theme_index(theme_dir):
    idx = defaultdict(dict)
    root = os.path.join(theme_dir, 'icons')
    if not os.path.isdir(root):
        root = theme_dir
    for dirpath, _d, files in os.walk(root):
        m = re.search(r'/(\d+)(?:@\dx)?$', dirpath)
        if not m:
            continue
        size = int(m.group(1))
        for f in files:
            if f.endswith('.svg'):
                idx[f[:-4]][size] = os.path.join(dirpath, f)
    return idx


def render_svg(path, px, out):
    r = subprocess.run(['rsvg-convert', '-w', str(px), '-h', str(px), '-o', out, path],
                       capture_output=True)
    return r.returncode == 0 and os.path.exists(out)


def chip(img_path, px=PX, zoom=ZOOM):
    side = px * zoom
    bg = Image.new('RGBA', (side, side), (255, 255, 255, 255))
    if img_path and os.path.exists(img_path):
        im = Image.open(img_path).convert('RGBA')
        if im.size != (side, side):
            im = im.resize((side, side), Image.NEAREST)
        bg.alpha_composite(im)
    else:
        d = ImageDraw.Draw(bg)
        d.line((0, 0, side, side), fill=(220, 220, 220), width=2)
        d.line((0, side, side, 0), fill=(220, 220, 220), width=2)
    return bg


def find_current(qet_ico, name):
    for d in ('22x22', '16x16', '32x32', '48x48'):
        p = os.path.join(qet_ico, d, name + '.png')
        if os.path.exists(p):
            return p
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--candidates', default='candidates.json')
    ap.add_argument('--theme', required=True)
    ap.add_argument('--qet-ico', required=True)
    ap.add_argument('--top', type=int, default=3)
    ap.add_argument('--changed-only', action='store_true',
                    help='only icons whose top candidate differs from the current asset')
    ap.add_argument('-o', '--outdir', default='review')
    args = ap.parse_args()

    if subprocess.run(['which', 'rsvg-convert'], capture_output=True).returncode:
        sys.exit('rsvg-convert not found -- apt-get install librsvg2-bin')

    idx = theme_index(args.theme)
    recs = [r for r in json.load(open(args.candidates)) if r['candidates']]
    if args.changed_only:
        recs = [r for r in recs if not r['top_is_current']]
    recs.sort(key=lambda r: -r['candidates'][0]['score'])

    os.makedirs(args.outdir, exist_ok=True)
    tmp = os.path.join(args.outdir, '_tmp')
    os.makedirs(tmp, exist_ok=True)

    side = PX * ZOOM
    pad = 10
    cell_h = side + 2 * pad
    label_w = 300
    cell_w = label_w + (args.top + 1) * (side + pad) + pad

    sheets = []
    for s in range(0, len(recs), PER_SHEET):
        chunk = recs[s:s + PER_SHEET]
        img = Image.new('RGB', (cell_w, len(chunk) * cell_h + 34), (245, 245, 245))
        d = ImageDraw.Draw(img)
        d.text((pad, 10), f'current | candidates ranked by function  '
                          f'-- sheet {s // PER_SHEET + 1}', fill=(0, 0, 0))
        for i, r in enumerate(chunk):
            y = i * cell_h + 34
            d.text((pad, y + pad + 4), r['symbol'][:26], fill=(0, 0, 0))
            d.text((pad, y + pad + 22), (r['labels'][0] if r['labels'] else '')[:40],
                   fill=(110, 110, 110))
            x = label_w
            cur = find_current(args.qet_ico, r['current_asset']) if r['current_asset'] else None
            img.paste(chip(cur).convert('RGB'), (x, y + pad))
            d.rectangle([x - 2, y + pad - 2, x + side + 1, y + pad + side + 1],
                        outline=(160, 160, 160))
            for j, c in enumerate(r['candidates'][:args.top]):
                x += side + pad
                src = idx.get(c['name'], {})
                pick = src.get(PX) or (src[max(src)] if src else None)
                png = os.path.join(tmp, f'{c["name"]}_{PX}.png')
                ok = pick and (os.path.exists(png) or render_svg(pick, side, png))
                img.paste(chip(png if ok else None).convert('RGB'), (x, y + pad))
                d.text((x, y + pad + side + 1), f'{c["name"][:14]} {c["score"]:.1f}',
                       fill=(90, 90, 90))
        p = os.path.join(args.outdir, f'review{s // PER_SHEET + 1}.png')
        img.save(p)
        sheets.append(p)

    print(f'{len(recs)} icons -> {len(sheets)} sheets in {args.outdir}/')
    for p in sheets:
        print(' ', p)


if __name__ == '__main__':
    main()
