#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Prototype .qet <-> .qetz converter (Joshua's roadmap, zipped project file).

Splits a .qet into the roadmap's zipped layout, with the project database
holding the engineering data and the folio files holding only graphics,
then joins it back. The point is to prove, on real files and before any
C++, that nothing is lost on the way through, and to measure what lands
where.

    qetcontainer.py split FILE.qet OUT.qetz
    qetcontainer.py join  IN.qetz  OUT.qet
    qetcontainer.py check FILE.qet...   split + join + compare, one line each

Container layout (format 1, draft):

    manifest.xml          format, min-reader, root attributes, top-level order
    project.sqlite        engineering data (schema below)
    folios/<id>.xml       one <diagram> each, data removed, graphics kept
    elements/             embedded symbols as real .elmt files
    elements/collection.xml   category tree and order, definitions by file
    titleblocks/<n>.titleblock
    images/<folio>-<n>.<ext>  pictures as real files, no base64
    conf/newdiagrams.xml  defaults for new folios
    other/<n>.xml         top-level content this converter does not model

"What goes where" (draft rule): in a list -> database; only says where ink
goes -> folio file; anything not understood stays where it was, verbatim.
Computed values QElectroTech also saves (element1_label, ...) stay in the
folio file: they are not facts.

Rows are keyed by uuid where the file has a unique one; otherwise by a
synthetic key, counted as an identity repair QElectroTech would have to do
on import (duplicate uuids from old copy-paste, GitHub #1408).
"""
import base64
import io
import json
import sqlite3
import sys
import tempfile
import xml.etree.ElementTree as ET
from xml.parsers import expat
import zipfile
from pathlib import Path

FORMAT = "1"
MIN_READER = "1"
KEY = "qc-key"          # links a folio-file item to its database row
FILE = "qc-file"        # a subtree or picture moved to its own file

FOLIO_DATA = ["title", "author", "date", "folio", "indexrev", "filename",
              "locmach", "plant", "auto_page_num"]
ELEMENT_DATA = ["uuid", "type", "prefix", "freezeLabel"]
CONDUCTOR_DATA = ["uuid", "element1", "terminal1", "element2", "terminal2",
                  "num", "formula", "function", "tension_protocol",
                  "conductor_color", "conductor_section", "cable", "bus",
                  "freezeLabel"]
STRIP_DATA = ["installation", "location", "name", "comment", "description"]

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE project_property (
    ord INTEGER PRIMARY KEY, name TEXT, value TEXT, attrs TEXT);
CREATE TABLE folio (
    id TEXT PRIMARY KEY, pos INTEGER NOT NULL UNIQUE, file TEXT NOT NULL,
    %s, props_at INTEGER, props_attrs TEXT);
CREATE TABLE folio_property (
    folio_id TEXT NOT NULL REFERENCES folio ON DELETE CASCADE,
    ord INTEGER NOT NULL, name TEXT, value TEXT, attrs TEXT,
    PRIMARY KEY (folio_id, ord));
CREATE TABLE element (
    key TEXT PRIMARY KEY,
    folio_id TEXT NOT NULL REFERENCES folio ON DELETE CASCADE,
    %s, info_at INTEGER, info_attrs TEXT, links_at INTEGER, links_attrs TEXT);
CREATE TABLE element_info (
    element_key TEXT NOT NULL REFERENCES element ON DELETE CASCADE,
    ord INTEGER NOT NULL, name TEXT, value TEXT, attrs TEXT,
    PRIMARY KEY (element_key, ord));
CREATE TABLE link (
    element_key TEXT NOT NULL REFERENCES element ON DELETE CASCADE,
    ord INTEGER NOT NULL, linked_uuid TEXT, attrs TEXT,
    PRIMARY KEY (element_key, ord));
CREATE TABLE conductor (
    key TEXT PRIMARY KEY,
    folio_id TEXT NOT NULL REFERENCES folio ON DELETE CASCADE, %s);
CREATE TABLE terminal_strip (
    uuid TEXT PRIMARY KEY, ord INTEGER NOT NULL UNIQUE,
    %s);
CREATE TABLE strip_terminal (
    strip_uuid TEXT NOT NULL REFERENCES terminal_strip ON DELETE CASCADE,
    pos INTEGER NOT NULL, level INTEGER NOT NULL, element_uuid TEXT,
    PRIMARY KEY (strip_uuid, pos, level));
CREATE TABLE strip_bridge (
    uuid TEXT PRIMARY KEY,
    strip_uuid TEXT NOT NULL REFERENCES terminal_strip ON DELETE CASCADE,
    ord INTEGER NOT NULL, color TEXT);
CREATE TABLE strip_bridge_terminal (
    bridge_uuid TEXT NOT NULL REFERENCES strip_bridge ON DELETE CASCADE,
    ord INTEGER NOT NULL, element_uuid TEXT,
    PRIMARY KEY (bridge_uuid, ord));
""" % tuple(", ".join(f'"{c}" TEXT' for c in cols)
            for cols in (FOLIO_DATA, ELEMENT_DATA, CONDUCTOR_DATA, STRIP_DATA))


# --- helpers -----------------------------------------------------------------

def _take(node, names):
    """Remove the named attributes from node; return them as a list of
    values, None where absent (absent and empty are different things)."""
    out = []
    for n in names:
        out.append(node.attrib.pop(n, None))
    return out


def _put(node, names, values):
    for n, v in zip(names, values):
        if v is not None:
            node.set(n, v)


def _attrs(node, skip=()):
    a = {k: v for k, v in node.attrib.items() if k not in skip}
    return json.dumps(a, ensure_ascii=False) if a else None


_CR = "\ue00d"      # stand-in: ElementTree writes a CR in text raw, and a
                     # parser reads it back as LF; the files carry &#13;


def _xml(node, **kw):
    changed = []
    for n in node.iter():
        if n.text and "\r" in n.text:
            changed.append((n, "text", n.text))
            n.text = n.text.replace("\r", _CR)
        if n.tail and "\r" in n.tail:
            changed.append((n, "tail", n.tail))
            n.tail = n.tail.replace("\r", _CR)
    data = ET.tostring(node, encoding="utf-8", **kw).replace(
        _CR.encode(), b"&#13;")
    for n, field, value in changed:      # leave the tree as it was
        setattr(n, field, value)
    return data


def _safe(s):
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s) or "_"


