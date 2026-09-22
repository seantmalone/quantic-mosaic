"""`assert_comparable` — the three ways an ablation silently becomes a lie (spec §13.9, G5 gap 8).

`evaluation/ablation.py` compares the newest run of each variant, and a comparison is only a
comparison if the arms differ in **one** thing: the variant. It has always guarded `target` (a
deployed baseline against two local arms) and `dataset_sha` (a moved dataset). The third guard is
the **build**, and its absence is what let the published trio pair a `baseline` measured on
`bd4ac93` against two arms measured on `34717b5`: on that pairing `dense_only_k2` came out *ahead*
of `baseline` on tool selection, which is a difference between two builds of the assistant and not
the effect of dropping the sparse retriever.

`target_git_sha` is optional by design — a `local` target has no second sha, and no run file written
before 2026-09-11 carries one — so an all-`None` set is one value and still comparable. A *mix* of
`None` and a sha is not: nothing in it says the two runs were measured on the same code.
"""

from __future__ import annotations

import pytest

from evaluation import ablation
from evaluation.schema import RunConfig, RunFile, RunMetrics

DEPLOYED = "https://mosaic-hr-copilot.onrender.com"
BUILD_A = "bd4ac9336e87f1233f848ef4e5635c29e07cd15b"
BUILD_B = "34717b52eb01312097ec41fe8a07394843d215d6"

CONFIG = RunConfig(
    retrieval_k=5,
    retrieval_strategy="hybrid_rrf",
    llm_model="claude-haiku-4-5",
    judge_model="gemini-3.5-flash-lite",
    min_evidence_score=0.6,
    min_support_score=0.45,
    llm_rpm=10,
    seed=1729,
)


def _run(variant: str, workflow_completion: float = 1.0, **overrides: object) -> RunFile:
    fields: dict[str, object] = {
        "run_id": f"r_test_{variant}",
        "created_at": 1,
        "git_sha": "0" * 40,
        "target_git_sha": BUILD_A,
        "label": variant,
        "variant": variant,
        "target": "deployed",
        "target_base_url": DEPLOYED,
        "dataset_sha": "0" * 64,
        "config": CONFIG,
        "n_items": 26,
        "metrics": RunMetrics(workflow_completion=workflow_completion, strict_pass_rate=0.8),
    }
    fields.update(overrides)
    return RunFile(**fields)  # type: ignore[arg-type]


def _trio(**overrides: object) -> dict[str, RunFile]:
    return {name: _run(name, **overrides) for name in ablation.VARIANT_ORDER}


def test_three_arms_on_one_target_dataset_and_build_are_comparable():
    ablation.assert_comparable(list(_trio().values()))


def test_a_mixed_target_is_refused():
    runs = _trio()
    runs["dense_only_k2"] = _run("dense_only_k2", target="local", target_base_url="http://127.0.0.1:8000")
    with pytest.raises(ablation.AblationError, match="do not share a target"):
        ablation.assert_comparable(list(runs.values()))


def test_a_moved_dataset_is_refused():
    runs = _trio()
    runs["no_structured_tools"] = _run("no_structured_tools", dataset_sha="1" * 64)
    with pytest.raises(ablation.AblationError, match="do not share a dataset_sha"):
        ablation.assert_comparable(list(runs.values()))


def test_arms_measured_on_two_builds_are_refused():
    """The published pairing itself: one baseline on `bd4ac93`, two arms on `34717b5`."""
    runs = _trio(target_git_sha=BUILD_B)
    runs["baseline"] = _run("baseline", target_git_sha=BUILD_A)
    with pytest.raises(ablation.AblationError, match="do not share a target_git_sha") as raised:
        ablation.assert_comparable(list(runs.values()))
    # The message names which arm was on which build — a bare "not comparable" sends a reader
    # looking through sixteen run files for the pair that differs.
    assert BUILD_A[:12] in str(raised.value) and BUILD_B[:12] in str(raised.value)


def test_runs_that_record_no_build_at_all_stay_comparable():
    """A `local` target, and every run file written before 2026-09-11: `None` is one value."""
    ablation.assert_comparable(list(_trio(target_git_sha=None).values()))


def test_a_recorded_build_beside_an_unrecorded_one_is_refused():
    runs = _trio(target_git_sha=None)
    runs["dense_only_k2"] = _run("dense_only_k2", target_git_sha=BUILD_B)
    with pytest.raises(ablation.AblationError, match="do not share a target_git_sha") as raised:
        ablation.assert_comparable(list(runs.values()))
    assert "baseline=none" in str(raised.value)


def test_the_published_comparison_refuses_to_be_written_across_two_builds():
    """The guard is on the write path, not only on the helper: `build_comparison` calls it first."""
    runs = _trio()
    runs["dense_only_k2"] = _run("dense_only_k2", target_git_sha=BUILD_B)
    with pytest.raises(ablation.AblationError, match="do not share a target_git_sha"):
        ablation.build_comparison(runs)


def test_the_comparison_and_its_report_footnote_name_the_one_shared_build():
    comparison = ablation.build_comparison(_trio(target_git_sha=BUILD_B))
    assert comparison["target_git_sha"] == BUILD_B
    assert f"`target_git_sha: {BUILD_B[:12]}…`" in ablation.render_section(comparison)


def test_a_local_comparison_says_it_has_no_build_rather_than_naming_none():
    comparison = ablation.build_comparison(_trio(target_git_sha=None, target="local", target_base_url="http://x"))
    assert comparison["target_git_sha"] is None
    assert "no `target_git_sha` (a local target)" in ablation.render_section(comparison)
