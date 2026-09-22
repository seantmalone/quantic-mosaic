## Task 5 — Blind reference labels and agreement (controller-orchestrated)

Closes gap **9**. Two fresh Opus sessions each read only one packet and author
`evaluation/reference_labels.yaml` (seed subset) and `evaluation/reference_labels_hard.yaml` (hard
subset) in the existing schema, with `protocol.blinding` naming exactly one run and stating plainly
which run's served answers the packet carried. Then `--recompute-agreement` for both metrics and
`--report` again. Commit as `G5(labels): ...`.