def _keyer(nodes, prefix, stats, stat_name):
    """uuid when present and unique, else a synthetic key (counted)."""
    seen = {}
    for n in nodes:
        u = n.get("uuid")
        if u:
            seen[u] = seen.get(u, 0) + 1
    keys, i = [], 0
    for n in nodes:
        u = n.get("uuid")
        if u and seen[u] == 1:
            keys.append(u)
        else:
            i += 1
            keys.append(f"{prefix}{i}")
            stats[stat_name] += 1
    return keys


# --- split -------------------------------------------------------------------

def parse(data):
    """Parse XML the way QElectroTech reads it: namespace prefixes and xmlns
    declarations are kept as literal names and attributes, where they were.
    (ElementTree's own parser resolves namespaces and then writes the
    declarations somewhere else, which QElectroTech reads as a different
    document: it dropped every title block with an SVG logo.)"""
    if isinstance(data, (str, Path)):
        data = Path(data).read_bytes()
    # A raw carriage return: QElectroTech keeps none (CR LF reads as LF, a
    # lone CR is dropped, in text and attributes alike), where a parser
    # following the XML rules reads a lone CR as LF -- "X\r\r\nY" gave two
    # line breaks instead of QElectroTech's one (forum attachment 1328).
    # Measured on master 13dbacef1. A written-out &#13; is not raw and stays.
    data = data.replace(b"\r", b"")
    p = expat.ParserCreate()
    p.buffer_text = True
    stack, root = [], None

    def start(tag, attrs):
        nonlocal root
        e = ET.Element(tag, attrs)
        if stack:
            stack[-1].append(e)
        else:
            root = e
        stack.append(e)

    def end(tag):
        stack.pop()

    def chars(text):
        cur = stack[-1]
        if len(cur):
            cur[-1].tail = (cur[-1].tail or "") + text
        else:
            cur.text = (cur.text or "") + text

    def leaf(e):
        if stack:
            stack[-1].append(e)

    p.StartElementHandler, p.EndElementHandler = start, end
    p.CharacterDataHandler = chars
    p.CommentHandler = lambda text: leaf(ET.Comment(text))
    p.ProcessingInstructionHandler = lambda t, d: leaf(ET.ProcessingInstruction(t, d))
    p.Parse(data, True)
    return root


