"""Digital twin of a small mobile transport network and the twin KPI model.

The guard uses `twin_kpis` (single weighted shortest path, binary SLA check).
The oracle (oracle.py) uses a richer model and is used only for labels.
"""
from __future__ import annotations

import copy
import random
from collections import defaultdict
from dataclasses import dataclass, field

import networkx as nx

# slice -> gateway (UPF site), per-site demand (Gb/s), utilization limit for SLA
SLICES = {
    "embb": {"gw": "core0", "demand": 3.0, "util_limit": 1.0},
    "urllc": {"gw": "core1", "demand": 1.0, "util_limit": 0.8},
    "mmtc": {"gw": "core2", "demand": 0.5, "util_limit": 1.0},
}
# network function -> slices that depend on it
NFS = {
    "upf-embb": ["embb"],
    "upf-urllc": ["urllc"],
    "upf-mmtc": ["mmtc"],
    "amf": ["embb", "urllc", "mmtc"],
    "smf": ["embb", "urllc", "mmtc"],
}


def ekey(u: str, v: str) -> tuple:
    return tuple(sorted((u, v)))


def build_topology(seed: int, n_core: int = 4, n_agg: int = 8, n_ran: int = 36) -> nx.Graph:
    """Core full mesh, aggregation dual-homed to core with an agg ring, RAN sites single/dual-homed."""
    rng = random.Random(seed)
    G = nx.Graph()
    cores = [f"core{i}" for i in range(n_core)]
    aggs = [f"agg{i}" for i in range(n_agg)]
    rans = [f"ran{i}" for i in range(n_ran)]
    for n in cores:
        G.add_node(n, tier="core")
    for n in aggs:
        G.add_node(n, tier="agg")
    for n in rans:
        G.add_node(n, tier="ran")
    for i, a in enumerate(cores):
        for b in cores[i + 1:]:
            G.add_edge(a, b, cap=200.0, weight=1.0, up=True, kind="core-core")
    for i, a in enumerate(aggs):
        c1 = cores[i % n_core]
        c2 = cores[(i + 1 + rng.randrange(n_core - 1)) % n_core]
        if c2 == c1:
            c2 = cores[(i + 1) % n_core]
        for c in (c1, c2):
            G.add_edge(a, c, cap=round(60.0 * rng.uniform(0.8, 1.2), 1), weight=1.0, up=True, kind="agg-core")
        b = aggs[(i + 1) % n_agg]
        G.add_edge(a, b, cap=30.0, weight=3.0, up=True, kind="agg-agg")
    for i, r in enumerate(rans):
        p = aggs[i % n_agg]
        G.add_edge(r, p, cap=10.0, weight=1.0, up=True, kind="ran-agg")
        s = aggs[(i + 1) % n_agg]
        if rng.random() < 0.6:
            G.add_edge(r, s, cap=10.0, weight=2.0, up=True, kind="ran-agg")
        elif rng.random() < 0.5:
            G.add_edge(r, s, cap=10.0, weight=2.0, up=False, kind="ran-agg-backup")
    return G


@dataclass
class NetState:
    G: nx.Graph
    slice_scale: dict = field(default_factory=lambda: {s: 1.0 for s in SLICES})
    nf_down: set = field(default_factory=set)
    acl: set = field(default_factory=set)  # (node, slice) deny
    down_nodes: set = field(default_factory=set)

    def copy(self) -> "NetState":
        return copy.deepcopy(self)


def active_graph(state: NetState) -> nx.Graph:
    H = nx.Graph()
    H.add_nodes_from(n for n in state.G.nodes if n not in state.down_nodes)
    for u, v, d in state.G.edges(data=True):
        if d.get("up", True) and u in H and v in H:
            H.add_edge(u, v, **d)
    return H


def ran_sites(G: nx.Graph) -> list:
    return [n for n, d in G.nodes(data=True) if d.get("tier") == "ran"]


def demands(state: NetState):
    for site in ran_sites(state.G):
        for s, spec in SLICES.items():
            yield site, s, spec["gw"], spec["demand"] * state.slice_scale.get(s, 1.0)


def slice_blocked_by_nf(state: NetState, s: str) -> bool:
    return any(s in NFS.get(nf, []) for nf in state.nf_down)


def summarize(per_demand: dict, util: dict) -> dict:
    """per_demand: {(site, slice): (demand, served)} -> KPI dict."""
    out = {"per_demand": per_demand, "util": util}
    served = defaultdict(float)
    total = defaultdict(float)
    reach = defaultdict(int)
    cnt = defaultdict(int)
    for (site, s), (d, sv) in per_demand.items():
        total[s] += d
        served[s] += sv
        cnt[s] += 1
        reach[s] += int(sv > 0)
    out["served_frac"] = {s: (served[s] / total[s] if total[s] else 1.0) for s in SLICES}
    out["sla_breach"] = {s: 1.0 - out["served_frac"][s] for s in SLICES}
    out["reachability"] = {s: reach[s] / cnt[s] if cnt[s] else 1.0 for s in SLICES}
    out["max_util"] = max(util.values()) if util else 0.0
    return out


def twin_kpis(state: NetState) -> dict:
    """Guard's model: each demand on one weighted shortest path; served iff path exists, no ACL hit,
    gateway NF up and every link on the path within the slice utilization limit."""
    H = active_graph(state)
    loads = defaultdict(float)
    paths = {}
    for site, s, gw, d in demands(state):
        p = None
        if site in H and gw in H and not slice_blocked_by_nf(state, s):
            try:
                p = nx.shortest_path(H, site, gw, weight="weight")
            except nx.NetworkXNoPath:
                p = None
        paths[(site, s)] = (p, d)
        if p:
            for a, b in zip(p, p[1:]):
                loads[ekey(a, b)] += d
    util = {e: loads[e] / H.edges[e]["cap"] for e in loads}
    per = {}
    for (site, s), (p, d) in paths.items():
        ok = p is not None
        if ok and any((n, s) in state.acl for n in p):
            ok = False
        if ok and any(util[ekey(a, b)] > SLICES[s]["util_limit"] for a, b in zip(p, p[1:])):
            ok = False
        per[(site, s)] = (d, d if ok else 0.0)
    return summarize(per, util)


def perturb_view(state: NetState, noise: float, seed: int) -> NetState:
    """Degraded twin fidelity: capacities perturbed by U(-noise, noise); each link dropped from the
    inventory with probability noise/5 (stale inventory)."""
    rng = random.Random(seed)
    v = state.copy()
    if noise <= 0:
        return v
    for u, w, d in list(v.G.edges(data=True)):
        d["cap"] = d["cap"] * (1.0 + rng.uniform(-noise, noise))
        if rng.random() < noise / 5.0:
            v.G.remove_edge(u, w)
    return v
