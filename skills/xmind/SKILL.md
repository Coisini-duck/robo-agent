---
name: xmind
description: "Use when editing or restructuring .xmind mindmap files."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows, macos, linux]
metadata:
  hermes:
    tags: [xmind, mindmap, zip, json, restructure]
    category: productivity
    related_skills: [docx, xlsx, powerpoint, project-plan-audit]
---

# XMind mindmaps — read, edit, restructure

`.xmind` is a **ZIP**. You edit it as JSON/XML, never by driving the GUI.

| Format | Inner file | Shape |
|---|---|---|
| Modern (Xmind 2020+/Zen/26.x) | `content.json` | **JSON array of sheets**; each `{id, title, rootTopic, ...}` |
| Legacy (Xmind 8) | `content.xml` | XML tree |

A topic is `{id, title, children: {attached: [...], detached: [...]}}` plus optional
`style`, `structureClass`, `markers`, `notes`, `href`, `labels`, `image`.
**Notes/links/labels exist only if the user added them** — count them before claiming
you preserved attachments, and don't assume a map is rich when it is titles-only.

Run `scripts/xmind_tool.py dump <file>` first; it prints the sheet list, field
inventory, and the whole tree with `repr()` titles.

## When to Use

- The user points at an `.xmind` file and asks to change, fill in, merge, dedupe,
  reorganise or "整合优化" it.
- A plan/timeline lives in a mindmap and needs to be brought in line with decisions
  made in chat (dates moved, items cancelled, new constraints).
- The user wants a **new** map (a summary of finished work, a demo explainer, a
  structure to fill by hand) — borrow one of their existing files as a style template,
  see "Creating a new map" below.
- You are about to answer "can you edit it directly?" — read this before answering:
  yes, via ZIP+JSON, with the locking caveat below.
- You need to extract a large map's contents as text to reason over.

Not for: reading a mindmap the user just wants summarised — `xmind_tool.py dump`
alone is enough, skip the rebuild sections.

## Procedure

### 1. Read the real tree — never guess a title

```python
import zipfile, json
z = zipfile.ZipFile(path)
print([i.filename for i in z.infolist()])      # content.json vs content.xml
root = json.loads(z.read("content.json"))[0]["rootTopic"]
```

Print titles with `repr()`. Real maps contain titles that look identical and are not:
trailing spaces (`'OPC-开发AI Agent '`), half-width vs full-width parens
(`打磨简历(中文+英文)` vs `打磨简历`), typos that must be corrected rather than
propagated (`专业课???`). Hard-coding a path from a rendered tree wastes a build cycle.

Build the path index **and** tolerate the root prefix:

```python
def R(*path):
    for cand in (path, (root_title,) + path):
        if cand in IDX: return deepcopy_with_new_ids(IDX[cand])
    raise KeyError(path)
```

An index built from the root includes the root's title in every key, so
`R("考研","英语")` misses while `R(("大学规划","考研","英语"))` hits.

### 2. Write by copying the ZIP and replacing one entry

```python
data = json.loads(z.read("content.json"))
sheet = dict(data[0]); sheet["rootTopic"] = new_root
data = [sheet] + data[1:]                       # keep other sheets untouched

with zipfile.ZipFile(src) as z:
    entries = [(i.filename, z.read(i.filename)) for i in z.infolist()]
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
    for fn, blob in entries:
        zo.writestr(fn, json.dumps(data, ensure_ascii=False) if fn == "content.json" else blob)
os.replace(tmp, out)
```

Every other entry (`manifest.json`, `metadata.json`, `styles.json`, `Thumbnails/`)
must be byte-identical. Preserve the sheet dict's own keys — replace only `rootTopic`.
Copy the old root and swap its `children` if the map has custom root styling.

### 3. Verify, then report numbers

`scripts/xmind_tool.py verify <orig> <new>` checks all of:

