#!/bin/sh
# Task 4 measurement chain on the deployed build. Sequential; logs every step.
set -u
cd /Users/sean/Projects/quantic-mosaic
W=.superpowers/sdd/2026-09-21-grade-5
R="$W/run_eval.py"
P=.venv/bin/python
step() { echo; echo "=== $(date -u +%FT%TZ) $*"; }
step "baseline drive"
$P "$R" evaluation.runner --variant baseline --label G5 --notes "G5 wave: published run on build 82994ce" || { echo "BASELINE DRIVE FAILED rc=$?"; exit 1; }
RUN=$($P -c "import json;print(json.load(open('evaluation/results/latest.json'))['run_id'])")
echo "baseline run id: $RUN"
step "judge $RUN"
$P "$R" evaluation.runner --judge "$RUN" || { echo "JUDGE FAILED rc=$?"; exit 1; }
step "arm dense_only_k2"
$P "$R" evaluation.runner --variant dense_only_k2 --label G5 || { echo "ARM1 FAILED rc=$?"; exit 1; }
step "arm no_structured_tools"
$P "$R" evaluation.runner --variant no_structured_tools --label G5 || { echo "ARM2 FAILED rc=$?"; exit 1; }
step "ablation"
$P "$R" evaluation.ablation; echo "ablation rc=$?"
step "report $RUN"
$P "$R" evaluation.runner --report "$RUN" || echo "REPORT FAILED rc=$?"
step "done"
echo "DONE $RUN"
