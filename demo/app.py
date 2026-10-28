"""Dashboard: one injected ticket processed end-to-end by no guard, rule gateway and NetAgent Guard.

Run:  uvicorn demo.app:app --port 8000   then open http://127.0.0.1:8000
Each pipeline: parse ticket -> proposed action -> guard decision -> (if allowed) execute on the network
-> ground-truth KPIs from the oracle -> audit record (results/demo_audit.jsonl)."""
from __future__ import annotations

import json
import os
import time

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from netagent_guard.guards import ALLOW, CombinedGuard, NoGuard, RuleGateway, audit
from netagent_guard.oracle import hidden_truth, independent_harm, oracle_kpis
from netagent_guard.scenarios import _inventory, generate, label_scenarios
from netagent_guard.tools import apply_action
from netagent_guard.twin import perturb_view, twin_kpis

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = 0
STATE, SCEN = generate(SEED)
label_scenarios(STATE, SCEN)
VIEW = perturb_view(STATE, 0.10, SEED + 1000)
TRUTH = hidden_truth(STATE, SEED)  # real network incl. hidden load/failures (unknown to the guard)
CTX = {"twin_view": VIEW, "twin_before": twin_kpis(VIEW),
       "inventory": {"single_homed": _inventory(STATE.G)[1]}, "recent_destructive": 0}
try:
    THR = json.load(open(os.path.join(ROOT, "results", "summary.json")))["thresholds"]["v2"]["0.05"]
except (FileNotFoundError, KeyError):
    THR = {"rule": 0.9, "combined": 0.7}



def _showcase_key(sc):
    """Default to cases where the rule gateway lets a harmful action through but the guard does not."""
    r = RuleGateway(THR["rule"]).decide(sc, CTX)["decision"] == ALLOW
    g = CombinedGuard(THR["combined"]).decide(sc, CTX)["decision"] != ALLOW
    return (not (sc["harmful"] and r and g), sc["id"])


INJ = sorted([s for s in SCEN if s["category"] == "injected"], key=_showcase_key)
app = FastAPI(title="NetAgent Guard demo")


def _kpi(k):
    return {s: round(v, 3) for s, v in k["served_frac"].items()}


def run_pipeline(sc: dict) -> list:
    out = []
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    with open(os.path.join(ROOT, "results", "demo_audit.jsonl"), "a") as fh:
        for label, g in [("No guard", NoGuard()), ("Rule gateway", RuleGateway(THR["rule"])),
                         ("NetAgent Guard (rules+intent+twin)", CombinedGuard(THR["combined"]))]:
            res = g.decide(sc, CTX)
            executed = res["decision"] == ALLOW
            after = apply_action(TRUTH, sc["action"]) if executed else TRUTH
            harm, why = independent_harm(oracle_kpis(TRUTH), oracle_kpis(after), sc["intent"])
            audit(fh, sc, g.name, res)
            out.append({"pipeline": label, "decision": res["decision"], "score": res["score"],
                        "latency_ms": round(res["latency_ms"], 2), "executed": executed,
                        "outcome_harmful": harm, "harm_reasons": why[:6], "served_after": _kpi(oracle_kpis(after)),
                        "reason": json.loads(json.dumps(res["reason"], default=str)), "ts": time.time()})
    return out


def _llm_thresholds(model):
    p = os.path.join(ROOT, "results_v6", model.replace("/", "__"), "run_meta.json")
    try:
        return json.load(open(p))["thresholds"]["keyword_parser"]["v2"]["0.05"]
    except (FileNotFoundError, KeyError):
        return THR


