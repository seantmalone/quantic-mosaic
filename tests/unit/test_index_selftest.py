"""`python -m hrmosaic.rag.index --selftest` — the build-time proof that the index answers (§6.5).

It is a `RUN` line in the `Dockerfile` and a P4 acceptance command, which is exactly why it needs
tests of its own: nothing else in the suite runs it, and a self-test that cannot *fail* proves
nothing. So the three ways it is meant to go red are driven here — the top-1 document is wrong, the
index built empty, and `index_meta.chunk_count` has drifted from the committed manifest — alongside
the green path against the real committed index.

The failing cases run against the session's `corpus_mini` index, built with `EMBED_PROVIDER=fake`;
`fake_embedder` is what makes `open_index()`'s mismatch guard admit it (spec §16.5).
"""

from __future__ import annotations

import pytest

from hrmosaic.rag import index


def _mini_manifest(mini_ingest):
    return mini_ingest.index_path.parent / "chunks.manifest.jsonl"


def test_a_zero_vector_scores_zero_rather_than_dividing_by_zero():
    """`cosine` is the one score definition; a degenerate vector must not take retrieval down."""
    assert index.cosine([0.0, 0.0, 0.0], [1.0, 2.0, 3.0]) == 0.0
    assert index.cosine([1.0, 2.0, 3.0], [0.0, 0.0, 0.0]) == 0.0
    assert index.cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_the_selftest_resolves_its_fixed_question_to_the_one_document_that_answers_it(capsys):
    """The green path, against the real committed index — what the Docker build asserts."""
    assert index.selftest() == 0
    printed = capsys.readouterr().out
    assert index.SELFTEST_DOC_ID in printed
    assert "dense_score" in printed and "chunk_count" in printed
    assert printed.strip().endswith(f"OK — {index.SELFTEST_QUERY!r} resolves to {index.SELFTEST_DOC_ID}")


def test_the_selftest_fails_when_the_top_hit_is_not_the_document_that_carries_the_answer(
    mini_ingest, fake_embedder, monkeypatch, capsys
):
    """A corpus edit that moves the answer elsewhere must stop the build, not ship a quiet index.

    The retrieval floor is dropped for the length of the test because the hash embedder's query and
    passage vectors are near-orthogonal by construction: at the shipped `MIN_SUPPORT_SCORE` this
    index returns nothing at all, which is the *other* failure (below). Both problems are then
    reported — the wrong document, and a dense score under the §6.5 floor.
    """
    from hrmosaic.settings import settings

    monkeypatch.setattr(settings, "min_support_score", -1.0)

    assert index.selftest(mini_ingest.index_path, _mini_manifest(mini_ingest)) == 1
    printed = capsys.readouterr().out
    assert "FAIL —" in printed
    assert f"expected {index.SELFTEST_DOC_ID!r}" in printed
    assert f"< {index.SELFTEST_MIN_DENSE_SCORE}" in printed


def test_the_selftest_fails_when_the_index_built_empty(tmp_path, fake_embedder, capsys):
    """Zero chunks is the failure a "did it build?" check exists for: it reports "no hits"."""
    index_path = index.build_index(
        [], [], index_path=tmp_path / "empty.sqlite", corpus_sha256="", manifest_sha256="", format_counts={}
    )
    manifest = tmp_path / "chunks.manifest.jsonl"
    manifest.write_text("", encoding="utf-8")

    assert index.selftest(index_path, manifest) == 1
    assert "no hits" in capsys.readouterr().out


def test_the_selftest_fails_when_the_stored_chunk_count_has_drifted_from_the_manifest(
    mini_ingest, fake_embedder, tmp_path, capsys
):
    """R1.4: the committed manifest is the determinism claim, so a drifted count is fatal."""
    manifest = tmp_path / "chunks.manifest.jsonl"
    manifest.write_text('{"chunk_id": "only-one-line"}\n', encoding="utf-8")

    assert index.selftest(mini_ingest.index_path, manifest) == 1
    printed = capsys.readouterr().out
    assert "!= manifest lines 1" in printed


def test_the_command_line_refuses_to_run_with_nothing_to_do(capsys):
    """`python -m hrmosaic.rag.index` on its own is a mistake, and argparse says which one."""
    with pytest.raises(SystemExit) as exit_info:
        index.main([])
    assert exit_info.value.code == 2
    assert "pass --selftest" in capsys.readouterr().err


def test_the_command_line_runs_the_selftest_against_the_index_path_it_is_given(mini_ingest, fake_embedder, capsys):
    """`--index-path` is how the Docker build points the check at the image's own index."""
    assert index.main(["--selftest", "--index-path", str(mini_ingest.index_path)]) == 1
    assert "FAIL —" in capsys.readouterr().out
