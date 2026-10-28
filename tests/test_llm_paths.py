"""LLM paths with a mocked transport: no key or network needed."""
import json

import pytest

from netagent_guard.agent import propose_action
from netagent_guard.guards import BLOCK, IntentGuard, llm_parse_intent
from netagent_guard.llm import Client, LLMUnavailable, config
from netagent_guard.scenarios import generate


def mock(content, record=None):
    def t(body):
        if record is not None:
            record.append(body)
        return {"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    return Client(transport=t)


def test_config_fails_loudly(monkeypatch):
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(LLMUnavailable):
        config()


def test_unreachable_endpoint_raises(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("LLM_API_KEY", "x")
    monkeypatch.setenv("LLM_MODEL", "m")
    with pytest.raises(LLMUnavailable):
        Client(retries=1).chat([{"role": "user", "content": "hi"}])


def test_agent_logs_and_normalises(tmp_path):
    st, sc = generate(0)
    s = sc[0]
    calls = []
    c = mock(json.dumps({"thought": "t", "name": "set_slice_bandwidth",
                         "args": {"u": None, "v": None, "node": None, "weight": None, "slice": "embb", "factor": 1.2, "nf": None}}), calls)
    p = tmp_path / "log.jsonl"
    with open(p, "w") as fh:
        r = propose_action(s, c, fh)
    assert r["action"] == {"name": "set_slice_bandwidth", "args": {"slice": "embb", "factor": 1.2}}
    assert r["error"] is None and json.loads(p.read_text())["scenario"] == s["id"]
    assert calls[0]["temperature"] == 0.0 and s["ticket"] in calls[0]["messages"][1]["content"]


def test_agent_invalid_output_is_flagged():
    st, sc = generate(0)
    r = propose_action(sc[0], mock("not json"))
    assert r["error"] and r["action"]["name"] == "read_kpis"


def test_llm_error_payload_raises():
    c = Client(transport=lambda b: {"error": {"code": 429, "message": "rate limited"}})
    with pytest.raises(LLMUnavailable):
        c.chat([{"role": "user", "content": "x"}])


def test_intent_extractor_only_sees_intent_text():
    st, sc = generate(0)
    s = next(x for x in sc if x["category"] == "injected")
    calls = []
    out = json.dumps({"action": "add_acl", "target_elements": ["RAN3"], "target_slices": ["mmtc"],
                      "max_degradation_pct": 5, "param_lo": None, "param_hi": None})
    p = llm_parse_intent(s["intent_text"], mock(out, calls))
    sent = json.dumps(calls[0]["messages"])
    assert s["ticket"] not in sent and s["telemetry"] not in sent
    assert p["allowed_actions"] == ["add_acl"] and p["target_elements"] == ["mmtc", "ran3"]
    assert p["max_degradation"] == 0.05


def test_intent_unknown_fallback_and_guard_uses_cached_parse():
    out = json.dumps({"action": "unknown", "target_elements": [], "target_slices": [], "max_degradation_pct": 0,
                      "param_lo": None, "param_hi": None})
    p = llm_parse_intent("???", mock(out))
    assert p["allowed_actions"] == []
    assert llm_parse_intent("x", mock("garbage"))["parser"] == "llm-malformed"
    st, sc = generate(0)
    s = dict(next(x for x in sc if x["action"]["name"] == "shutdown_link"))
    s["parsed_intent"] = {**p, "allowed_actions": ["read_kpis"]}
    assert IntentGuard(0.5).decide(s, {"twin_view": st})["decision"] == BLOCK


def test_demo_llm_endpoint_mocked(monkeypatch):
    from fastapi.testclient import TestClient
    import demo.app as dapp
    import netagent_guard.llm as L
    body = json.dumps({"thought": "t", "name": "read_kpis", "args": {k: None for k in ["u", "v", "node", "weight", "slice", "factor", "nf"]}})
    monkeypatch.setattr(L.Client, "__init__", lambda self, transport=None, retries=3: (
        setattr(self, "cfg", None), setattr(self, "retries", 1), setattr(self, "usage", {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}),
        setattr(self, "transport", lambda b: {"choices": [{"message": {"content": body}}]}))[0])
    r = TestClient(dapp.app).get("/api/run_llm").json()
    assert r["scenario"]["action"]["name"] == "read_kpis" and len(r["pipelines"]) == 3


def test_demo_llm_endpoint_fails_loudly(monkeypatch):
    from fastapi.testclient import TestClient
    import demo.app as dapp
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    assert TestClient(dapp.app).get("/api/run_llm").status_code == 503