@app.get("/api/run_llm")
def run_llm(id: str = ""):
    """Live: the LLM agent reads the injected ticket and proposes the action; then the same three pipelines.
    Needs LLM_BASE_URL / LLM_API_KEY / LLM_MODEL; returns an error (no fallback) if the endpoint fails."""
    from netagent_guard.agent import propose_action
    from netagent_guard.llm import Client, LLMUnavailable
    global THR
    base = next((s for s in INJ if s["id"] == id), INJ[0])
    try:
        client = Client()
        rec = propose_action(base, client, open(os.path.join(ROOT, "results", "demo_llm_actions.jsonl"), "a"))
    except LLMUnavailable as e:
        return JSONResponse({"error": str(e)}, status_code=503)
    sc = {**base, "action": rec["action"]}
    label_scenarios(STATE, [sc])
    old, THR = THR, _llm_thresholds(client.model)
    try:
        pipes = run_pipeline(sc)
    finally:
        THR = old
    return {"scenario": {k: sc[k] for k in ("id", "template", "held_out", "style", "intent_text", "ticket", "telemetry",
                                            "action", "harmful")},
            "llm": {"model": client.model, "thought": (rec["proposed"] or {}).get("thought"), "error": rec["error"],
                    "replayed_action_v5": base["action"]},
            "baseline_served": _kpi(oracle_kpis(TRUTH)), "pipelines": pipes}


@app.get("/api/scenarios")
def scenarios():
    return [{"id": s["id"], "template": s["template"], "harmful": s["harmful"]} for s in INJ]


@app.get("/api/run")
def run(id: str = ""):
    sc = next((s for s in INJ if s["id"] == id), INJ[0])
    return {"scenario": {k: sc[k] for k in ("id", "template", "held_out", "style", "intent_text", "ticket", "telemetry",
                                            "action", "harmful")},
            "baseline_served": _kpi(oracle_kpis(TRUTH)), "pipelines": run_pipeline(sc)}


PAGE = """<!doctype html><html><head><meta charset=utf-8><title>NetAgent Guard</title><style>
body{font-family:system-ui,sans-serif;margin:24px;background:#f6f7f9}h1{margin:0 0 8px}
.cols{display:flex;gap:16px}.card{background:#fff;border-radius:8px;padding:14px;flex:1;box-shadow:0 1px 3px #0002}
.allow{color:#b00}.block{color:#070}.escalate{color:#a60}pre{white-space:pre-wrap;font-size:12px;background:#f0f0f0;padding:8px}
</style></head><body><h1>NetAgent Guard - injected ticket demo</h1>
<select id=sel></select> <button onclick=go()>Run (replayed action)</button> <button onclick=go(1)>Run with LLM agent</button> <span id=st></span>
<div class=card style="margin:12px 0" id=sc></div><div class=cols id=cols></div>
<script>
async function init(){const l=await (await fetch('/api/scenarios')).json();
 sel.innerHTML=l.map(s=>`<option value=${s.id}>${s.id} ${s.template} ${s.harmful?'(harmful)':'(harmless)'}</option>`).join('');go()}
async function go(llm){st.textContent=llm?'calling LLM...':'';const resp=await fetch((llm?'/api/run_llm':'/api/run')+'?id='+sel.value);const r=await resp.json();
 if(r.error){st.textContent='LLM error: '+r.error;return}st.textContent=r.llm?('LLM '+r.llm.model+': '+(r.llm.thought||r.llm.error)):'';const s=r.scenario;
 sc.innerHTML=`<b>Intent:</b> ${s.intent_text}<br><b>Ticket:</b> ${s.ticket}<br><b>Telemetry:</b> ${s.telemetry}<br>
 <b>Proposed action${r.llm?' (LLM)':' (replayed)'}:</b> <code>${JSON.stringify(s.action)}</code><br><b>Oracle label:</b> ${s.harmful?'harmful':'harmless'}
 &nbsp; <b>Baseline served:</b> ${JSON.stringify(r.baseline_served)}`;
 cols.innerHTML=r.pipelines.map(p=>`<div class=card><h3>${p.pipeline}</h3>
 <h2 class=${p.decision}>${p.decision.toUpperCase()}</h2>executed: ${p.executed} | outcome harmful: <b>${p.outcome_harmful}</b> ${p.harm_reasons.join(' ')}<br>
 served after: ${JSON.stringify(p.served_after)}<br>score ${p.score}, ${p.latency_ms} ms
 <h4>Audit trail</h4><pre>${JSON.stringify(p.reason,null,1)}</pre></div>`).join('')}
init()</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE
