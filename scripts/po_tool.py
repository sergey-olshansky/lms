#!/usr/bin/env python3
"""PO toolkit for LMS ru.po (task 8).

Pure-python PO parser/writer/patcher. The ru.po file is fully regular:
every non-comment line matches ^(msgid|msgstr) "..."$ or is a "..." continuation,
no msgctxt and no msgid_plural entries exist.

Usage (module): see functions. CLI:
  stats                     print entry statistics vs main.pot
  show <substr>             show entries whose msgid contains substr
  export-empty <out.json>   export entries with empty msgstr (POT keys + extra)
  apply <patch.json>        apply [{op: set|remove|append, id, str?, refs?, comments?}]
"""
import json
import re
import sys
from collections import OrderedDict

PO_PATH = "lms/locale/ru.po"
POT_PATH = "lms/locale/main.pot"

LINE_RE = re.compile(r'^(msgctxt|msgid_plural|msgid|msgstr(?:\[(\d+)\])?)\s+"(.*)"$')
CONT_RE = re.compile(r'^"(.*)"$')


def unquote(s):
    # s is the PO string content between the outer quotes (still escaped)
    return json.loads('"' + s + '"')


def quote(s):
    return json.dumps(s, ensure_ascii=False)


class Entry:
    __slots__ = ("comments", "refs", "id", "str", "line")

    def __init__(self, line=0):
        self.comments = []  # #. lines
        self.refs = []      # #: lines
        self.id = ""
        self.str = ""
        self.line = line

    def to_lines(self):
        out = []
        for c in self.comments:
            out.append(c)
        if self.refs:
            out.append("#: " + " ".join(self.refs))
        out.append("msgid " + quote(self.id))
        out.append("msgstr " + quote(self.str))
        return out


def parse_po(path=PO_PATH):
    entries = []
    header_lines = []
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    cur = None
    field = None  # 'id' | 'str'
    pending_comments = []
    for i, raw in enumerate(lines, 1):
        line = raw.rstrip("\r")
        if not line.strip():
            continue
        if line.startswith("#"):
            if line.startswith("#:") or line.startswith("#."):
                pending_comments.append(line)
            else:
                pending_comments.append(line)
            continue
        m = LINE_RE.match(line)
        if m:
            name, _idx, rest = m.group(1), m.group(2), m.group(3)
            val = unquote(rest)
            if name == "msgid" and val == "":
                # header or entry with empty id
                cur = Entry(i)
                cur.id = val
                field = "id"
                if not entries and not [e for e in entries]:
                    pass
                entries.append(cur)
                cur.comments = pending_comments
                pending_comments = []
                continue
            if name == "msgid":
                cur = Entry(i)
                cur.id = val
                field = "id"
                entries.append(cur)
                cur.comments = pending_comments
                pending_comments = []
            elif name == "msgstr":
                cur.str = val
                field = "str"
            else:
                raise ValueError("unexpected keyword %r at %s:%d" % (name, path, i))
        else:
            mc = CONT_RE.match(line)
            if not mc:
                raise ValueError("unparsable line %s:%d: %r" % (path, i, line))
            val = unquote(mc.group(1))
            if field == "id":
                cur.id += val
            elif field == "str":
                cur.str += val
            else:
                raise ValueError("continuation before keyword at %s:%d" % (path, i))
    return entries


def write_po(entries, path=PO_PATH, header=None):
    with open(path, "w", encoding="utf-8") as f:
        first = True
        for e in entries:
            if not first:
                f.write("\n")
            first = False
            for ln in e.to_lines():
                f.write(ln + "\n")
    # ensure trailing newline structure kept (single \n at end already)


def pot_keys(path=POT_PATH):
    keys = OrderedDict()
    for e in parse_po(path):
        if e.id == "":
            continue
        keys.setdefault(e.id, e)
    return keys


def po_keys(entries=None):
    entries = entries if entries is not None else parse_po()
    keys = OrderedDict()
    for e in entries:
        if e.id == "":
            continue
        keys.setdefault(e.id, []).append(e)
    return keys


def stats():
    entries = parse_po()
    pot = pot_keys()
    ids = [e for e in entries if e.id != ""]
    byid = po_keys(entries)
    empty_pot = [i for i in pot if i in byid and all(not e.str for e in byid[i])]
    missing = [i for i in pot if i not in byid]
    extra = [i for i in byid if i not in pot]
    dup = [i for i, v in byid.items() if len(v) > 1]
    empty_extra = [i for i in extra if all(not e.str for e in byid[i])]
    fuzzy = 0
    with open(PO_PATH, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#,") and "fuzzy" in line:
                fuzzy += 1
    print(json.dumps({
        "po_entries": len(ids),
        "po_unique_ids": len(byid),
        "pot_msgids": len(pot),
        "missing_in_po": len(missing),
        "empty_msgstr_pot": len(empty_pot),
        "extra_not_in_pot": len(extra),
        "empty_extra": len(empty_extra),
        "duplicate_ids": len(dup),
        "fuzzy": fuzzy,
    }, indent=1, ensure_ascii=False))
    return {"missing": missing, "empty_pot": empty_pot, "extra": extra, "dup": dup}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "stats":
        stats()
    elif cmd == "show":
        sub = sys.argv[2]
        for e in parse_po():
            if sub.lower() in e.id.lower():
                print("L%d %s" % (e.line, " | ".join(e.refs)))
                print("  id : " + quote(e.id))
                print("  str: " + quote(e.str))
    elif cmd == "export-empty":
        out = {}
        for e in parse_po():
            if e.id != "" and not e.str:
                out[e.id] = {"line": e.line, "refs": e.refs}
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print("exported", len(out))
    elif cmd == "apply":
        with open(sys.argv[2], encoding="utf-8") as f:
            patch = json.load(f)
        entries = parse_po()
        byid = po_keys(entries)
        pot = pot_keys()
        n_set = n_rm = n_add = 0
        for op in patch:
            if op["op"] == "set":
                found = False
                for e in byid.get(op["id"], []):
                    e.str = op["str"]
                    found = True
                if not found:
                    raise SystemExit("set: id not found: %r" % op["id"])
                n_set += 1
            elif op["op"] == "remove":
                if op["id"] not in byid:
                    raise SystemExit("remove: id not found: %r" % op["id"])
                entries = [e for e in entries if e.id != op["id"]]
                byid = po_keys(entries)
                n_rm += 1
            elif op["op"] == "append":
                if op["id"] in byid:
                    raise SystemExit("append: id already exists: %r" % op["id"])
                e = Entry()
                e.id = op["id"]
                e.str = op["str"]
                e.refs = op.get("refs", [])
                e.comments = op.get("comments", [])
                entries.append(e)
                byid.setdefault(op["id"], []).append(e)
                n_add += 1
            else:
                raise SystemExit("bad op %r" % op)
        write_po(entries)
        print("applied: set=%d remove=%d append=%d" % (n_set, n_rm, n_add))
    else:
        raise SystemExit("unknown command %r" % cmd)


if __name__ == "__main__":
    main()