- `ZipFile(out).testzip() is None` and the entry count matches the source
- node count, top-branch count, **every id unique** (regenerate a fresh `uuid4` per
  node on rebuild so moved or reused subtrees cannot collide)
- **`Counter` diff of all titles vs the original** — prints every title whose count
  dropped, so each removal is a deliberate line you can defend
- **long-text leaves (>50 chars) count** — proves substantive prose survived, not
  just that node counts look similar
- no parent whose child repeats its own title (`简历` > `简历` is the tell of a
  half-finished merge)

Report the tally in chat. "Should be fine" is not a result; a `Counter` diff is.

## Creating a new map (template style, none of the template's content)

Editing keeps every ZIP entry byte-identical; **creating must not**. Two reasons, both
of which readers/humans will hit:

- A modern-looking file often ALSO carries legacy `content.xml`. Some read paths fall
  back to it, so a new `content.json` plus the template's `content.xml` can open as
  **the old map**.
- `manifest.json` lists `file-entries`; leaving the template's list while dropping
  `resources/` and `Thumbnails/` describes files that are not in the ZIP.

Ship exactly three entries:

| entry | content |
|---|---|
| `content.json` | `[{<template sheet fields…>, id: <new sheet id>, title, rootTopic: <new tree>}]` |
| `metadata.json` | the template's, with `activeSheetId` set to the **new** sheet id |
| `manifest.json` | `{"file-entries": {"content.json": {}, "metadata.json": {}}}` |

Drop `resources/`, `Thumbnails/thumbnail.png`, `content.xml`. Rebuild the tree with a
fresh `uuid4`-derived id per node.

**Borrow the template's look, not its content:** copy the sheet's `theme`, `style`,
`structureClass`, `extensions` (everything except `id`/`title`/`rootTopic`), and put
`class: "topic"` + the template root's `structureClass` on your new root. Child topics
need no `class`. Skipping these still parses, but the map renders in the default theme
and looks foreign next to the user's other maps.

Shape guidance for a "简介版 / one-glance" map: **30–40 nodes**, 5–8 top branches, one
fact or number per leaf, and an explicit `边界 / 没做` branch — an honest limits branch is
what makes the map survivable in an interview or defense, and the user will be asked
exactly that question.

Self-check before reporting: `testzip() is None`, namelist is exactly those three
entries, node count, ids unique, and print the top-level branch titles so the shape is
read back rather than assumed. Then also paste the **indented text outline** in chat —
XMind imports it as branches, and it is the fallback if the app rejects the file. Say
plainly that the GUI was not opened to confirm rendering.

### Give the outline alone when he asked for "文字，我自己粘"

When the ask is "给我一份…我复制粘贴进 xmind" (or he posts a screenshot of nodes and
says do it like that), **do not build a `.xmind` file**. He wants the text, and a
hand-built file is extra work he then has to open, compare and delete. Write the outline
in one fenced block, tab-indented one level per branch, and offer it as
`Ctrl+Shift+V → 粘贴为分支`.

