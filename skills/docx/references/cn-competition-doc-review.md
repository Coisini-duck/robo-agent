# Reviewing a Chinese competition document (作品说明书)

Templates for 工创赛 / 大创 / 挑战杯 / 学科竞赛 ship as a `.docx` where every
section carries a blue instruction line (`（xxxx，字数不超过500字，5幅图之内）`,
`（宋体，五号，行距为固定值20磅…）`). Those lines are **deleted before submission**,
so both the character count and the score depend on what you strip.

## Procedure

1. **Extract paragraphs without python-docx if it is missing.** `pip install
   python-docx` fails on some hosts (PEP 668); the zip route works and is enough
   for review:
   ```python
   import re, zipfile
   xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8", "ignore")
   paras = []
   for m in re.finditer(r"<w:p[ >].*?</w:p>", xml, re.S):
       txt = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", m.group(0), re.S))
       txt = re.sub(r"<[^>]+>", "", txt).strip()
       if txt:
           paras.append(txt)
   ```
   (Read-only review only. To *edit*, use `scripts/docx_edit.py` or
   `references/xml-roundtrip-form-filling.md`.)
2. **Split by the section headings** (`一、` `二、` …), not by Word heading styles —
   these templates rarely use real heading levels.
3. **Strip the instruction paragraphs before counting**, or every number is wrong.
   A paragraph is template boilerplate when it starts with `（` and contains any of
   `字数不超过` / `宋体` / `注意任何` / `供参考`.
4. **Count `len(re.sub(r"\s", "", text))`** per section and compare with the cap
   stated in that section. Report `上限 / 实际 / 余量` — the margin is what tells the
   user where writing effort should go (surplus = a section that is suspiciously
   thin and is probably losing marks; negative = must cut).
5. **Then run the four structural checks** (below).

## The four structural checks

| Check | How | Why it costs marks |
|---|---|---|
| Anonymity | grep for school / team / student names | Template states a violation scores **0** and triggers an on-site audit |
| Placeholders | search `**`, `待补`, `xx`, `TBD` | An unfilled `凸轮迭代了**版` reads as an unfinished submission |
| Cross-section number consistency | count occurrences of each headline number (track length, waypoint count, cycle time) across all sections | The same quantity stated as `13.1 m` in one section and `13.4 m` in another is the first thing a reviewer notices; each section can be internally self-consistent |
| Figure numbering | list every `图N` | Sections each restart at `图1`, so the same number recurs; decide per-section vs continuous from the template and make it uniform |

Required-content check: the template says what each section must *record* (e.g.
“重点对制作、调试过程中遇到的各项问题及针对性解决方案进行记录”). Map the actual
paragraphs onto those required items and name the gaps explicitly.

## Drafting rules when the user owns only part of the document

- **Never invent numbers, dates, or events** to fill a gap. Draft only from facts
  already present in the document; for anything else, ask one pointed question
  (e.g. “凸轮一共迭代了几版，每版的什么问题”).
- Keep every draft inside the section's cap and say the count.
- Quote the exact placeholder line you are replacing, so the user can find it.

## Reporting shape

Lead with a table of `上限 / 实际 / 余量` per section, then a short ordered list of
hard defects (over-limit, placeholder, contradictory numbers, retained instruction
lines) each with the evidence, then the drafts, then the list of facts you need
from the user. The user writes these documents for teammates — flag that a
rewrite needs their confirmation, and offer the specific edit list instead of
silently rewriting their file.
