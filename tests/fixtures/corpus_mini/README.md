# `corpus_mini` — one tiny document per format

Four fixture documents, one per parsing path of spec §6.2, plus the PDF's Markdown source. They exist
so the parser, chunker and index tests never load the fourteen real policy documents (spec §16.5):
a test that needs the real corpus reads `corpus/` and the committed manifest instead.

| File | Path exercised |
|---|---|
| `mini-md.md` | ATX headings; one leaf deliberately longer than `CHUNK_MAX_CHARS`, so the windowing branch and its overlap are reachable |
| `mini-html.html` | `beautifulsoup4` → `markdownify` → the Markdown path, including a table that must survive as pipe-delimited text |
| `mini-txt.txt` | `=` underline / `-` underline / CAPITALS heading convention |
| `mini-pdf.pdf` (+ `mini-pdf.src.md`) | `pypdf` extraction, the running footer that must be dropped, and heading recovery against the source's heading set |

Every document follows the corpus conventions of `corpus/README.md`: a title, a `Document ID: … ·
Owner: … · Effective … · Version …` line, a `Topics:` line, and a heading path that excludes the title.
Nothing in them is a real policy.

`mini-pdf.pdf` is generated, once, by the same renderer as the corpus PDF:

```bash
python scripts/build_pdf.py --source tests/fixtures/corpus_mini/mini-pdf.src.md \
                            --target tests/fixtures/corpus_mini/mini-pdf.pdf
```

The creation date is pinned, so re-running that command on an unchanged source rewrites the same bytes.