Node style he actually uses (copy it, don't approximate):

- **one self-contained sentence per node**, 2–4 clauses joined by `｜` or `：`,
  each clause carrying a real number, filename, error string or measured value;
- **no bare labels** — `策略层` is wrong, `策略层：SmolVLA 450M，权重 865 MB，热态 0.25–0.39 s/次，显存 0.90 GB` is right;
- a `未验证项 / 边界` branch is mandatory, and it is what gets asked in an interview;
- 12–16 nodes for a single experiment write-up, 30–40 for a whole project explainer.

Also save the same text beside the doc (`<主题>_导图文字.txt`) so he can re-copy later,
and put every node's claim back against the evidence you measured — a number he cannot
defend in front of a reviewer is worse than no number.

## Never overwrite a file the app has open

If Xmind is running with that map, `os.replace` fails with
`PermissionError: [WinError 5]`. Do not retry, and do not ask the user to close it
as a precondition for making progress — write a sibling `..._v2.xmind`, verify it,
and say plainly: original untouched, here is the new file, open that one. A locked
target is a reason to branch the filename, not a blocker.

Always take a timestamped sibling copy of the source before the first write, and
name the rollback file in the reply.

**Version chains and deletion.** This workflow leaves several look-alike files
(`原文件` / `备份_<ts>` / `优化版_v1` / `优化版_v2` / `整合优化`). When the user says
"旧版删了吧", resolve the referent precisely instead of sweeping:

- delete **only** the superseded intermediate you created yourself (`_v1` when `_v2`
exists) — that needs no confirmation;
- **keep** the user's own original and the newest rollback copy until he has opened
and used the new file for a while, and say why you are keeping them;
- list the remaining files with size + mtime + what each one is, so the decision is
his. Reporting a modification time that is **newer than your own backup** is the
tell that the user saved from the app mid-flight — check it before assuming your
copy is the latest.

Deleting a locked file also fails; check writability (`open(p, "r+b")` in a
try/except) before promising a deletion.

## Restructuring a large personal map

The class of request: *"整合优化我的整份 Xmind"* on a 400–500-node life/plan map.

1. **Dump everything first.** A restructuring decided from a truncated listing will
   silently drop branches. Read all nodes, then plan.
2. **Dedupe across top branches before reorganising inside one.** Count where each
   recurring theme lives ("证书 in 4 places, 竞赛/奖项 in 3, 简历 in 2") — that count
   is the finding to report, and it is what justifies the new shape.
3. **Separate the layers**: decisions/constraints → execution timeline → domain
   branches → assets → life. A map whose timeline, achievements and skills all
   interleave cannot answer "what do I do this term".
4. **Move subtree objects, never retype them.** Deep-copy the original node so long
   prose (job history, experiment write-ups) survives verbatim.
5. **Never silently delete a cancelled item.** Collect them into a
   `❄ 已放弃` branch with **date + reason** for each. Silent deletion reads as data
   loss and destroys the record of a decision the user made deliberately.
6. **Keep the user's own names** as prefixes when you rebuild a list (their four
   target universities stay named, each annotated with what verification found),
   and mark unverified entries `待核 · …` instead of presenting them as settled.
7. **Annotate, don't orphan.** A stale leaf (`SeeedStudio`, a project name with no
   verdict) gets a child carrying the current conclusion, so the map stays useful.
8. **State the scope you touched.** If a cleanup reaches outside the branch you
   promised to leave alone, say so explicitly rather than letting the user find it.
9. **Sort a timeline branch by real calendar order, not by build order.** A winter
   break falls *between* two semesters, not after the later one; rebuilding in the
   order the source map happened to list the nodes yields a timeline that reads
   backwards while every integrity check still passes. Print the branch's children
   and read the dates in sequence before you report the rebuild.
10. **When a later chat decision contradicts the map, patch the map and prove the old
    wording is gone.** Re-open the file, rewrite the affected node, then count the
    nodes still matching the superseded phrase (`sum("<old phrase>" in t for t in
    titles)`) and report that count — it must be 0. A map still carrying the old
    city/date/deadline is worse than one that never mentioned it, because the map is
    what the user acts on.

## Pitfalls

- **Iterating the wrong object yields a plausible-but-wrong tree.** `[N(x) for x in spec]`
  where `spec` is a dict produces the dict's *keys* — you get children named after your
  own branch titles instead of the content. Always print the built subtree and read it;
  node counts and ZIP integrity both pass on a structurally wrong map.
- **Nodes meant to be children become siblings** when you build them in a flat list.
  Check that a wrapper node actually holds the items it names.
- **Grouping five route lines under one `执行路线` node** by title prefix is fragile —
  prefer building the parent with its children in one expression.
- **Do not promise "everything else is untouched" from memory.** Diff the counts, then say it.
- Adding a child to a leaf is the cheapest fix for a stale node — XMind renders it fine.

## Files

- `scripts/xmind_tool.py` — `dump` / `verify` / reusable load-save helpers.
