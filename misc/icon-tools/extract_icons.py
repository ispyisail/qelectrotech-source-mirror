#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Stage 1 of the icon audit: work out what each QET icon actually *does*.

Filename matching against an icon theme is unreliable -- a visual pass over the
93 name-matches found 21 where upstream Breeze depicts a different thing
entirely (QET's `go-home` is a person, Breeze's is a house; QET's `guides` is
page guides, Breeze's is audio connectors).

A better signal is the label of the QAction the icon is attached to. This script
harvests that, producing one record per QET::Icons symbol:

    symbol, asset files, the UI strings it appears next to, where it is used

Output: icons.json  (consumed by match_icons.py)

Usage:
    extract_icons.py --qet-source /path/to/qelectrotech-source-mirror
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict

# QET::Icons::Foo -- the symbol as referenced at call sites
SYMBOL_RE = re.compile(r'QET::Icons::([A-Za-z_][A-Za-z0-9_]*)')

# Icons.addFile(":/ico/22x22/arrow-left.png");  in qeticons.cpp
ADDFILE_RE = re.compile(
    r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*addFile\s*\(\s*"([^"]+)"', re.M)

# tr("...") / QObject::tr("...") -- first arg only, second is a translator hint
TR_RE = re.compile(r'\btr\s*\(\s*"((?:[^"\\]|\\.)*)"')


def parse_registry(qeticons_cpp):
    """symbol -> [asset paths], from the central QET::Icons registry."""
    src = open(qeticons_cpp, encoding='utf-8', errors='replace').read()
    reg = defaultdict(list)
    for sym, path in ADDFILE_RE.findall(src):
        reg[sym].append(path)
    return reg


# the variable an icon is being assigned to, so tips can be attributed to it
ASSIGN_RE = re.compile(r'([A-Za-z_][\w>\-\.]*)\s*(?:=|->\s*setIcon\s*\()')
TIP_RE = re.compile(r'([A-Za-z_][\w>\-\.]*)\s*->\s*set(?:StatusTip|ToolTip|Text)\s*\(')


def _statement_at(text, pos):
    """The single C++ statement containing `pos`: forward to the `;` at depth 0."""
    depth, i, n = 0, pos, len(text)
    while i < n:
        c = text[i]
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        elif c == ';' and depth <= 0:
            break
        i += 1
    start = text.rfind(';', 0, pos) + 1
    return text[start:i + 1]


def harvest_usages(sources_dir):
    """symbol -> [{file, line, strings, tips, context}] for every call site.

    Strings are taken from the *statement* the symbol appears in, not a fixed
    line window -- a window bleeds labels in from neighbouring statements (it
    gave ZoomFitBest "Ajouter une ligne" from the next line down).
    """
    usages = defaultdict(list)
    for root, _dirs, files in os.walk(sources_dir):
        for fn in files:
            if not fn.endswith(('.cpp', '.h')):
                continue
            p = os.path.join(root, fn)
            try:
                text = open(p, encoding='utf-8', errors='replace').read()
            except OSError:
                continue
            rel = os.path.relpath(p, sources_dir)
            for m in SYMBOL_RE.finditer(text):
                sym = m.group(1)
                stmt = _statement_at(text, m.start())
                strings = [s for s in TR_RE.findall(stmt) if s.strip()]

                # Tips set on the same variable, later in the same scope.
                tips = []
                am = ASSIGN_RE.search(stmt)
                if am:
                    var = re.escape(am.group(1).strip())
                    tail = text[m.end():m.end() + 1500]
                    for tm in TIP_RE.finditer(tail):
                        if tm.group(1).strip() == am.group(1).strip():
                            tips += [s for s in TR_RE.findall(
                                _statement_at(tail, tm.start())) if s.strip()]
                    del var

                usages[sym].append({
                    'file': rel,
                    'line': text.count('\n', 0, m.start()) + 1,
                    'strings': strings,
                    'tips': tips,
                    'context': stmt.strip().replace('\n', ' ')[:160],
                })
    return usages


def split_symbol(sym):
    """CamelCase / IC_CopyFile -> lowercase word tokens."""
    sym = re.sub(r'^IC_', '', sym)
    return [w.lower() for w in re.findall(r'[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|\d+', sym)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--qet-source', required=True,
                    help='root of a qelectrotech-source-mirror checkout')
    ap.add_argument('-o', '--out', default='icons.json')
    args = ap.parse_args()

    sources = os.path.join(args.qet_source, 'sources')
    qeticons = os.path.join(sources, 'qeticons.cpp')
    for p in (sources, qeticons):
        if not os.path.exists(p):
            sys.exit(f'not found: {p}  (is --qet-source correct?)')

    registry = parse_registry(qeticons)
    usages = harvest_usages(sources)

    records = []
    for sym in sorted(set(registry) | set(usages)):
        u = usages.get(sym, [])
        strings, tips, seen = [], [], set()
        for entry in u:
            for s in entry['strings']:
                if s not in seen:
                    seen.add(s)
                    strings.append(s)
            for s in entry['tips']:
                if s not in seen:
                    seen.add(s)
                    tips.append(s)
        records.append({
            'symbol': sym,
            'tokens': split_symbol(sym),
            'assets': registry.get(sym, []),
            'strings': strings,
            'tips': tips,
            'use_count': len(u),
            'used_at': [f"{e['file']}:{e['line']}" for e in u[:6]],
            'declared_only': sym in registry and not u,
            'undeclared': bool(u) and sym not in registry,
        })

    json.dump(records, open(args.out, 'w'), indent=1, ensure_ascii=False)

    n = len(records)
    with_str = sum(1 for r in records if r['strings'])
    print(f'symbols                 : {n}')
    print(f'  with an asset in .cpp : {sum(1 for r in records if r["assets"])}')
    print(f'  used somewhere        : {sum(1 for r in records if r["use_count"])}')
    print(f'  with a UI label       : {with_str}  ({100 * with_str // max(n, 1)}%)')
    print(f'  declared but unused   : {sum(1 for r in records if r["declared_only"])}')
    print(f'\nwrote {args.out}')


if __name__ == '__main__':
    main()