def split(qet_path, out_path):
    root = parse(qet_path)
    if root.tag != "project":
        raise ValueError(f"{qet_path}: root is <{root.tag}>, not <project>")
    stats = dict.fromkeys(
        ["folios", "elements", "element_infos", "links", "conductors",
         "images", "symbols", "folio_without_uuid", "element_key_repair",
         "conductor_key_repair", "other_toplevel", "terminal_strips",
         "strip_terminals"], 0)

    with tempfile.TemporaryDirectory() as tmp:
        dbfile = Path(tmp) / "project.sqlite"
        db = sqlite3.connect(dbfile)
        db.executescript(SCHEMA)
        db.execute("INSERT INTO meta VALUES ('schema', ?)", (FORMAT,))
        files = {}
        manifest = ET.Element("qet-container",
                              {"format": FORMAT, "min-reader": MIN_READER})
        ET.SubElement(manifest, "project", dict(root.attrib))
        order = ET.SubElement(manifest, "order")

        all_diagrams = [c for c in root if c.tag == "diagram"]
        all_elements = [e for d in all_diagrams
                        for e in (d.find("elements") if d.find("elements") is not None else [])
                        if e.tag == "element"]
        all_conductors = [c for d in all_diagrams
                          for c in (d.find("conductors") if d.find("conductors") is not None else [])
                          if c.tag == "conductor"]
        ekeys = dict(zip(map(id, all_elements),
                         _keyer(all_elements, "e", stats, "element_key_repair")))
        ckeys = dict(zip(map(id, all_conductors),
                         _keyer(all_conductors, "c", stats, "conductor_key_repair")))

        pos = 0
        for n, child in enumerate(list(root)):
            entry = ET.SubElement(order, child.tag)
            if child.tag == "properties":
                entry.set("attrs", _attrs(child) or "")
                for i, p in enumerate(child):
                    db.execute("INSERT INTO project_property VALUES (?,?,?,?)",
                               (i, p.get("name"), p.text,
                                json.dumps({"tag": p.tag, **{k: v for k, v in p.attrib.items() if k != "name"}},
                                           ensure_ascii=False)))
            elif child.tag == "newdiagrams":
                files["conf/newdiagrams.xml"] = _xml(child)
            elif child.tag == "titleblocktemplates":
                entry.set("attrs", _attrs(child) or "")
                for i, t in enumerate(child):
                    name = f"titleblocks/{i:03d}-{_safe(t.get('name', 'unnamed'))}.titleblock"
                    files[name] = _xml(t)
                    ET.SubElement(entry, "file", {"path": name})
            elif child.tag == "collection":
                _split_collection(child, files, stats)
                files["elements/collection.xml"] = _xml(child)
            elif child.tag == "terminal_strips" and _split_strips(child, db, stats):
                pass                     # rebuilt from the database
            elif child.tag == "diagram":
                pos += 1
                fid = child.get("uuid")
                if not fid:
                    stats["folio_without_uuid"] += 1
                    fid = f"f{pos}"
                fname = f"folios/{_safe(fid.strip('{}'))}.xml"
                entry.set("id", fid)
                _split_diagram(child, fid, pos, fname, db, files, stats,
                               ekeys, ckeys)
                files[fname] = _xml(child)
            else:
                name = f"other/{n:03d}-{_safe(child.tag)}.xml"
                files[name] = _xml(child)
                entry.set("file", name)
                stats["other_toplevel"] += 1

        problems = db.execute("PRAGMA foreign_key_check").fetchall()
        if problems:
            raise RuntimeError(f"foreign key check failed: {problems[:5]}")
        db.commit()
        db.close()
        files["project.sqlite"] = dbfile.read_bytes()
        files["manifest.xml"] = _xml(manifest)

        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.xml", files.pop("manifest.xml"))
            for name in sorted(files):
                data = files[name]
                stored = name.startswith("images/")   # already compressed
                z.writestr(zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)), data,
                           zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
    return stats


