"""Eight typed network actions. `apply_action` returns a new state (pure)."""
from __future__ import annotations

from .twin import NFS, SLICES, NetState

ACTIONS = {
    "shutdown_link": {"u": str, "v": str},
    "enable_link": {"u": str, "v": str},
    "shutdown_node": {"node": str},
    "set_link_weight": {"u": str, "v": str, "weight": float},
    "set_slice_bandwidth": {"slice": str, "factor": float},
    "restart_nf": {"nf": str},
    "add_acl": {"node": str, "slice": str},
    "read_kpis": {},
}


class ActionError(ValueError):
    pass


def validate(action: dict) -> None:
    name = action.get("name")
    if name not in ACTIONS:
        raise ActionError(f"unknown action {name}")
    args = action.get("args", {})
    for k, t in ACTIONS[name].items():
        if k not in args:
            raise ActionError(f"missing arg {k}")
        try:
            t(args[k])
        except (TypeError, ValueError) as e:
            raise ActionError(f"bad type for {k}") from e
    if name in ("set_slice_bandwidth", "add_acl") and args["slice"] not in SLICES:
        raise ActionError("unknown slice")
    if name == "restart_nf" and args["nf"] not in NFS:
        raise ActionError("unknown nf")


def targets(action: dict) -> set:
    """Network elements an action touches (node names and 'u-v' link ids)."""
    a = action.get("args", {})
    n = action["name"]
    if n in ("shutdown_link", "enable_link", "set_link_weight"):
        return {a["u"], a["v"]}
    if n in ("shutdown_node", "add_acl"):
        return {a["node"]}
    if n == "restart_nf":
        return {a["nf"]}
    if n == "set_slice_bandwidth":
        return {a["slice"]}
    return set()


def apply_action(state: NetState, action: dict) -> NetState:
    validate(action)
    s = state.copy()
    n, a = action["name"], action.get("args", {})
    G = s.G
    if n in ("shutdown_link", "enable_link", "set_link_weight"):
        if G.has_edge(a["u"], a["v"]):
            e = G.edges[a["u"], a["v"]]
            if n == "shutdown_link":
                e["up"] = False
            elif n == "enable_link":
                e["up"] = True
            else:
                e["weight"] = float(a["weight"])
    elif n == "shutdown_node":
        if a["node"] in G:
            s.down_nodes.add(a["node"])
    elif n == "set_slice_bandwidth":
        s.slice_scale[a["slice"]] = float(a["factor"])
    elif n == "restart_nf":
        # modelled as the NF being unavailable during the evaluation window
        s.nf_down.add(a["nf"])
    elif n == "add_acl":
        s.acl.add((a["node"], a["slice"]))
    return s
