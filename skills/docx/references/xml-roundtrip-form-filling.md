# Filling a blank .docx form without python-docx

A `.docx` is a ZIP whose body lives in `word/document.xml`, and a form is a
`<w:tbl>` of `<w:tr>` (row) / `<w:tc>` (cell). With no python-docx on the host
(PEP 668 blocks global installs, no `pip` module) this is the route that works —
use it deliberately, not as sed-on-XML.

## 1. Map the grid before writing a single character

Print the `row / cell → label` map first, and paste it into your reasoning before
filling anything. A form's visual layout does not tell you where the value cells
are: a label row can be `姓名 | (空) | 性别 | (空) | 出生年月 | (空) | 照片`, a long
field can be `label | (空)` while the next row's value cell is offset by a merged
column.

```python
import zipfile, re
xml = zipfile.ZipFile(src).read("word/document.xml").decode("utf-8")
rows = re.findall(r"<w:tr\b.*?</w:tr>", xml, re.S)
for ri, tr in enumerate(rows):
    cells = re.findall(r"<w:tc\b.*?</w:tc>", tr, re.S)
    print(ri, [celltext(tc)[:24] for tc in cells])
```

Also count paragraphs per target cell (`len(re.findall(r"<w:p\b", tc))`) — a
"可附页" cell often arrives pre-seeded with empty paragraphs, and that tells you
whether to replace the first paragraph or append after the last.

## 2. Extract cell text with the right regex

```python
re.findall(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", tc, re.S)   # correct
re.findall(r"<w:t[^>]*>(.*?)</w:t>", tc, re.S)           # WRONG
```

`<w:t[^>]*>` also matches `<w:tcPr w:w="..."/>` and every other attribute blob
starting with `w:t`. The symptom is not an exception: the cell map comes back as
garbage attributes, real labels look absent, and you fill the wrong cells.
Un-escape `&amp;` / `&lt;` / `&gt;` when reading.

## 3. Fill a cell by replacing its first paragraph, carrying `pPr`

```python
def fill(tc, lines):
    m = re.search(r"<w:p\b[^>]*>(.*?)</w:p>", tc, re.S)
    p = re.search(r"<w:pPr>.*?</w:pPr>", m.group(1), re.S)
    pPr = p.group(0) if p else ""
    newps = "".join(
        '<w:p>%s<w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % (pPr, esc(ln))
        for ln in lines)
    return tc[:m.start()] + newps + tc[m.end():]
```

- **Reuse the existing `<w:pPr>`.** It carries alignment, spacing and cell
  centring; dropping it re-flows the whole form.
- `xml:space="preserve"` is what keeps the leading spaces used to indent
  sub-bullets under a numbered item.
- Escape `&`, `<`, `>` — one bare `&` in a name produces a file Word will not open.
- One list entry per visual paragraph. Joining with `\n` inside a single `<w:t>`
  renders as one run-together line.
- Splice the modified cell back into its row, then the row back into the document,
  one row at a time (`xml = xml.replace(tr, new_tr, 1)`); never re-serialise the
  whole document from parsed objects.

## 4. Write a new file, never the original

Keep the blank template intact and write to the filename the recipient demanded
(a posting that specifies `姓名+学院+年级` naming means the delivered file must
carry exactly that, not `报名表(1).docx`).

## 5. Verify by reading it back

Re-open the output with the same extractor and assert three things, then report
them: every value you filled is present, every intended placeholder is still
`【…】`, and the byte size is plausible. The package stays valid because every
other ZIP entry was copied byte-verbatim.

Text extraction proves the *content*, not that Word will open it — so also tell
the user to open it once in Word/WPS before printing. Do not present extraction
success as rendering proof.

## Identity and screening fields are never guessed

性别 / 民族 / 政治面貌 / 是否资助对象 / 可用时间 belong in the file as
`【…待填】`, in a distinct colour if the format allows. A form is screened on
these, and a plausible guess is indistinguishable from a fact once the file
leaves your hands. Say plainly which cells you left blank and why.

A photo cell cannot be filled with text — state that the user must insert the
photo themselves rather than writing "见附件".
