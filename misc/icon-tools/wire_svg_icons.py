#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Point qeticons.cpp and qelectrotech.qrc at the new SVGs in ico/scalable/.

For every QET::Icons symbol whose PNG asset has an SVG replacement, the
symbol's addFile() lines collapse to a single scalable one. One SVG serves
every size, so the multi-size PNG pattern is no longer needed for these.

Superseded PNGs are deliberately left on disk: this keeps the change additive
and easy to revert, and avoids breaking anything that still references them by
path. Removing them is follow-up work, not part of a preview.

    wire_svg_icons.py --repo /path/to/checkout [--dry-run]
"""

import argparse
import os
import re
import sys

# Four icons were renamed because the old filename described the wrong thing.
RENAMED = {
    "edit-clear": "project-clean",
    "configure-toolbars": "panel-projects",
    "view-pim-journal": "folio-list",
    "application-pdf": "export-pdf",
}

ADDFILE = re.compile(
    r'^(?P<indent>\s*)(?P<sym>[A-Za-z_]\w*)\s*\.\s*addFile\s*\(\s*"'
    r'(?P<path>:/ico/[^"]+)"\s*\)\s*;\s*$')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', required=True)
    ap.add_argument('--svg-dir', default='ico/scalable')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    svg_abs = os.path.join(args.repo, args.svg_dir)
    have = {f[:-4] for f in os.listdir(svg_abs) if f.endswith('.svg')}
    if not have:
        sys.exit(f'no SVGs in {svg_abs}')

    cpp_path = os.path.join(args.repo, 'sources/qeticons.cpp')
    lines = open(cpp_path, encoding='utf-8').read().splitlines(keepends=True)

    # symbol -> the new SVG that should serve it
    target, seen = {}, set()
    for ln in lines:
        m = ADDFILE.match(ln)
        if not m:
            continue
        base = os.path.basename(m.group('path'))
        base = base[:-4] if base.endswith('.png') else base
        new = RENAMED.get(base, base)
        if new in have:
            target.setdefault(m.group('sym'), new)

    out, emitted, dropped = [], set(), 0
    for ln in lines:
        m = ADDFILE.match(ln)
        if not m or m.group('sym') not in target:
            out.append(ln)
            continue
        sym = m.group('sym')
        if sym in emitted:
            dropped += 1           # superseded by the scalable entry above
            continue
        emitted.add(sym)
        pad = ' ' * max(1, 20 - len(sym))
        out.append(f'{m.group("indent")}{sym}{pad}'
                   f'.addFile(":/{args.svg_dir}/{target[sym]}.svg");\n')

    qrc_path = os.path.join(args.repo, 'qelectrotech.qrc')
    qrc = open(qrc_path, encoding='utf-8').read()
    entries = '\n'.join(f'        <file>{args.svg_dir}/{n}.svg</file>'
                        for n in sorted(have))
    if f'{args.svg_dir}/' not in qrc:
        anchor = qrc.index('<file>')
        anchor = qrc.rindex('\n', 0, anchor) + 1
        qrc = qrc[:anchor] + entries + '\n' + qrc[anchor:]

    print(f'SVGs available          : {len(have)}')
    print(f'symbols repointed       : {len(emitted)}')
    print(f'redundant PNG lines gone: {dropped}')
    print(f'qrc entries added       : {len(have)}')
    unused = sorted(have - set(target.values()))
    if unused:
        print(f'\nSVGs no symbol uses ({len(unused)}): {", ".join(unused)}')

    if args.dry_run:
        print('\n(dry run, nothing written)')
        return
    open(cpp_path, 'w', encoding='utf-8').write(''.join(out))
    open(qrc_path, 'w', encoding='utf-8').write(qrc)
    print('\nwrote qeticons.cpp and qelectrotech.qrc')


if __name__ == '__main__':
    main()
