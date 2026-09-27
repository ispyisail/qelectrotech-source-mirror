#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Stage 2 of the icon audit: propose icon-theme candidates by *function*.

Filename matching is unreliable -- QET's `label.png` is really the TitleBlock
icon, so Breeze's `label` (a price tag) is wrong for it. This scores every
theme icon against what a QET icon actually does, derived from its QET::Icons
symbol name and the QAction labels it appears with (see extract_icons.py).

Output is a *ranked shortlist for human review*, never an automatic decision:
the point is to find a good indicator of the function, and that is a judgement
call a script cannot close.

Usage:
    match_icons.py --icons icons.json --theme /path/to/breeze-icons \\
                   [--top 5] [--only-unmatched] -o candidates.json
"""

import argparse
import json
import math
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))

# tokens that say nothing about what an icon depicts
NOISE = set("""the of to this that with new all and or for from into a an is are be
le la les un une des du de et ou ce cet cette ces en sur dans par pour qui est
sont son sa ses dev tous toutes plus moins ici cela nbsp amp lt gt quot""".split())


def strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s)
                   if unicodedata.category(c) != 'Mn')


def words(s):
    return [w for w in re.findall(r"[a-z]{2,}", strip_accents(s).lower())
            if w not in NOISE]


def load_theme(theme_dir):
    """icon name -> {'sizes': set, 'categories': set} from <theme>/icons/<cat>/<size>/."""
    icons = defaultdict(lambda: {'sizes': set(), 'categories': set()})
    root = os.path.join(theme_dir, 'icons')
    if not os.path.isdir(root):
        root = theme_dir
    for dirpath, _dirs, files in os.walk(root):
        m = re.search(r'/([^/]+)/(\d+)(?:@\dx)?$', dirpath)
        for f in files:
            if not f.endswith('.svg'):
                continue
            rec = icons[f[:-4]]
            if m:
                rec['categories'].add(m.group(1))
                rec['sizes'].add(int(m.group(2)))
    return icons


def query_tokens(rec, lexicon):
    """Weighted bag of English concept tokens describing what this icon does.

    The symbol name is the most reliable signal (a developer named it for its
    role); the primary QAction label next; tooltips are the loosest.
    """
    bag = Counter()

    def add(src, weight):
        for w in words(src):
            for t in lexicon.get(w, [w]):
                bag[t] += weight

    for t in rec.get('tokens', []):
        for x in lexicon.get(t, [t]):
            bag[x] += 3.0
    for s in rec.get('strings', [])[:2]:
        add(s, 2.0)
    for s in rec.get('strings', [])[2:4]:
        add(s, 0.75)
    for s in rec.get('tips', [])[:2]:
        add(s, 1.0)
    return bag


# A toolbar button wants an *action* glyph. Application/device icons share
# vocabulary with domain terms and produce false friends: an electrical
# "borne" (terminal) scores `utilities-terminal`, which is a shell console.
CATEGORY_WEIGHT = {
    'actions': 1.0,
    'status': 0.9,
    'places': 0.85,
    'mimetypes': 0.8,
    'preferences': 0.8,
    'emblems': 0.7,
    'devices': 0.45,
    'applets': 0.35,
    'apps': 0.3,
}


def score(bag, name_tokens, idf, categories=()):
    """Cosine-ish overlap, rare tokens weighted higher, damped by category."""
    if not bag or not name_tokens:
        return 0.0
    hit = sum(bag[t] * idf.get(t, 1.0) for t in name_tokens if t in bag)
    if not hit:
        return 0.0
    norm = math.sqrt(sum(v * v for v in bag.values())) * math.sqrt(len(name_tokens))
    if not norm:
        return 0.0
    cw = max((CATEGORY_WEIGHT.get(c, 0.6) for c in categories), default=1.0)
    return (hit / norm) * cw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--icons', default='icons.json')
    ap.add_argument('--theme', required=True, help='icon theme checkout (e.g. breeze-icons)')
    ap.add_argument('--lexicon', default=os.path.join(HERE, 'lexicon.json'))
    ap.add_argument('--top', type=int, default=5)
    ap.add_argument('--min-score', type=float, default=0.10)
    ap.add_argument('--skip-colors', action='store_true', default=True,
                    help='skip generated colour-swatch icons (not UI chrome)')
    ap.add_argument('-o', '--out', default='candidates.json')
    args = ap.parse_args()

    if not os.path.isdir(args.theme):
        sys.exit(f'theme not found: {args.theme}')

    lexicon = {k: v for k, v in json.load(open(args.lexicon)).items()
               if not k.startswith('_')}
    records = json.load(open(args.icons))
    theme = load_theme(args.theme)
    if not theme:
        sys.exit(f'no .svg icons found under {args.theme}')

    name_tokens = {n: words(n.replace('-', ' ').replace('_', ' ')) for n in theme}

    df = Counter()
    for toks in name_tokens.values():
        df.update(set(toks))
    N = len(name_tokens)
    idf = {t: math.log(N / (1 + c)) + 1.0 for t, c in df.items()}

    # Not UI chrome, and actively harmful to score: the 24x16 set is country
    # flags whose two-letter names collide with real words ("no" -> gtk-no,
    # "it"/"br"/"tr"/"nl"/"da" likewise). Colour swatches are generated.
    def is_data_asset(paths):
        return bool(paths) and all(('/color/' in p or '/24x16/' in p) for p in paths)

    # helpers in qeticons.cpp that the symbol regex also picks up
    NOT_AN_ICON = {'initIcons', 'Icons'}

    out, skipped = [], 0
    for rec in records:
        assets = rec.get('assets', [])
        if rec['symbol'] in NOT_AN_ICON:
            skipped += 1
            continue
        if args.skip_colors and is_data_asset(assets):
            skipped += 1
            continue
        bag = query_tokens(rec, lexicon)
        if not bag:
            skipped += 1
            continue
        ranked = sorted(
            ((score(bag, name_tokens[n], idf, theme[n]['categories']), n)
             for n in theme),
            key=lambda x: (-x[0], x[1]))[:args.top]
        cands = [{'name': n,
                  'score': round(s, 4),
                  'sizes': sorted(theme[n]['sizes']),
                  'categories': sorted(theme[n]['categories'])}
                 for s, n in ranked if s >= args.min_score]
        current = os.path.basename(assets[0])[:-4] if assets else None
        out.append({
            'symbol': rec['symbol'],
            'current_asset': current,
            'labels': rec.get('strings', [])[:2],
            'query': [t for t, _ in bag.most_common(8)],
            'candidates': cands,
            'top_is_current': bool(cands and current and cands[0]['name'] == current),
        })

    json.dump(out, open(args.out, 'w'), indent=1, ensure_ascii=False)

    withc = [r for r in out if r['candidates']]
    print(f'theme icons indexed      : {N}')
    print(f'QET icons scored         : {len(out)}   (skipped {skipped})')
    print(f'  with >=1 candidate     : {len(withc)}')
    print(f'  none above --min-score : {len(out) - len(withc)}')
    print(f'  top candidate == current asset : '
          f'{sum(1 for r in out if r["top_is_current"])}')
    print(f'\nwrote {args.out}')


if __name__ == '__main__':
    main()