def _split_diagram(d, fid, pos, fname, db, files, stats, ekeys, ckeys):
    stats["folios"] += 1
    vals = _take(d, FOLIO_DATA)
    db.execute(f"INSERT INTO folio VALUES (?,?,?,{','.join('?' * len(FOLIO_DATA))},NULL,NULL)",
               (fid, pos, fname, *vals))
    for i, c in enumerate(list(d)):
        if c.tag == "properties":
            db.execute("UPDATE folio SET props_at = ?, props_attrs = ? WHERE id = ?",
                       (i, _attrs(c), fid))
            for j, p in enumerate(c):
                db.execute("INSERT INTO folio_property VALUES (?,?,?,?,?)",
                           (fid, j, p.get("name"), p.text,
                            json.dumps({"tag": p.tag, **{k: v for k, v in p.attrib.items() if k != "name"}},
                                       ensure_ascii=False)))
            d.remove(c)
            break

    elements = d.find("elements")
    for e in (elements if elements is not None else []):
        if e.tag != "element":
            continue
        stats["elements"] += 1
        key = ekeys[id(e)]
        vals = _take(e, ELEMENT_DATA)
        info_at = info_attrs = links_at = links_attrs = None
        for i, c in enumerate(list(e)):
            if c.tag == "elementInformations" and info_at is None:
                info_at, info_attrs = i, _attrs(c)
            elif c.tag == "links_uuids" and links_at is None:
                links_at, links_attrs = i, _attrs(c)
        db.execute(f"INSERT INTO element VALUES (?,?,{','.join('?' * len(ELEMENT_DATA))},?,?,?,?)",
                   (key, fid, *vals, info_at, info_attrs, links_at, links_attrs))
        for c in list(e):
            if c.tag == "elementInformations" and info_at is not None and c is e[info_at]:
                for j, inf in enumerate(c):
                    stats["element_infos"] += 1
                    db.execute("INSERT INTO element_info VALUES (?,?,?,?,?)",
                               (key, j, inf.get("name"), inf.text,
                                json.dumps({"tag": inf.tag, **{k: v for k, v in inf.attrib.items() if k != "name"}},
                                           ensure_ascii=False)))
            elif c.tag == "links_uuids" and links_at is not None and c is e[links_at]:
                for j, ln in enumerate(c):
                    stats["links"] += 1
                    db.execute("INSERT INTO link VALUES (?,?,?,?)",
                               (key, j, ln.get("uuid"),
                                json.dumps({"tag": ln.tag, **{k: v for k, v in ln.attrib.items() if k != "uuid"}},
                                           ensure_ascii=False)))
        # remove after reading, highest index first so positions stay valid
        for at in sorted(x for x in (info_at, links_at) if x is not None)[::-1]:
            e.remove(e[at])
        e.set(KEY, key)

    conductors = d.find("conductors")
    for c in (conductors if conductors is not None else []):
        if c.tag != "conductor":
            continue
        stats["conductors"] += 1
        key = ckeys[id(c)]
        vals = _take(c, CONDUCTOR_DATA)
        db.execute(f"INSERT INTO conductor VALUES (?,?,{','.join('?' * len(CONDUCTOR_DATA))})",
                   (key, fid, *vals))
        c.set(KEY, key)

    images = d.find("images")
    for i, im in enumerate(images if images is not None else []):
        text = im.text or ""
        b64 = text.strip()
        try:
            raw = base64.b64decode(b64, validate=True)
        except ValueError:
            continue
        if not raw or base64.b64encode(raw).decode() != b64:
            continue            # not a canonical encoding: leave it inline
        ext = ("png" if raw[:4] == b"\x89PNG" else
               "jpg" if raw[:2] == b"\xff\xd8" else
               "svg" if b"<svg" in raw[:512] else "bin")
        name = f"images/{_safe(fid.strip('{}'))}-{i:03d}.{ext}"
        files[name] = raw
        im.text = None
        im.set(FILE, name)
        lead, trail = text[:len(text) - len(text.lstrip())], text[len(text.rstrip()):]
        if lead or trail:
            im.set("qc-ws", json.dumps([lead, trail]))
        stats["images"] += 1


