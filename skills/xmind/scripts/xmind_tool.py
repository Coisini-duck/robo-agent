"""XMind read/write/verify helpers (stdlib only).

Usage:
    python xmind_tool.py dump   <file.xmind>            # sheets, field inventory, full tree
    python xmind_tool.py verify <orig.xmind> <new.xmind> # integrity + loss report

Importable helpers: load_root, save_root, walk, index, clone_with_new_ids.
"""
import json
import sys
import uuid
import copy
import zipfile
from collections import Counter

CONTENT = "content.json"


def load_root(path):
    """Return (root_topic, full_sheet_list). Raises if legacy content.xml."""
    z = zipfile.ZipFile(path)
    names = z.namelist()
    if CONTENT not in names:
        raise SystemExit(
            "%s has no content.json (legacy Xmind 8 content.xml?) entries=%s"
            % (path, names[:6])
        )
    data = json.loads(z.read(CONTENT))
    return data[0]["rootTopic"], data


def save_root(src, dst, data):
    """Copy every entry of src to dst, replacing only content.json."""
    with zipfile.ZipFile(src) as z:
        entries = [(i.filename, z.read(i.filename)) for i in z.infolist()]
    payload = json.dumps(data, ensure_ascii=False)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
        for name, blob in entries:
            zo.writestr(name, payload if name == CONTENT else blob)


def walk(topic, depth=0, out=None):
    """[(depth, title, topic_dict), ...] in document order."""
    out = [] if out is None else out
    out.append((depth, topic.get("title") or "", topic))
    for child in topic.get("children", {}).get("attached", []):
        walk(child, depth + 1, out)
    return out


def index(root, prefix=()):
    """Path tuple -> topic. NOTE: keys include the root's own title."""
    out = {}
    path = prefix + (root.get("title"),)
    out.setdefault(path, root)
    for child in root.get("children", {}).get("attached", []):
        out.update(index(child, path))
    return out


def clone_with_new_ids(topic):
    """Deep copy, assign a fresh uuid4 to every node (prevents id collisions
    when a subtree is moved or reused in a rebuilt tree)."""
    node = copy.deepcopy(topic)

    def fix(x):
        x["id"] = str(uuid.uuid4())
        for c in x.get("children", {}).get("attached", []):
            fix(c)

    fix(node)
    return node


def cmd_dump(path):
    root, data = load_root(path)
    z = zipfile.ZipFile(path)
    print("entries: %d" % len(z.namelist()))
    print("sheets: %d" % len(data))
    for s in data:
        print("  sheet %r id=%s" % (s.get("title"), s.get("id")))
    nodes = walk(root)
    fields = set()
    rich = 0
    for _, _, t in nodes:
        fields |= set(t.keys())
        if t.get("notes") or t.get("href") or t.get("labels"):
            rich += 1
    print("nodes: %d | fields: %s" % (len(nodes), sorted(fields)))
    print("nodes with notes/href/labels: %d%s"
          % (rich, "" if rich else "  (titles-only map: nothing extra to preserve)"))
    for depth, title, _ in nodes:
        print("  " * depth + repr(title)[:80])


def cmd_verify(orig, new):
    ro, _ = load_root(orig)
    rn, _ = load_root(new)
    wo, wn = walk(ro), walk(rn)
    ok = True

    print("zip ok: %s" % (zipfile.ZipFile(new).testzip() is None))
    print("entries: %d -> %d" % (
        len(zipfile.ZipFile(orig).namelist()), len(zipfile.ZipFile(new).namelist())))
    print("nodes: %d -> %d" % (len(wo), len(wn)))
    print("top branches: %d -> %d" % (
        len(ro.get("children", {}).get("attached", [])),
        len(rn.get("children", {}).get("attached", []))))

    ids = [t["id"] for _, _, t in wn]
    print("ids unique: %s (%d)" % (len(ids) == len(set(ids)), len(ids)))
    ok &= len(ids) == len(set(ids))

    def long_leaves(nodes):
        return sum(1 for _, t, _ in nodes if len(t) > 50)

    lo, ln = long_leaves(wo), long_leaves(wn)
    print("long-text leaves (>50 chars): %d -> %d" % (lo, ln))
    ok &= ln >= lo

    co = Counter(t for _, t, _ in wo)
    cn = Counter(t for _, t, _ in wn)
    missing = {t: co[t] - cn.get(t, 0) for t in co if cn.get(t, 0) < co[t]}
    if missing:
        print("\ntitles reduced/removed (%d) - confirm each is intentional:" % len(missing))
        for title, n in sorted(missing.items(), key=lambda kv: -kv[1]):
            print("  x%d  %s" % (n, title[:70]))
    else:
        print("\nno titles reduced/removed")

    dups = [(p, t) for p, t, _ in
            [(t, t, n) for _, _, n in []]]  # placeholder, real check below
    dup_found = []

    def check_dup(topic):
        kids = topic.get("children", {}).get("attached", [])
        titles = [k.get("title") for k in kids]
        for k in kids:
            if k.get("title") in (topic.get("title"),) and len(titles) == 1:
                dup_found.append((topic.get("title"), k.get("title")))
            check_dup(k)

    check_dup(rn)
    if dup_found:
        print("\nparent repeating its own title as the sole child: %s" % dup_found)
        ok = False

    print("\nRESULT: %s" % ("PASS" if ok else "REVIEW ABOVE"))
    return ok


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    cmd = sys.argv[1]
    if cmd == "dump":
        cmd_dump(sys.argv[2])
    elif cmd == "verify" and len(sys.argv) >= 4:
        cmd_verify(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit(__doc__)
