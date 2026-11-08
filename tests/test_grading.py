import json
from pathlib import Path

import pytest

from mason.calibrate import run_calibration
from mason.course_io import Question, load_course
from mason.grading import extract_choice, grade, grade_mc, is_abstention

SAMPLE = Path(__file__).resolve().parent.parent / "courses" / "sample-bio"
CH = {"A": "Cytoplasm", "B": "Mitochondrial matrix", "C": "Inner mitochondrial membrane", "D": "Chloroplast"}
MCQ = Question(id="T", type="mc", stem="Where?", choices=CH, answer="A")


@pytest.mark.parametrize("text,expected", [
    ("A", "A"), ("a", "A"), ("(A)", "A"), ("A)", "A"), ("A. Cytoplasm", "A"), ("B: Mitochondrial matrix", "B"),
    ("The answer is C", "C"), ("Answer: (d)", "D"), ("cytoplasm", "A"), ("It happens in the chloroplast.", "D"),
    ("", None), ("A or B", None), ("B/C", None), ("A and D", None),
])
def test_extract_choice(text, expected):
    assert extract_choice(text, CH) == expected


def test_extract_choice_ambiguous_text():
    # mentions two choices' texts and no leading letter -> ambiguous
    assert extract_choice("either the cytoplasm or the chloroplast", CH) is None


def test_true_false_and_matching_style_choices():
    tf = {"T": "True", "F": "False"}
    assert extract_choice("False", tf) == "F"
    assert extract_choice("T", tf) == "T"


def test_grade_mc_and_counterfactual_key():
    assert grade_mc(MCQ, "A").correct
    assert not grade_mc(MCQ, "B").correct
    assert grade_mc(MCQ, "B", key="B").correct
    assert not grade_mc(MCQ, "I don't know").correct


@pytest.mark.parametrize("text", ["I don't know", "i do not know.", "NOT IN NOTES", "", "  ", "I cannot answer this"])
def test_abstentions(text):
    assert is_abstention(text)


def test_not_abstention():
    assert not is_abstention("I know it is the cytoplasm")


def test_rubric_grading_parses_criteria(fake_llm):
    lc = load_course(SAMPLE)
    q = lc.question("Q17")
    llm = fake_llm(lambda req: json.dumps({"criteria": [
        {"index": 1, "met": True, "reason": "3 Na out"}, {"index": 2, "met": False, "reason": "K wrong"}]}))
    g = grade(llm, q, "3 sodium out and 3 potassium in")
    assert g.score == 0.5 and not g.correct and g.grader == "ai"
    prompt = llm.backend.calls[0]["messages"][0]["content"][0]["text"]
    assert "RUBRIC" in prompt and q.rubric[0] in prompt
    assert "key and rubric win" in llm.backend.calls[0]["system"]


def test_rubric_abstention_makes_no_call(fake_llm):
    lc = load_course(SAMPLE)
    llm = fake_llm(lambda req: pytest.fail("should not call the grader"))
    g = grade(llm, lc.question("Q17"), "I don't know")
    assert not g.correct and len(llm.backend.calls) == 0


def test_counterfactual_written_key(fake_llm):
    lc = load_course(SAMPLE)
    llm = fake_llm(lambda req: json.dumps({"criteria": [{"index": 1, "met": True, "reason": "ok"}]}))
    g = grade(llm, lc.question("Q17"), "2 sodium out, 3 potassium in", key_override="2 Na+ out and 3 K+ in")
    prompt = llm.backend.calls[0]["messages"][0]["content"][0]["text"]
    assert "2 Na+ out and 3 K+ in" in prompt and g.correct


def test_calibration_with_perfect_fake_grader(fake_llm):
    """Wiring check: a grader that echoes the human label scores 100% agreement."""
    import yaml
    items = yaml.safe_load((SAMPLE / "calibration" / "grader_labels.yaml").read_text())["items"]
    label = {it["answer"]: it["correct"] for it in items}

    def responder(req):
        prompt = req["messages"][0]["content"][0]["text"]
        ans = prompt.split("STUDENT ANSWER:\n", 1)[1].split("\n\nFor each rubric", 1)[0]
        n = prompt.count("\n", prompt.index("RUBRIC"), prompt.index("STUDENT ANSWER")) - 2
        return json.dumps({"criteria": [{"index": i, "met": label[ans], "reason": "x"} for i in range(1, n + 1)]})

    res = run_calibration(fake_llm(responder), SAMPLE)
    assert res.n >= 40 and res.agreement == 1.0 and res.passed


def test_calibration_labels_reference_real_short_questions():
    import yaml
    lc = load_course(SAMPLE)
    items = yaml.safe_load((SAMPLE / "calibration" / "grader_labels.yaml").read_text())["items"]
    for it in items:
        assert lc.question(it["question"]).type == "short"


@pytest.mark.live
def test_live_grader_calibration():
    from mason.llm import LLM
    res = run_calibration(LLM.from_config(), SAMPLE)
    assert res.passed, res.disagreements
