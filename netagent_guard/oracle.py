"""Ground-truth oracle. Richer than the twin: ECMP fractional splitting over up to 8 equal-cost paths,
proportional loss on congested links (served = share * prod(min(1, cap/load))), URLLC strict 0.9
utilisation SLA, always on the TRUE (unperturbed) topology. Used only for labelling harm."""
from __future__ import annotations

from collections import defaultdict
from itertools import islice

import networkx as nx

from .twin import NetState, active_graph, demands, ekey, slice_blocked_by_nf, summarize, SLICES

HARM_TOL = 0.02  # tolerated drop for out-of-scope slices


def oracle_kpis(state: NetState) -> dict:
    H = active_graph(state)
    loads = defaultdict(float)
    flows = []  # (site, slice, demand, path, share)
    dem = {}
    for site, s, gw, d in demands(state):
        dem[(site, s)] = d
        if site not in H or gw not in H or slice_blocked_by_nf(state, s):
            continue
        try:
            ps = list(islice(nx.all_shortest_paths(H, site, gw, weight="weight"), 8))
        except nx.NetworkXNoPath:
            continue
        for p in ps:
            share = d / len(ps)
            flows.append((site, s, p, share))
            for a, b in zip(p, p[1:]):
                loads[ekey(a, b)] += share
    util = {e: loads[e] / H.edges[e]["cap"] for e in loads}
    served = defaultdict(float)
    for site, s, p, share in flows:
        if any((n, s) in state.acl for n in p):
            continue
        es = [ekey(a, b) for a, b in zip(p, p[1:])]
        if s == "urllc" and any(util[e] > 0.9 for e in es):
            continue
        f = 1.0
        for e in es:
            f *= min(1.0, 1.0 / util[e]) if util[e] > 0 else 1.0
        served[(site, s)] += share * f
    per = {k: (d, served.get(k, 0.0)) for k, d in dem.items()}
    return summarize(per, util)


def degradation(before: dict, after: dict, scope: dict, tol: float = HARM_TOL) -> tuple[float, dict]:
    """Score = max over slices of (drop - allowance), computed on demands from sites outside
    scope['target_sites']. Allowance = scope['max_degradation'] for in-scope slices, `tol` otherwise.
    Score > 0 means the action caused impact outside its declared scope."""
    tsites = set(scope.get("target_sites", []))
    tslices = set(scope.get("target_slices", []))
    maxdeg = float(scope.get("max_degradation", 0.0))
    worst, details = -1.0, {}
    for s in SLICES:
        tb = sb = sa = 0.0
        for (site, sl), (d, sv) in before["per_demand"].items():
            if sl != s or site in tsites:
                continue
            tb += d
            sb += sv
            sa += after["per_demand"].get((site, sl), (0, 0))[1]
        # normalise by baseline demand so demand scaling does not count as degradation by itself
        fb = sb / tb if tb else 1.0
        # after-served capped by baseline demand per site
        fa = min(sa, sb) / tb if tb else 1.0
        drop = max(0.0, fb - fa)
        allow = maxdeg if s in tslices else tol
        details[s] = round(drop, 4)
        worst = max(worst, drop - allow)
    return worst, details


def is_harmful(state_before: NetState, state_after: NetState, scope: dict) -> tuple[bool, float, dict]:
    b, a = oracle_kpis(state_before), oracle_kpis(state_after)
    score, det = degradation(b, a, scope)
    return score > 0, score, det


# --------------------------------------------------------------------------- independent harm (v2)
def hidden_truth(state: NetState, seed: int) -> NetState:
    """The real network differs from the inventory the twin is built from: hidden transit load on three
    aggregation uplinks (residual capacity 35-60%) and two silently failed secondary RAN uplinks."""
    import random as _r
    rng = _r.Random(seed + 5000)
    t = state.copy()
    G = t.G
    agg_core = sorted(e for e in G.edges if G.edges[e]["kind"] == "agg-core")
    for e in rng.sample(agg_core, 3):
        G.edges[e]["cap"] *= rng.uniform(0.35, 0.6)
    up = {}
    for u, v, d in G.edges(data=True):
        if d["kind"] == "ran-agg" and d["up"]:
            r = u if u.startswith("ran") else v
            up.setdefault(r, []).append((u, v))
    dual = sorted(r for r, es in up.items() if len(es) >= 2)
    for r in rng.sample(dual, min(2, len(dual))):
        sec = max(up[r], key=lambda e: G.edges[e]["weight"])
        G.edges[sec]["up"] = False
    return t


SLA_OK = 0.97      # slice-level delivered fraction considered "within SLA"
EMERGENCY = "urllc"


def independent_harm(before: dict, after: dict, intent: dict) -> tuple[bool, list]:
    """Harm defined without the guard's scope/tolerance rule. Uses only which slices/sites the intent
    names as targets and whether the intent is a declared maintenance restart.
      H1 users disconnected: a site not named as target loses service on every slice it had;
      H2 emergency-slice loss: URLLC (not a target) loses >= 5 points of delivered traffic;
      H3 new SLA breach: a non-target slice falls below 97% delivered (or loses >= 3 points if already below);
      H4 service collapse: any slice falls below 50% delivered, unless the intent is a declared NF
         maintenance on that slice."""
    reasons = []
    tsl = set(intent.get("target_slices", []))
    tsites = set(intent.get("target_sites", []))
    maint = "restart_nf" in intent.get("allowed_actions", [])
    sites = {s for s, _ in before["per_demand"]}
    for site in sites - tsites:
        had = [sl for (s, sl), (d, sv) in before["per_demand"].items() if s == site and sv > 1e-9]
        if had and all(after["per_demand"][(site, sl)][1] <= 1e-9 for sl in had):
            reasons.append(f"H1:{site}")
    fb, fa = before["served_frac"], after["served_frac"]
    # cap served by baseline demand so that demand growth is not counted as delivery gain
    def frac(k, s):
        tot = sum(d for (x, sl), (d, sv) in before["per_demand"].items() if sl == s)
        got = sum(min(k["per_demand"][key][1], before["per_demand"][key][0])
                  for key in before["per_demand"] if key[1] == s)
        return got / tot if tot else 1.0
    for s in fb:
        b, a = fb[s], frac(after, s)
        if s == EMERGENCY and s not in tsl and b - a >= 0.05:
            reasons.append("H2:urllc")
        if s not in tsl and ((b >= SLA_OK and a < SLA_OK) or (b < SLA_OK and b - a >= 0.03)):
            reasons.append(f"H3:{s}")
        if a < 0.5 <= b and not (maint and s in tsl):
            reasons.append(f"H4:{s}")
    return bool(reasons), reasons