def _split_strips(node, db, stats):
    """Terminal strips into the database. Only when rebuilding them from
    the rows gives back exactly this XML: anything else (an attribute or
    child QElectroTech does not write, a strip without a uuid) leaves the
    whole block as a verbatim file, counted as other_toplevel."""
    strips, terms, bridges, bterms = [], [], [], []
    try:
        if node.attrib or node.text and node.text.strip():
            return False
        for i, st in enumerate(node):
            data = st.find("terminal_strip_data")
            suuid = data.get("uuid")
            if not suuid:
                return False
            info = {x.get("name"): x.text or "" for x in data.iter("information")}
            strips.append((suuid, i, *[info.get(c) for c in STRIP_DATA]))
            for p, phy in enumerate(st.find("layout")):
                for lv, rt in enumerate(phy):
                    terms.append((suuid, p, lv, rt.get("element_uuid")))
            for b, br in enumerate(st.findall("terminal_strip_bridge")):
                buuid = br.get("uuid")
                if not buuid:
                    return False
                bridges.append((buuid, suuid, b, br.get("color")))
                bterms += [(buuid, k, rt.get("uuid"))
                           for k, rt in enumerate(br.find("real_terminals"))]
    except (AttributeError, TypeError):
        return False
    rebuilt = _strips_xml(strips, terms, bridges, bterms)
    if first_difference(node, rebuilt) is not None:
        return False
    if (len({r[0] for r in strips}) != len(strips)
            or len({r[0] for r in bridges}) != len(bridges)):
        return False
    db.executemany("INSERT INTO terminal_strip VALUES (%s)" % ",".join("?" * (2 + len(STRIP_DATA))), strips)
    db.executemany("INSERT INTO strip_terminal VALUES (?,?,?,?)", terms)
    db.executemany("INSERT INTO strip_bridge VALUES (?,?,?,?)", bridges)
    db.executemany("INSERT INTO strip_bridge_terminal VALUES (?,?,?)", bterms)
    stats["terminal_strips"] += len(strips)
    stats["strip_terminals"] += len(terms)
    return True


def _strips_xml(strips, terms, bridges, bterms):
    """<terminal_strips> as QElectroTech writes it (TerminalStrip::toXml)."""
    root = ET.Element("terminal_strips")
    for suuid, _ord, *info in sorted(strips, key=lambda r: r[1]):
        st = ET.SubElement(root, "terminal_strip")
        data = ET.SubElement(st, "terminal_strip_data", {"uuid": suuid})
        infos = ET.SubElement(data, "informations")
        for name, value in zip(STRIP_DATA, info):
            if value is not None:
                ET.SubElement(infos, "information", {"name": name}).text = value
        layout = ET.SubElement(st, "layout")
        phys = {}
        for s_uuid, p, lv, euuid in sorted(terms, key=lambda r: (r[1], r[2])):
            if s_uuid != suuid:
                continue
            if p not in phys:
                phys[p] = ET.SubElement(layout, "physical_terminal")
            rt = ET.SubElement(phys[p], "real_terminal")
            if euuid is not None:
                rt.set("element_uuid", euuid)
        for buuid, s_uuid, _b, color in sorted(bridges, key=lambda r: r[2]):
            if s_uuid != suuid:
                continue
            br = ET.SubElement(st, "terminal_strip_bridge", {"uuid": buuid})
            if color is not None:
                br.set("color", color)
            rts = ET.SubElement(br, "real_terminals")
            for b_uuid, _k, euuid in sorted(bterms, key=lambda r: r[1]):
                if b_uuid == buuid:
                    rt = ET.SubElement(rts, "real_terminal")
                    if euuid is not None:
                        rt.set("uuid", euuid)
    return root


def _join_strips(db):
    q = lambda sql: db.execute(sql).fetchall()
    return _strips_xml(q("SELECT * FROM terminal_strip"),
                       q("SELECT * FROM strip_terminal"),
                       q("SELECT * FROM strip_bridge"),
                       q("SELECT * FROM strip_bridge_terminal"))


def _split_collection(node, files, stats, path=("elements",)):
    for c in node:
        if c.tag == "category":
            _split_collection(c, files, stats, path + (_safe(c.get("name", "_")),))
        elif c.tag == "element" and len(c) == 1 and c[0].tag == "definition":
            name = "/".join(path + (_safe(c.get("name", "unnamed")),))
            while name in files:
                name += "_"
            files[name] = _xml(c[0])
            c.remove(c[0])
            c.set(FILE, name)
            stats["symbols"] += 1


