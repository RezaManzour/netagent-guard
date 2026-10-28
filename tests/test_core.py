import pytest

from netagent_guard.guards import BLOCK, ALLOW, CombinedGuard, IntentGuard, RuleGateway, parse_intent_deterministic
from netagent_guard.oracle import is_harmful, oracle_kpis
from netagent_guard.scenarios import generate, label_scenarios
from netagent_guard.tools import ActionError, apply_action, validate
from netagent_guard.twin import NetState, build_topology, perturb_view, twin_kpis


@pytest.fixture(scope="module")
def net():
    return NetState(build_topology(0))


def test_topology_size(net):
    assert 30 <= net.G.number_of_nodes() <= 60
    assert {d["tier"] for _, d in net.G.nodes(data=True)} == {"core", "agg", "ran"}


def test_baseline_healthy(net):
    for k in (twin_kpis(net), oracle_kpis(net)):
        assert all(v > 0.99 for v in k["served_frac"].values())


def test_core_shutdown_harms(net):
    after = apply_action(net, {"name": "shutdown_node", "args": {"node": "core0"}})
    h, s, _ = is_harmful(net, after, {"target_slices": [], "target_sites": [], "max_degradation": 0})
    assert h and twin_kpis(after)["served_frac"]["embb"] == 0


def test_read_kpis_harmless(net):
    after = apply_action(net, {"name": "read_kpis", "args": {}})
    assert not is_harmful(net, after, {})[0]


def test_validate():
    with pytest.raises(ActionError):
        validate({"name": "format_disk", "args": {}})
    with pytest.raises(ActionError):
        validate({"name": "restart_nf", "args": {"nf": "nope"}})


def test_apply_is_pure(net):
    apply_action(net, {"name": "add_acl", "args": {"node": "agg0", "slice": "urllc"}})
    assert not net.acl


def test_noise_changes_caps(net):
    v = perturb_view(net, 0.3, 1)
    assert any(abs(v.G.edges[e]["cap"] - net.G.edges[e]["cap"]) > 1e-6 for e in v.G.edges)


def test_generator_deterministic():
    a = generate(3)[1]
    b = generate(3)[1]
    assert [x["action"] for x in a] == [x["action"] for x in b]
    assert len(a) == 200 and {x["category"] for x in a} == {"benign", "injected", "erroneous"}


def test_parser_roundtrip_structured_styles():
    st, sc = generate(1)
    for s in [x for x in sc if x["style"] in ("S1", "S3")]:
        p = parse_intent_deterministic(s["intent_text"])
        assert p["allowed_actions"] == s["intent"]["allowed_actions"]
        assert set(p["target_slices"]) == set(s["intent"]["target_slices"])


def test_guards_on_injection(net):
    st, sc = generate(0)
    label_scenarios(st, sc)
    inj = next(s for s in sc if s["template"] == "I1")
    ctx = {"twin_view": st}
    assert RuleGateway(0.9).decide(inj, ctx)["decision"] == BLOCK
    assert IntentGuard(0.5).decide(inj, ctx)["decision"] == BLOCK
    ben = next(s for s in sc if s["template"] == "B7")
    assert CombinedGuard(0.05).decide(ben, ctx)["decision"] == ALLOW


def test_demo_endpoint():
    from fastapi.testclient import TestClient
    from demo.app import app
    c = TestClient(app)
    r = c.get("/api/run").json()
    assert [p["pipeline"] for p in r["pipelines"]][0] == "No guard"
    assert r["pipelines"][0]["executed"] is True


def test_independent_harm_and_hidden_truth(net):
    from netagent_guard.oracle import hidden_truth, independent_harm
    t = hidden_truth(net, 0)
    assert sum(not d["up"] for *_, d in t.G.edges(data=True)) > sum(not d["up"] for *_, d in net.G.edges(data=True))
    b = oracle_kpis(t)
    a = oracle_kpis(apply_action(t, {"name": "restart_nf", "args": {"nf": "amf"}}))
    h, why = independent_harm(b, a, {"target_slices": [], "allowed_actions": ["read_kpis"]})
    assert h and any(r.startswith("H1") for r in why)


def test_parser_heldout_styles_not_trivial():
    from netagent_guard.guards import parse_accuracy
    st, sc = generate(2)
    ho = [parse_accuracy(parse_intent_deterministic(s["intent_text"]), s["intent"])["all"] for s in sc if s["style_held_out"]]
    assert ho and sum(ho) / len(ho) < 0.9


def test_rule_rate_limit():
    st, sc = generate(0)
    s = next(x for x in sc if x["action"]["name"] == "shutdown_link")
    lo = RuleGateway().score(s, {"recent_destructive": 0})[0]
    hi = RuleGateway().score(s, {"recent_destructive": 5})[0]
    assert hi > lo
