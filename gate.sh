#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Round-trip gate for the .qetz prototype converter
# for each .qet, QElectroTech's resave of the original must equal
# its resave of original -> container -> .qet.
#
#   gate.sh QET_BINARY FILE.qet...
#
# Normalised before comparing, because they depend on the file's path or
# bytes, not its content:
#   - the project uuid, when the original had none: QElectroTech derives it
#     from the file's raw bytes (QETProject::derivedUuid), and the rebuilt
#     file has the same content laid out differently. The C++ importer
#     derives it once, from the original, so this is not a loss. Ids
#     derived from it (autonumbering schemes) are normalised with it.
#   - the savedfilename / savedfilepath / savedfilenamedir properties.
# A file whose own resave is not repeatable is reported as UNSTABLE, not
# as a converter failure.
set -u
bin=$1; shift
here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d "${SCRATCH:-/tmp}/qetc-gate-XXXXXX")
cp "$bin" "$work/qet"                       # private binary path (qet-env)
export TMPDIR=$(mktemp -d /tmp/qet-XXXXXX)  # short private socket dir
export HOME=$work/home XDG_CONFIG_HOME=$work/home/.config \
       XDG_DATA_HOME=$work/home/.local/share QT_QPA_PLATFORM=offscreen
mkdir -p "$HOME"

norm() { sed -E '/<property name="savedfile(name|path|namedir)"/d' "$1"; }
# for an original saved without a project uuid: that uuid and the ids
# derived from it (autonumbering schemes, QETProject::derivedItemUuid):
# the rebuilt file's derived ids are mapped, in order, onto the original's,
# wherever they are copied (current_autonum_id, an element's formula_id).
normlegacy() {  # normlegacy ORIGINAL_RESAVE OTHER_RESAVE -> OTHER, mapped
    python3 - "$1" "$2" <<'PY2'
import re, sys
a, b = (open(p, encoding="utf-8", newline="").read() for p in sys.argv[1:3])
ids = lambda s: re.findall(r'<project[^>]* uuid="(\{[^}]*\})"', s)[:1] + \
                re.findall(r'<element_autonum[^>]* id="(\{[^}]*\})"', s)
for x, y in zip(ids(b), ids(a)):
    b = b.replace(x, y)
sys.stdout.buffer.write(b.encode("utf-8"))
PY2
}
resave() { rm -f "$2"; timeout 300 "$work/qet" --resave "$1" "$2" >/dev/null 2>&1; [ -s "$2" ]; }

pass=0 fail=0 unstable=0
for f in "$@"; do
    n=$(basename "$f")
    cp "$f" "$work/orig.qet"
    python3 "$here/qetcontainer.py" split "$work/orig.qet" "$work/c.qetz" >/dev/null &&
    python3 "$here/qetcontainer.py" join "$work/c.qetz" "$work/rt.qet" || { echo "ERROR    $n (converter)"; fail=$((fail+1)); continue; }
    resave "$work/orig.qet" "$work/a.qet" && resave "$work/orig.qet" "$work/a2.qet" &&
    resave "$work/rt.qet" "$work/b.qet" || { echo "ERROR    $n (QElectroTech resave)"; fail=$((fail+1)); continue; }
    if head -c 4000 "$f" | grep -q '<project[^>]* uuid='; then
        cmpb() { norm "$work/b.qet"; }
    else
        cmpb() { normlegacy "$work/a.qet" "$work/b.qet" > "$work/b.mapped"; norm "$work/b.mapped"; }
    fi
    if ! cmp -s <(norm "$work/a.qet") <(norm "$work/a2.qet"); then
        echo "UNSTABLE $n (QElectroTech's own resave differs run to run)"; unstable=$((unstable+1))
    elif cmp -s <(norm "$work/a.qet") <(cmpb); then
        echo "SAME     $n"; pass=$((pass+1))
    else
        echo "DIFF     $n: $(diff <(norm "$work/a.qet") <(cmpb) | grep -c '^<') lines"
        diff <(norm "$work/a.qet") <(cmpb) | head -4 | cut -c1-160 | sed 's/^/         /'
        fail=$((fail+1))
    fi
done
echo; echo "same $pass, different $fail, unstable $unstable  (work: $work)"
[ "$fail" -eq 0 ]
