"""Free-text rendering of structured intents in several styles.

Train styles (used when writing the parser and for calibration): S1 structured, S2 natural, S3 ops
shorthand, S4 noisy natural (typos, casing, filler). Held-out styles (eval only, parser never tuned on
them): S5 formal/passive with synonyms, S6 Finglish (Persian in Latin script) mixed with English."""
from __future__ import annotations

import random

TRAIN_STYLES = ["S1", "S2", "S3", "S4"]
HELD_OUT_STYLES = ["S5", "S6"]

VERBS = {  # action -> style -> verb options
    "shutdown_link": {"S1": ["Drain"], "S2": ["take down", "drain", "shut"], "S3": ["DRAIN"],
                      "S5": ["temporarily decommission", "remove from service"], "S6": ["khamoosh konid", "az service kharej konid"]},
    "enable_link": {"S1": ["Enable"], "S2": ["bring up", "enable", "activate"], "S3": ["ENABLE"],
                    "S5": ["unshut", "restore to service"], "S6": ["roshan konid", "unshut konid"]},
    "set_link_weight": {"S1": ["Tune routing weight of"], "S2": ["adjust the metric on", "change the weight of"],
                        "S3": ["SET-WEIGHT"], "S5": ["re-cost", "rebalance the IGP cost on"],
                        "S6": ["cost ro avaz konid baraye", "weight ro taghir bedid baraye"]},
    "set_slice_bandwidth": {"S1": ["Increase bandwidth of"], "S2": ["bump the bandwidth of", "raise capacity for"],
                            "S3": ["SET-BW"], "S5": ["uplift the throughput allocation of", "provision more throughput for"],
                            "S6": ["pahnaye band ro bishtar konid baraye", "zarfiat ro ziad konid baraye"]},
    "restart_nf": {"S1": ["Restart network function"], "S2": ["restart", "bounce"], "S3": ["RESTART"],
                   "S5": ["re-initialise", "perform a controlled reload of"], "S6": ["restart konid", "dobare rah andazi konid"]},
    "add_acl": {"S1": ["Apply ACL filter for"], "S2": ["filter", "block"], "S3": ["ACL-DENY"],
                "S5": ["quarantine", "police and drop"], "S6": ["masdood konid", "filter konid"]},
    "read_kpis": {"S1": ["Check and report KPIs"], "S2": ["report KPIs", "check KPIs"], "S3": ["KPI-REPORT"],
                  "S5": ["produce a health summary", "provide a service-quality digest"], "S6": ["vaziat ro gozaresh bedid", "salamat shabake ro check konid"]},
}


def _obj(it):
    a, e = it["allowed_actions"][0], it["target_elements"]
    if a in ("shutdown_link", "enable_link", "set_link_weight"):
        return f"link {e[0]}-{e[1]}", f"{e[0]}<->{e[1]}", f"{e[0]}/{e[1]}"
    if a == "set_slice_bandwidth":
        return f"slice {e[0]}", f"the {e[0]} slice", f"slice={e[0]}"
    if a == "restart_nf":
        return e[0], e[0], f"nf={e[0]}"
    if a == "add_acl":
        s = it["target_slices"][0]
        return f"slice {s} at site {e[0]}", f"{s} traffic at {e[0]}", f"{e[0]} slice={s}"
    return "for all slices", "for every slice", "all"


def _typo(word, rng):
    if len(word) < 4 or any(c.isdigit() for c in word) or rng.random() > 0.15:
        return word
    i = rng.randrange(1, len(word) - 2)
    return word[:i] + word[i + 1] + word[i] + word[i + 2:]


def render(it: dict, style: str, rng: random.Random) -> str:
    act = it["allowed_actions"][0]
    verb_style = "S2" if style == "S4" else style
    verb = rng.choice(VERBS[act][verb_style])
    o1, o2, o3 = _obj(it)
    sl = it["target_slices"]
    pct = int(round(it["max_degradation"] * 100))
    pr = it.get("param_range")
    if style == "S1":
        t = f"{verb} {o1}. Scope: sites [none]; slices [{', '.join(sl) or 'none'}]; max degradation {pct}%."
        if pr:
            t += f" Parameter range {pr[0]:g} to {pr[1]:g}."
    elif style in ("S2", "S4"):
        lead = rng.choice(["Hi team, please", "Can you", "Tonight we need to", "Please"])
        t = f"{lead} {verb} {o2}" + (f" ({it['purpose']})" if it.get("purpose") else "") + "."
        t += (f" It's fine if {' and '.join(sl)} sees up to {pct}% impact, nothing else should be touched."
              if sl else " No customer impact expected.")
        if pr:
            t += f" Keep the value between {pr[0]:g} and {pr[1]:g}."
        if style == "S4":
            words = [_typo(w, rng) for w in t.split()]
            t = " ".join(words)
            t = rng.choice([t.lower(), t, t.upper() if rng.random() < 0.2 else t]) + rng.choice(["", " thx", " asap pls", " per CAB"])
    elif style == "S3":
        t = f"CHG: {verb} {o3} | slices={','.join(sl) or '-'} | sites=- | maxdeg={pct}%"
        if pr:
            t += f" | range={pr[0]:g}..{pr[1]:g}"
    elif style == "S5":
        t = (f"Objective: {verb} {o1}. Service tolerance: {pct} percent on "
             f"{', '.join(sl) if sl else 'no service'}; all other services must remain unaffected.")
        if pr:
            t += f" Admissible values: {pr[0]:g} through {pr[1]:g}."
    else:  # S6
        t = f"Lotfan {o2} ro {verb}." + (f" Ta {pct} darsad roye {' va '.join(sl)} eshkal nadare." if sl
                                         else " Nabayad roye moshtari asar bezare.")
        if pr:
            t += f" Meghdar bein {pr[0]:g} ta {pr[1]:g} bashe."
    return t