# --- join --------------------------------------------------------------------

def join(in_path, out_path=None):
    with zipfile.ZipFile(in_path) as z:
        files = {n: z.read(n) for n in z.namelist()}
    manifest = parse(files["manifest.xml"])
    if int(manifest.get("min-reader", "1")) > int(FORMAT):
        raise RuntimeError(f"{in_path} needs a newer reader (min-reader "
                           f"{manifest.get('min-reader')}, this is {FORMAT})")
    with tempfile.TemporaryDirectory() as tmp:
        dbfile = Path(tmp) / "project.sqlite"
        dbfile.write_bytes(files["project.sqlite"])
        db = sqlite3.connect(dbfile)
        root = ET.Element("project", dict(manifest.find("project").attrib))
        for entry in manifest.find("order"):
            tag = entry.tag
            if tag == "properties":
                node = ET.SubElement(root, "properties", json.loads(entry.get("attrs") or "{}"))
                for name, value, attrs in db.execute(
                        "SELECT name, value, attrs FROM project_property ORDER BY ord"):
                    node.append(_rebuild(name, value, attrs, "name"))
            elif tag == "newdiagrams":
                root.append(parse(files["conf/newdiagrams.xml"]))
            elif tag == "titleblocktemplates":
                node = ET.SubElement(root, tag, json.loads(entry.get("attrs") or "{}"))
                for f in entry:
                    node.append(parse(files[f.get("path")]))
            elif tag == "collection":
                col = parse(files["elements/collection.xml"])
                for e in col.iter("element"):
                    if e.get(FILE):
                        e.append(parse(files[e.attrib.pop(FILE)]))
                root.append(col)
            elif tag == "terminal_strips" and not entry.get("file"):
                root.append(_join_strips(db))
            elif tag == "diagram":
                root.append(_join_diagram(entry.get("id"), db, files))
            else:
                root.append(parse(files[entry.get("file")]))
        db.close()
    data = _xml(root, xml_declaration=True)
    if out_path:
        Path(out_path).write_bytes(data)
    return root


def _rebuild(name, value, attrs, name_attr):
    a = json.loads(attrs)
    node = ET.Element(a.pop("tag"))
    if name is not None:
        node.set(name_attr, name)
    for k, v in a.items():
        node.set(k, v)
    node.text = value
    return node


def _insert_at(parent, at, child):
    parent.insert(min(at, len(parent)), child)


def _join_diagram(fid, db, files):
    row = db.execute(f"SELECT file, {', '.join(f'\"{c}\"' for c in FOLIO_DATA)}, "
                     "props_at, props_attrs FROM folio WHERE id = ?", (fid,)).fetchone()
    d = parse(files[row[0]])
    _put(d, FOLIO_DATA, row[1:1 + len(FOLIO_DATA)])
    props_at, props_attrs = row[-2:]
    if props_at is not None:
        p = ET.Element("properties", json.loads(props_attrs or "{}"))
        for name, value, attrs in db.execute(
                "SELECT name, value, attrs FROM folio_property WHERE folio_id = ? ORDER BY ord", (fid,)):
            p.append(_rebuild(name, value, attrs, "name"))
        _insert_at(d, props_at, p)

    elements = d.find("elements")
    for e in (elements if elements is not None else []):
        key = e.attrib.pop(KEY, None)
        if key is None:
            continue
        r = db.execute(f"SELECT {', '.join(f'\"{c}\"' for c in ELEMENT_DATA)}, "
                       "info_at, info_attrs, links_at, links_attrs FROM element WHERE key = ?",
                       (key,)).fetchone()
        _put(e, ELEMENT_DATA, r[:len(ELEMENT_DATA)])
        info_at, info_attrs, links_at, links_attrs = r[len(ELEMENT_DATA):]
        moved = []
        if info_at is not None:
            w = ET.Element("elementInformations", json.loads(info_attrs or "{}"))
            for name, value, attrs in db.execute(
                    "SELECT name, value, attrs FROM element_info WHERE element_key = ? ORDER BY ord", (key,)):
                w.append(_rebuild(name, value, attrs, "name"))
            moved.append((info_at, w))
        if links_at is not None:
            w = ET.Element("links_uuids", json.loads(links_attrs or "{}"))
            for uuid, attrs in db.execute(
                    "SELECT linked_uuid, attrs FROM link WHERE element_key = ? ORDER BY ord", (key,)):
                w.append(_rebuild(uuid, None, attrs, "uuid"))
            moved.append((links_at, w))
        for at, w in sorted(moved, key=lambda m: m[0]):
            _insert_at(e, at, w)

    conductors = d.find("conductors")
    for c in (conductors if conductors is not None else []):
        key = c.attrib.pop(KEY, None)
        if key is None:
            continue
        r = db.execute(f"SELECT {', '.join(f'\"{x}\"' for x in CONDUCTOR_DATA)} "
                       "FROM conductor WHERE key = ?", (key,)).fetchone()
        _put(c, CONDUCTOR_DATA, r)

    for im in d.iter("image"):
        name = im.attrib.pop(FILE, None)
        if name:
            lead, trail = json.loads(im.attrib.pop("qc-ws", '["", ""]'))
            im.text = lead + base64.b64encode(files[name]).decode() + trail
    return d


