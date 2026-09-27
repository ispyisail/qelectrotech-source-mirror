# Icon tools — match QET icons to a theme, and draw the ones no theme has

Two halves. **Matching** (below) shortlists Breeze icons by what each QET
button does, for a human to review. **Drawing** (at the end) generates SVGs
for the QElectroTech-specific icons no theme provides: conductors, terminals,
line ends, cross-references, title blocks.

Python 3. Matching needs `rsvg-convert` (librsvg) for the review sheets;
`normalise_icons.py` needs Pillow and `rsvg-convert`. Licence: GPL-2.0-or-later,
as QElectroTech.


Filename matching against an icon theme is unreliable. A visual pass over the 93
QET icons whose names match KDE Breeze found **21 where upstream depicts a
different thing entirely**: QET's `go-home` is a person, Breeze's is a house;
QET's `guides` is page guides, Breeze's is audio connectors; QET's `label.png`
is really the *TitleBlock* icon, so Breeze's `label` (a price tag) is wrong for
it.

This pipeline instead asks what each icon *does* — from its `QET::Icons` symbol
name and the `QAction` labels it appears next to — and shortlists theme icons
that express that function. It produces **candidates for human review**, never
an automatic decision.

## Pipeline

```bash
# 1. What does each icon do?  -> icons.json
./extract_icons.py --qet-source /path/to/qelectrotech-source-mirror

# 2. Rank theme icons by function  -> candidates.json
git clone --depth 1 https://github.com/KDE/breeze-icons.git
./match_icons.py --icons icons.json --theme breeze-icons --top 5

# 3. Render current vs candidates for eyeballing  -> review/*.png
sudo apt-get install librsvg2-bin        # rsvg-convert
./render_review.py --candidates candidates.json --theme breeze-icons \
                   --qet-ico /path/to/qelectrotech-source-mirror/ico \
                   --changed-only
```

`lexicon.json` maps French UI vocabulary to the English tokens used in
freedesktop icon names. It was derived from the actual label corpus rather than
guessed, and is meant to be edited.

## How the semantics are derived

`extract_icons.py` reads two things:

- **`sources/qeticons.cpp`** — the central registry, `symbol -> asset files`.
- **every `QET::Icons::Foo` call site** — capturing `tr()` strings from the
  *enclosing C++ statement* (not a line window; a window bleeds in labels from
  neighbouring statements) plus `setStatusTip`/`setToolTip` on the same variable.

Signal quality on a 350-symbol run: 348 have an asset, 312 are used somewhere,
**286 (81%) carry a usable UI label**.

Weighting in `match_icons.py`: symbol tokens ×3 (a developer named it for its
role), primary action label ×2, secondary labels ×0.75, tooltips ×1. Scoring is
cosine-ish token overlap with IDF, so rare tokens count for more.

## Known hazard: false friends

Domain words collide with unrelated application names:

| QET icon | means | naive match | actually |
|---|---|---|---|
| `Terminal` | electrical terminal (*borne*) | `utilities-terminal` | a shell console |
| `North`/`South`/`East`/`West` | terminal orientation | `kruler-north`… | a screen-ruler app |

`CATEGORY_WEIGHT` in `match_icons.py` damps `apps`/`applets`/`devices` icons,
which removes the `utilities-terminal` class of error. It does **not** catch
`kruler-*`, which lives in `actions` — that one needs the human pass.

This is why stage 3 exists and why the matching half never writes to the source tree.

## What it will not solve

Genuinely domain-specific icons — `conductor`, `ground`, `phase`, `neutral`,
terminal orientations, `endline-*` styles — have no equivalent in a general
icon theme. The matcher returns weak or no candidates for them, correctly. Those
need drawing, not matching.

## Drawing the domain icons

```bash
./make_domain_icons.py -o out/            # writes out/<name>.svg, 89 icons
./normalise_icons.py --dir out/           # audit: ink box size and centring
./normalise_icons.py --dir out/ --apply   # centre each icon (translate only)
./wire_svg_icons.py --repo /path/to/qelectrotech-source-mirror --dry-run
```

- **`iconspec.py`** is the spec every icon is drawn to: a 22 px canvas (16 and
  32 px are rendered from the same art), 2 px strokes, the colours measured from QET's existing icons
  (dark grey `#4d4d4d`, red/blue terminals, green ground, Breeze blue and
  red), and the primitives (`line`, `rect`, `terminal_stub`, `arc_arrow`, …).
  Change a value here and every icon follows.
- **`make_domain_icons.py`** holds one small function per icon, and the
  `ICONS` table maps QET icon names to them. Add an icon by writing a
  function and adding a row.
- **`normalise_icons.py`** measures each icon's ink by rendering it and
  centres it with a `translate()`. It never scales, because scaling would
  change the stroke width. Icons that are genuinely the wrong size are listed
  for a fix by hand.
- **`wire_svg_icons.py`** points `sources/qeticons.cpp` and the `.qrc` at the
  SVGs in `ico/scalable/`. It leaves the old PNGs on disk.

The 88 SVGs on the `feature/svg-domain-icons` branch of
`ispyisail/qelectrotech-source-mirror` came from these scripts. Regenerated
today, 87 are byte-identical. The exceptions: `endline-diamond`, which the
centring step now nudges 0.75 px, and `project-delete`, which the generator
draws but the branch does not have.
