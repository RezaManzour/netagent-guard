#!/usr/bin/env python
"""Regenerate the results summary tables from the CSV/JSON files that are already in the repo.

No experiment is run and no network or LLM call is made: this only reads `results/` (offline evaluation),
`results_mvp1/` (before/after table) and `results_v6/<model>/<variant>/` (optional LLM-agent run) and renders markdown.

    python scripts/make_tables.py                       # print all tables to stdout
    python scripts/make_tables.py --output tables.md    # write them to a file
    python scripts/make_tables.py --no-v6               # offline tables only (same text as results/tables.md)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pandas as pd  # noqa: E402

from netagent_guard.report import GUARDS, _p, tables  # noqa: E402

V6_GUARDS = GUARDS + ["comb-no_twin"]


def v6_tables(v6_dir: str, budget: float = 0.05) -> str:
    """Summary of the optional LLM-agent run(s): harm v2 at the given false-block budget, from main_metrics_v2.csv."""
    lines = ["## Optional LLM-agent run (results_v6, harm v2, %g%% false-block budget)" % (100 * budget), ""]
    if not os.path.isdir(v6_dir):
        return "\n".join(lines + ["_No results_v6 directory found._", ""])
    for model in sorted(os.listdir(v6_dir)):
        mdir = os.path.join(v6_dir, model)
        if not os.path.isdir(mdir):
            continue
        name = model.replace("__", "/")
        variants = [v for v in ("keyword_parser", "llm_parser")
                    if os.path.exists(os.path.join(mdir, v, "main_metrics_v2.csv"))]
        if not variants:
            lines += [f"### {name}", "", "_INCOMPLETE: no guard evaluation was run for this model; not used for guard metrics._", ""]
            continue
        for v in variants:
            m = pd.read_csv(os.path.join(mdir, v, "main_metrics_v2.csv"))
            m = m[(m.budget == budget) & m.guard.isin(V6_GUARDS)]
            if m.empty:
                continue
            lines += [f"### {name}, {v} (harmful scenarios: {int(m.n_harmful.iloc[0])} of {int(m.n.iloc[0])})", "",
                      "| guard | thr | harmful-exec [95% CI] | false-block [95% CI] | escalation |", "|---|---|---|---|---|"]
            for _, r in m.iterrows():
                lines.append(f"| {r.guard} | {r.threshold:g} | {_p(r.harmful_exec_rate)} [{_p(r.her_ci_lo)}, {_p(r.her_ci_hi)}] | "
                             f"{_p(r.false_block_rate)} [{_p(r.fbr_ci_lo)}, {_p(r.fbr_ci_hi)}] | {_p(r.escalation_rate)} |")
            lines.append("")
    return "\n".join(lines)


def build(results_dir="results", before_dir="results_mvp1", v6_dir="results_v6", include_v6=True) -> str:
    """Relative directories are resolved from the repository root, whatever the current directory is."""
    cwd = os.getcwd()
    os.chdir(ROOT)  # report.tables() prints the directory names it was given, so keep them relative
    try:
        text = tables(results_dir, before_dir)
        if include_v6:
            text += "\n\n" + v6_tables(v6_dir)
    finally:
        os.chdir(cwd)
    return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results-dir", default="results")
    ap.add_argument("--before-dir", default="results_mvp1")
    ap.add_argument("--v6-dir", default="results_v6")
    ap.add_argument("--no-v6", action="store_true", help="skip the results_v6 (LLM run) tables")
    ap.add_argument("--output", help="write to this file instead of stdout")
    a = ap.parse_args(argv)
    text = build(a.results_dir, a.before_dir, a.v6_dir, not a.no_v6)
    if a.output:
        with open(a.output, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
