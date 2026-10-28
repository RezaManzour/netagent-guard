"""Parser accuracy from cached LLM intent extractions only (no LLM calls). Usage:
python -m netagent_guard.parser_offline results_v6/<model_dir>"""
import json
import os
import sys

import pandas as pd

from .eval import CALIB_SEED, N_SCEN, SEEDS
from .guards import parse_accuracy, parse_intent_deterministic
from .scenarios import generate

PCOLS = ["action", "elements", "slices", "max_degradation", "param_range", "all"]

if __name__ == "__main__":
    d = sys.argv[1]
    cache = {}
    for line in open(os.path.join(d, "llm_intents.jsonl"), encoding="utf-8"):
        r = json.loads(line); cache[r["text"]] = r["parsed"]
    rows, missing = [], 0
    for s in SEEDS:
        for x in generate(s, N_SCEN)[1]:
            p = cache.get(x["intent_text"])
            if p is None:
                missing += 1; continue
            for parser, q in [("keyword", parse_intent_deterministic(x["intent_text"])), ("llm", p)]:
                rows.append({"parser": parser, "style": x["style"], "style_held_out": x["style_held_out"], **parse_accuracy(q, x["intent"])})
    pa = pd.DataFrame(rows)
    acc = pa.groupby(["parser", "style", "style_held_out"])[PCOLS].mean()
    acc["n"] = pa.groupby(["parser", "style", "style_held_out"]).size()
    acc.reset_index().to_csv(os.path.join(d, "parser_accuracy.csv"), index=False)
    print(acc.round(3).to_string(), "\nmissing:", missing)
