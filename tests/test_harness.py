"""The harness must measure what it claims: these fake students have known true leakage/learning."""

import json
from pathlib import Path

import pytest

from mason.course_io import load_course
from mason.evals.harness import evaluate, exact_key_grader, is_untaught_at
from mason.evals.metrics import ItemOutcome, leak_rate, wilson
from mason.student.base import GatedOracleStudent, OmniscientStudent
from mason.student.baseline import BaselineStudent
from mason.student.view import make_view

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "courses" / "sample-bio"


@pytest.fixture(scope="module")
def lc():
    return load_course(SAMPLE)


def by_test(report):
    return {r["test"]: r for r in report["results"]}


def test_omniscient_student_leaks_everything(lc):
    r = by_test(evaluate(lc, OmniscientStudent(), exact_key_grader, workers=1))
    assert r["T1"]["value"] == pytest.approx(1.0)
    assert not r["T1"]["passed"]
    assert r["T2"]["value"] == pytest.approx(1.0)
    assert r["T3"]["value"] == pytest.approx(0.0)  # removing lessons changes nothing: no dependence


def test_gated_oracle_is_perfect(lc):
    rep = evaluate(lc, GatedOracleStudent(), exact_key_grader, workers=1)
    r = by_test(rep)
    assert r["T1"]["value"] == 0.0 and r["T1"]["passed"]
    assert r["T2"]["value"] == 1.0 and r["T2"]["passed"]
    assert r["T3"]["value"] == pytest.approx(1.0) and r["T3"]["passed"]
    assert rep["passed"]


def test_blind_guesser_scores_no_leak_on_mc():
    # 4-choice MC, 25% correct by chance -> chance-corrected leak 0
    items = [ItemOutcome(str(i), "mc", 4, i % 4 == 0) for i in range(100)]
    assert leak_rate(items)["leak"] == pytest.approx(0.0)
    items = [ItemOutcome(str(i), "mc", 4, True) for i in range(10)]
    assert leak_rate(items)["leak"] == pytest.approx(1.0)


def test_wilson_interval():
    lo, hi = wilson(0, 60)
    assert lo == 0.0 and 0.05 < hi < 0.07
    lo, hi = wilson(30, 60)
    assert lo < 0.5 < hi


def test_probe_selection(lc):
    q04 = lc.question("Q31")  # L5
    assert is_untaught_at(lc, q04, "L3") and not is_untaught_at(lc, q04, "L6")
    assert is_untaught_at(lc, lc.question("B10"), "L6")
    assert not is_untaught_at(lc, lc.question("Q01"), "L3")


def test_view_gate_excludes_future_and_ablated_lessons(lc):
    v = make_view(lc, "L3")
    assert v.attended_ids == ["L1", "L2", "L3"]
    v = make_view(lc, "L6", exclude=("L4",))
    assert v.attended_ids == ["L1", "L2", "L3", "L5", "L6"]


def test_baseline_prompts_never_contain_untaught_lessons(lc, fake_llm):
    """GATING: at lesson 3, nothing from lessons 4-6 may appear in any prompt sent to the model."""
    llm = fake_llm(lambda req: json.dumps({"evidence": "", "answer": "I don't know"}))
    student = BaselineStudent(llm)
    view = make_view(lc, "L3")
    for q in lc.exam.questions[:10]:
        student.answer(view, q)
    future_markers = ["Energy and Enzymes", "adenosine triphosphate", "Cellular Respiration", "Glycolysis takes place",
                      "Photosynthesis is the process", "Calvin cycle", "ATP synthase spins"]
    sent = json.dumps(llm.backend.calls)
    for m in future_markers:
        assert m not in sent, m
    assert "Cell Theory and Types of Cells" in sent  # attended lessons are there


def test_ablated_lesson_never_reaches_prompt(lc, fake_llm):
    llm = fake_llm(lambda req: json.dumps({"evidence": "", "answer": "I don't know"}))
    BaselineStudent(llm).answer(make_view(lc, "L6", exclude=("L3",)), lc.question("Q16"))
    sent = json.dumps(llm.backend.calls)
    assert "Plasma Membrane and Transport" not in sent and "Photosynthesis" in sent


def test_baseline_uses_prompt_cache_on_notes(lc, fake_llm):
    llm = fake_llm(lambda req: json.dumps({"evidence": "", "answer": "A"}))
    BaselineStudent(llm).answer(make_view(lc, "L2"), lc.question("Q01"))
    system = llm.backend.calls[0]["system"]
    assert isinstance(system, list) and system[-1]["cache_control"] == {"type": "ephemeral"}


def test_eval_cli_offline(capsys):
    from mason.cli import main
    assert main(["eval", str(SAMPLE), "--student", "oracle", "--workers", "1"]) == 0
    assert main(["eval", str(SAMPLE), "--student", "omniscient", "--workers", "1", "--tests", "T1"]) == 1
    out = capsys.readouterr().out
    assert "OVERALL" in out


@pytest.mark.live
def test_live_baseline_eval(lc):
    from mason.evals.harness import llm_grader
    from mason.llm import LLM
    llm = LLM.from_config()
    rep = evaluate(lc, BaselineStudent(llm), llm_grader(llm), tests=("T1", "T2"))
    assert rep["results"]  # numbers are recorded; the baseline is EXPECTED to miss the leak bar
