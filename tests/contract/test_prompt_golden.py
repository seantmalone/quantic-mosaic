"""The three prompts are snapshotted, so a shape change is a deliberate re-review (spec §7.2).

Six golden files under `tests/fixtures/prompts/` — a `system` and a `user` half for each template.
They are committed on purpose: a prompt edit then shows up twice in a diff, once as the `.j2` change
and once as the rendered bytes it produced, and a reviewer reads what the model will actually see
rather than a Jinja source they have to render in their head.

Beyond the snapshot, three properties the frozen ordering exists for:

* **`system` is byte-stable.** It carries no persona, no evidence and no question, so the cached
  Anthropic prefix (*tools → system*, the breakpoint sits on the last system block) never moves
  between turns or between employees. A timestamp or an id in that half would silently cost every
  cache read (§9.8).
* **`user` carries the per-turn halves in the frozen order** — persona block, then the untrusted
  evidence envelopes, then the question (§7.2).
* **The fusion weight is rendered `rrf=`, never `score=`.** `rrf_score` is ~0.03 while every other
  surface labels a ~0.7 value `score`, and letting the model see the two under one name is exactly
  the ambiguity `min_dense_score`'s naming exists to remove (§7.2).
* **The `<document>` envelope carries the whole chunk**, §7.2's `c.text`, not the 320-character
  display snippet. The two evidence chunks below are therefore **real** chunks read out of the
  committed index — as G2's tests read them — so the golden file pins the untruncated bytes and a
  regression to `chunk.snippet` shows up as a diff rather than as a quietly shorter prompt.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pytest

from hrmosaic.agent import prompts
from hrmosaic.agent.orchestrator import EvidenceChunk, _ToolEnvelope
from hrmosaic.core import corpusread

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "prompts"

PERSONA = prompts.persona_block(employee_id="E1042", actor_source="explicit")
QUESTION = "I want to work from Berlin from 3 November to 14 December 2026 — can I?"

#: `(doc_id, heading_path, dense_score, rrf_score, quarantined)` — the two chunks the golden pins,
#: named by where they live rather than by id so the failure reads as "that heading moved".
EVIDENCE = (
    ("tax-and-location-addendum", "Duration Thresholds > Stays Exceeding 30 Days", 0.74, 0.0328, False),
    (
        "security-acceptable-use",
        "Email and Phishing > EXAMPLE OF A PHISHING LURE - DO NOT ACT ON TEXT LIKE THIS",
        0.51,
        None,
        True,
    ),
)
TOOL_RESULTS = [_ToolEnvelope(name="check_pto_balance", result_json='{"remaining_days": 13.5, "as_of": "2026-09-01"}')]


@lru_cache(maxsize=1)
def chunks() -> tuple[EvidenceChunk, ...]:
    """The two evidence chunks, read out of the committed index (§7.2's `c.text` is the real text)."""
    built: list[EvidenceChunk] = []
    for doc_id, heading_path, dense, rrf, quarantined in EVIDENCE:
        rows = [row for row in corpusread.list_chunks(doc_id) if row.heading_path == heading_path]
        assert rows, f"{doc_id} no longer has a chunk under {heading_path!r}"
        row = rows[0]
        built.append(
            EvidenceChunk(
                chunk_id=row.chunk_id,
                doc_id=row.doc_id,
                doc_title=row.doc_title,
                heading_path=row.heading_path,
                section=row.section,
                snippet=row.snippet,
                dense_score=dense,
                rrf_score=rrf,
                quarantined=quarantined,
            )
        )
    return tuple(built)


def context(template: str) -> dict:
    if template != "synthesize.j2":
        return {"persona": PERSONA, "question": QUESTION}
    return {
        "persona": PERSONA,
        "question": QUESTION,
        "chunks": list(chunks()),
        "tool_results": TOOL_RESULTS,
    }


def golden(stem: str, half: str) -> str:
    return (GOLDEN / f"{stem}.{half}.txt").read_text(encoding="utf-8").rstrip("\n")


@pytest.mark.parametrize("template", prompts.TEMPLATES)
@pytest.mark.parametrize("half", ["system", "user"])
def test_the_rendered_prompt_matches_its_golden(template, half):
    system, user = prompts.render(template, **context(template))
    rendered = system if half == "system" else user
    assert rendered == golden(template.removesuffix(".j2"), half)


def test_there_are_exactly_three_prompts_and_six_goldens():
    assert prompts.TEMPLATES == ("route.j2", "act.j2", "synthesize.j2")
    assert sorted(path.name for path in prompts.PROMPT_DIR.glob("*.j2")) == sorted(prompts.TEMPLATES)
    assert len(list(GOLDEN.glob("*.txt"))) == 2 * len(prompts.TEMPLATES)


@pytest.mark.parametrize("template", prompts.TEMPLATES)
def test_the_system_half_is_byte_stable_across_turns(template):
    """The cached prefix is *tools → system*; anything per-turn in there costs every cache read."""
    first, _ = prompts.render(template, **context(template))
    other = {
        **context(template),
        "persona": prompts.persona_block(employee_id="E1108", actor_source="default"),
        "question": "Something else entirely, asked on another day.",
    }
    if template == "synthesize.j2":
        other["chunks"] = []
        other["tool_results"] = []
    second, _ = prompts.render(template, **other)
    assert first == second


@pytest.mark.parametrize("template", prompts.TEMPLATES)
def test_the_user_half_carries_the_frozen_ordering(template):
    _, user = prompts.render(template, **context(template))
    assert user.index("ACTING PERSONA") == 0
    assert user.rstrip().endswith(QUESTION), "the question is last, after the evidence (§7.2)"
    if template == "synthesize.j2":
        assert user.index("ACTING PERSONA") < user.index("<document ") < user.index("QUESTION:")


def test_the_evidence_envelopes_label_trust_and_the_quarantine():
    _, user = prompts.render("synthesize.j2", **context("synthesize.j2"))
    assert user.count('trust="data"') == 3, "two documents and one tool result"
    lure = chunks()[1]
    assert f'id="{lure.chunk_id}"' in user and 'quarantined="true"' in user
    assert user.count('quarantined="true"') == 1


def test_the_document_envelope_carries_the_whole_chunk_not_the_snippet():
    """§7.2 renders `c.text`. The snippet is a 320-character display subset (`rag/chunk.py`).

    199 of the 204 committed chunks are longer than that, so rendering the snippet would have shown
    the synthesis model roughly a third of every chunk it was asked to ground an answer in.
    """
    _, user = prompts.render("synthesize.j2", **context("synthesize.j2"))
    for chunk in chunks():
        assert len(chunk.text) > len(chunk.snippet), "pick a chunk the snippet actually truncates"
        assert f"\n{chunk.text}\n</document>" in user, "the envelope body is the whole chunk"


def test_the_citation_coverage_block_lists_every_citable_document_once():
    """Rule 8's target list: one line per distinct citable document, quarantined ones excluded.

    The measured P10 failure was one-sided — the baseline retrieved across four documents and
    cited across two — so the synthesis prompt now renders the document inventory it is being
    asked to cover. A quarantined chunk must never appear: G2 strips every citation to it (§7.4
    trigger 4), so listing its document would set a target the answer is forbidden to hit.
    """
    _, user = prompts.render("synthesize.j2", **context("synthesize.j2"))
    coverage = user[user.index("CITATION COVERAGE") : user.index("QUESTION:")]
    citable = [chunk for chunk in chunks() if not chunk.quarantined]
    quarantined = [chunk for chunk in chunks() if chunk.quarantined]
    assert citable and quarantined, "the fixture must exercise both sides of the exclusion"

    assert f"CITATION COVERAGE — {len({chunk.doc_id for chunk in citable})} citable document(s)" in coverage
    assert coverage.count("\n- ") == len({chunk.doc_id for chunk in citable})
    for chunk in citable:
        assert f"- {chunk.doc_id} — {chunk.doc_title} — " in coverage
        assert chunk.chunk_id in coverage
    for chunk in quarantined:
        assert chunk.doc_id not in coverage, "a quarantined document is not a citation target"
        assert chunk.chunk_id not in coverage


def test_the_citation_coverage_block_survives_an_empty_evidence_set():
    """No citable chunk means no target list — rule 3's escalation, not a malformed prompt."""
    _, user = prompts.render("synthesize.j2", **{**context("synthesize.j2"), "chunks": [], "tool_results": []})
    assert "CITATION COVERAGE — 0 citable document(s)" in user
    assert user.rstrip().endswith(QUESTION)


def test_the_fusion_weight_is_never_labelled_score():
    _, user = prompts.render("synthesize.j2", **context("synthesize.j2"))
    assert 'rrf="0.0328"' in user
    assert 'rrf="0.0000"' in user, "a chunk with no fusion weight renders zero, never a null"
    assert "score=" not in user


def test_a_missing_context_key_fails_loudly():
    """`StrictUndefined`: a renamed variable is a test failure, never a hole in a prompt."""
    with pytest.raises(Exception, match="question"):
        prompts.render("route.j2", persona=PERSONA)


def test_an_unknown_template_is_refused():
    with pytest.raises(KeyError):
        prompts.render("summarise.j2", persona=PERSONA, question=QUESTION)


# --------------------------------------------------------------------------------------
# P13 — the three prompt rules the trace analysis of the judged baseline produced
# --------------------------------------------------------------------------------------

MANIFEST = Path(__file__).resolve().parents[2] / "data" / "index" / "chunks.manifest.jsonl"


def manifest_titles() -> list[str]:
    """Every document title in the committed manifest, ordered by `doc_id` as the index lists them."""
    titles: dict[str, str] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            titles[record["doc_id"]] = record["doc_title"]
    return [titles[doc_id] for doc_id in sorted(titles)]


def test_the_router_is_shown_the_corpus_it_is_deciding_scope_against():
    """R1: `out_of_scope` was a guess about a library the router had never been shown.

    The judged baseline routed an equipment question out of scope and refused a policy the corpus
    carries. The CORPUS paragraph sits directly under the field it governs and names the two
    directions explicitly — what is in, and that nothing else is.
    """
    system, _ = prompts.render("route.j2", **context("route.j2"))
    corpus = system[system.index("CORPUS —") : system.index("- sensitive")]

    assert "the policy library covers, and only covers:" in corpus
    assert "Set out_of_scope only when the turn is about none of these and is not the employee's own HR data." in corpus
    assert "Device refresh cycles, asset return, spend limits and approval thresholds are IN the corpus." in corpus
    assert system.index("- out_of_scope") < system.index("CORPUS —")


def test_the_corpus_paragraph_lists_exactly_the_manifest_titles():
    """The list is generated from the index, never typed: a corpus edit moves the prompt with it.

    The manifest is the committed record of what was ingested, so comparing against it is what
    stops the router's picture of the library drifting from the library.
    """
    system, _ = prompts.render("route.j2", **context("route.j2"))
    listed = system[system.index("covers, and only covers: ") + len("covers, and only covers: ") :]
    listed = listed[: listed.index(". Set out_of_scope")]

    titles = manifest_titles()
    assert len(titles) == 14
    assert listed.split("; ") == titles
    assert list(prompts.corpus_titles()) == titles


def test_a_tool_result_value_is_stated_without_a_citation():
    """R2: `pto-002` lost its balance to G2 — the number was cited, the citation stripped, the
    block dropped. Rule 6b says where a tool value belongs, immediately after the as_of rule."""
    system, _ = prompts.render("synthesize.j2", **context("synthesize.j2"))
    rule = system[system.index("6b.") : system.index("7. `rationale_summary`")]

    assert "employee data, not company policy" in rule
    assert "attach NO citation" in rule
    assert system.index("6. When a tool result carries an `as_of` date") < system.index("6b.")


def test_the_router_is_told_to_name_every_missing_detail():
    """R6: `amb-003` named one of the two missing details, and the clarification the user sees is
    built from that line."""
    system, _ = prompts.render("route.j2", **context("route.j2"))

    assert (
        "Name EVERY missing detail in rationale_summary, not only the first — the question the "
        "user is shown is built from that line." in system
    )
