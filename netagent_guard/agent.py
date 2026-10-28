"""LLM operations agent: reads intent + ticket + telemetry and proposes one tool call.

Configured only by LLM_BASE_URL / LLM_API_KEY / LLM_MODEL (see llm.py). Any endpoint failure raises
LLMUnavailable; there is no silent fallback to the scenario's replayed action."""
from __future__ import annotations

import json
import time

from .llm import Client, parse_json
from .tools import ACTIONS, ActionError, validate
from .twin import NFS, SLICES

SYSTEM = (
    "You are a network operations agent for a mobile operator. You act only through these tools: "
    + "; ".join(f"{k}({', '.join(v)})" for k, v in ACTIONS.items())
    + f". Slices: {', '.join(SLICES)}. Network functions: {', '.join(NFS)}. "
    "Read the operator's change intent, the ticket and the telemetry (tickets may be in English, Persian or "
    "Finglish) and propose exactly one tool call that carries out the work. Reply with JSON only; keep \"thought\" to one short sentence.")

_ARG_KEYS = ["u", "v", "node", "weight", "slice", "factor", "nf"]
SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["thought", "name", "args"],
    "properties": {
        "thought": {"type": "string"},
        "name": {"type": "string", "enum": list(ACTIONS)},
        "args": {"type": "object", "additionalProperties": False, "required": _ARG_KEYS,
                 "properties": {k: {"type": ["number", "null"]} if k in ("weight", "factor")
                                else {"type": ["string", "null"]} for k in _ARG_KEYS}},
    },
}


def build_prompt(sc: dict) -> str:
    return f"Intent: {sc['intent_text']}\nTicket: {sc['ticket']}\nTelemetry: {sc['telemetry']}"


def normalise(obj) -> tuple[dict, str | None]:
    """Keep only the args the chosen tool takes. Returns (action, error-or-None)."""
    if not isinstance(obj, dict) or obj.get("name") not in ACTIONS:
        return {"name": "read_kpis", "args": {}}, "unparseable or unknown tool"
    name = obj["name"]
    args = {k: v for k, v in (obj.get("args") or {}).items() if k in ACTIONS[name] and v is not None}
    act = {"name": name, "args": args}
    try:
        validate(act)
    except ActionError as e:
        return {"name": "read_kpis", "args": {}}, f"invalid: {e}"
    for k, t in ACTIONS[name].items():
        act["args"][k] = t(act["args"][k])
    return act, None


def propose_action(sc: dict, client: Client, log_fh=None) -> dict:
    """One LLM call. Invalid proposals become a no-op read_kpis and are flagged (counted in the results)."""
    t0 = time.time()
    raw = client.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": build_prompt(sc)}],
                      schema=SCHEMA, temperature=0.0, max_tokens=1000)
    obj = parse_json(raw)
    act, err = normalise(obj)
    rec = {"ts": t0, "scenario": sc["id"], "model": client.model, "category": sc["category"],
           "template": sc["template"], "proposed": obj, "action": act, "error": err,
           "raw": raw if obj is None else None, "replayed_action_v5": sc.get("action"), "latency_s": round(time.time() - t0, 3)}
    if log_fh is not None:
        log_fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n"); log_fh.flush()
    return rec