# --- compare -----------------------------------------------------------------

def first_difference(a, b, path=""):
    """Exact infoset comparison: tag, attributes, text, child order.
    Whitespace-only text and tails count as empty (indentation)."""
    here = f"{path}/{a.tag}"
    if a.tag != b.tag:
        return f"{here}: tag {a.tag!r} vs {b.tag!r}"
    if a.attrib != b.attrib:
        ka, kb = set(a.attrib), set(b.attrib)
        diff = sorted((ka ^ kb) | {k for k in ka & kb if a.attrib[k] != b.attrib[k]})
        return f"{here}: attributes differ: {diff[:5]}"
    norm = lambda s: s if s and s.strip() else ""
    if norm(a.text) != norm(b.text):
        return f"{here}: text differs"
    if len(a) != len(b):
        return f"{here}: {len(a)} vs {len(b)} children"
    for i, (ca, cb) in enumerate(zip(a, b)):
        if norm(ca.tail) != norm(cb.tail):
            return f"{here}[{i}]: tail differs"
        d = first_difference(ca, cb, f"{here}[{i}]")
        if d:
            return d
    return None


def check(path):
    with tempfile.TemporaryDirectory() as tmp:
        zpath = Path(tmp) / "out.qetz"
        stats = split(path, zpath)
        back = join(zpath)
        orig = parse(path)
        diff = first_difference(orig, back)
        with zipfile.ZipFile(zpath) as z:
            sizes = {"db": z.getinfo("project.sqlite").file_size,
                     "folios": sum(i.file_size for i in z.infolist() if i.filename.startswith("folios/")),
                     "zip": zpath.stat().st_size}
    return stats, sizes, diff


def main(argv):
    if len(argv) >= 3 and argv[0] == "split":
        print(json.dumps(split(argv[1], argv[2])))
    elif len(argv) == 3 and argv[0] == "join":
        join(argv[1], argv[2])
    elif len(argv) >= 2 and argv[0] == "check":
        failed = 0
        print(f"{'file':32} {'qet':>9} {'zip':>9} {'folios':>6} {'elmts':>6} "
              f"{'infos':>6} {'wires':>6} {'links':>5} {'imgs':>4} {'syms':>4} "
              f"{'repair':>6}  result")
        for p in argv[1:]:
            try:
                s, z, diff = check(p)
            except Exception as ex:          # report and keep going
                failed += 1
                print(f"{Path(p).name[:32]:32} ERROR {type(ex).__name__}: {ex}")
                continue
            failed += diff is not None
            repair = s["element_key_repair"] + s["conductor_key_repair"]
            print(f"{Path(p).name[:32]:32} {Path(p).stat().st_size:>9} {z['zip']:>9} "
                  f"{s['folios']:>6} {s['elements']:>6} {s['element_infos']:>6} "
                  f"{s['conductors']:>6} {s['links']:>5} {s['images']:>4} {s['symbols']:>4} "
                  f"{repair:>6}  {'LOSSLESS' if diff is None else 'DIFF ' + diff}")
        print(f"\n{len(argv) - 1 - failed} of {len(argv) - 1} lossless")
        return 1 if failed else 0
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
