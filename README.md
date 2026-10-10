# .qetz prototype converter

A prototype, outside QElectroTech, of the zipped project file from Joshua's
roadmap note (`refonte_du_code_de_qelectrotech` on the wiki). It converts a
`.qet` into a `.qetz` and back, so "every older project still opens" can be
measured instead of promised. Discussion: https://github.com/qelectrotech/qelectrotech-source-mirror/discussions/1440

It needs only Python 3, nothing else to install. It runs on your own computer and sends
nothing anywhere. It never changes the file you give it.

```bash
python3 qetcontainer.py check MyProject.qet         # convert and back, compare, print sizes
python3 qetcontainer.py split MyProject.qet out.qetz
python3 qetcontainer.py join  out.qetz back.qet
./gate.sh /path/to/qelectrotech MyProject.qet       # Linux: compare QElectroTech's own resaves
```

`check` prints one line per file: `LOSSLESS` when the file came back with
the same content (every tag, value and comment, in order), or the first
difference. **If you get anything other than LOSSLESS, please say so in the
discussion** — that is exactly what this is for. You do not need to share
the project.

## What is inside a .qetz

```
manifest.xml          format version, oldest reader allowed
project.sqlite        engineering data: folio and project information,
                      symbol information, coil–contact links, wires,
                      terminal strips (terminals, levels, bridges)
folios/<id>.xml       one per folio: where things are drawn
elements/             the project's symbols, one .elmt each
titleblocks/          one .titleblock each
images/               pictures as real files, no base64
conf/newdiagrams.xml  defaults for new folios
```

The rule for what goes where: would an engineer put it in a list → database;
does it only say where ink goes → folio file; can QElectroTech work it out
(labels from a formula, `%total`) → not treated as data.

## Results so far (2026-10-10, master 613f05a05)

| Files | `check` | `gate.sh` |
|---|---|---|
| 25 shipped examples | 25 / 25 | 25 / 25 |
| 9 bugtracker attachments (QElectroTech 0.4 – 0.100) | 9 / 9 | 8 same, 1 that QElectroTech itself does not resave the same way twice |
| 4 GitHub issue attachments (up to 148 folios) | 4 / 4 | 4 / 4 |
| a test file with symbols sharing a uuid (#1408) | 1 / 1 | 1 / 1 |
| a test file with two terminal strips and bridges | 1 / 1 | 1 / 1 |

41.3 MB of `.qet` became 9.3 MB of `.qetz`.

## Traps found on the way

- A carriage return inside a value must be written `&#13;`, or it comes
  back as a newline.
- QElectroTech reads XML namespaces literally: moving an SVG logo's
  `xmlns` declaration made it drop every title block with a logo.
- Comments inside SVG logos survive QElectroTech today, so they must
  survive the container too.

This is a prototype for discussion, not a file format anyone should save
real work in. License: GPL-2.0-or-later.
