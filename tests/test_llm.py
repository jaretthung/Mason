import json

import pytest

from mason.llm import LLM, BudgetExceeded, FakeBackend, Ledger, LLMError, Usage, request_key


def test_cost_accounting(config):
    price = config.price("claude-sonnet-5-5")
    u = Usage(input_tokens=1_000_000, output_tokens=100_000, cache_read_tokens=1_000_000)
    assert u.cost(price) == pytest.approx(2.00 + 1.00 + 0.20)


def test_role_sets_model_and_effort(fake_llm):
    llm = fake_llm()
    req = llm.build_request("solver", "hi")
    assert req["model"] == "claude-sonnet-5-5"
    assert req["output_config"]["effort"] == "medium"
    assert req["messages"] == [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]


def test_schema_parses_json(fake_llm):
    llm = fake_llm(lambda req: json.dumps({"answer": "B"}))
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"],
              "additionalProperties": False}
    r = llm.call("solver", "q", schema=schema)
    assert r.data == {"answer": "B"}
    assert llm.backend.calls[0]["output_config"]["format"]["schema"] == schema


def test_invalid_json_raises(fake_llm):
    llm = fake_llm(lambda req: "not json")
    with pytest.raises(LLMError):
        llm.call("solver", "q", schema={"type": "object"})


def test_disk_cache_second_call_is_free(config):
    backend = FakeBackend(lambda req: "pong")
    ledger = Ledger(10, 150, config.state_dir / "spend.json")
    llm = LLM(config=config, backend=backend, ledger=ledger)
    a = llm.call("ping", "say pong")
    b = llm.call("ping", "say pong")
    assert not a.cached and a.cost_usd > 0
    assert b.cached and b.cost_usd == 0 and b.text == "pong"
    assert len(backend.calls) == 1
    assert ledger.run_spend == pytest.approx(a.cost_usd)


def test_cache_key_changes_with_prompt():
    r1 = {"model": "m", "messages": [{"role": "user", "content": "a"}]}
    r2 = {"model": "m", "messages": [{"role": "user", "content": "b"}]}
    assert request_key(r1) != request_key(r2)
    assert request_key(r1) == request_key(dict(reversed(list(r1.items()))))


def test_run_budget_stops_before_overspend(fake_llm):
    llm = fake_llm(lambda req: "x" * 4000, per_run_usd=0.001)
    calls = 0
    with pytest.raises(BudgetExceeded):
        for _ in range(100):
            llm.call("notebook", "y" * 4000)
            calls += 1
    # stopped well before 100 calls; overshoot is at most one call's cost
    assert calls < 100
    last = llm.log[-1].cost_usd
    assert llm.ledger.run_spend < 0.001 + last
    assert len(llm.backend.calls) == calls


def test_monthly_budget_persists(tmp_path, config):
    state = tmp_path / "spend.json"
    l1 = Ledger(100, 1.0, state)
    l1.record(0.6, cached=False)
    l2 = Ledger(100, 1.0, state)  # new process, same month
    l2.check()
    l2.record(0.5, cached=False)
    l3 = Ledger(100, 1.0, state)
    with pytest.raises(BudgetExceeded):
        l3.check()


@pytest.mark.live
def test_live_ping(tmp_path, config):
    llm = LLM.from_config(config)
    r = llm.call("ping", "Reply with exactly the word: pong", max_tokens=2000)
    assert "pong" in r.text.lower()
    assert r.cost_usd > 0
