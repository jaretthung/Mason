import json
from pathlib import Path

import pytest

from mason.course_io import load_course
from mason.notebook import IndexedConcept, Notebook, build_entries, build_notebook, cut_passages, index_lesson, verify_entries
from mason.student.notebook_student import NotebookStudent
from mason.student.view import make_view

SAMPLE = Path(__file__).resolve().parent.parent / "courses" / "sample-bio"


@pytest.fixture(scope="module")
def lc():
    return load_course(SAMPLE)


# ------------------------------------------------------------------ notebook

def test_entries_are_verbatim_unique_and_gated(lc):
    v = make_view(lc, "L3")
    es = build_entries(v)
    assert verify_entries(es, v) == []
    assert len({e.id for e in es}) == len(es)
    assert {e.lesson_id for e in es} == {"L1", "L2", "L3"}
    assert all(len(e.text.split()) <= 95 for e in es)


def test_verify_catches_tampered_entry(lc):
    v = make_view(lc, "L1")
    es = build_entries(v)
    es[0].text += " Mitochondria are the powerhouse of the cell."
    assert verify_entries(es, v)


def test_bullets_become_separate_entries():
    p = cut_passages("## Slide 4 — Enzyme specificity\n- Each enzyme fits a specific substrate\n- Induced fit model")
    assert p == [("Slide 4 — Enzyme specificity", "- Each enzyme fits a specific substrate"),
                 ("Slide 4 — Enzyme specificity", "- Induced fit model")]


def test_index_drops_hallucinated_ids(lc, fake_llm):
    v = make_view(lc, "L4")
    l4 = v.lessons[-1]
    es = [e for e in build_entries(v) if e.lesson_id == "L4"]
    llm = fake_llm(lambda req: json.dumps({"concepts": [
        {"name": "Induced fit", "entry_ids": ["L4.15", "L9.99"], "depth": "mentioned_only", "note": "named only"},
        {"name": "Ghost", "entry_ids": ["X1"], "depth": "explained", "note": ""}]}))
    cs = index_lesson(llm, l4, es)
    assert [c.name for c in cs] == ["Induced fit"] and cs[0].entry_ids == ["L4.15"]
    assert "slide deck with no speaker notes" in llm.backend.calls[0]["messages"][0]["content"][0]["text"]


def test_notebook_roundtrip(lc):
    nb = build_notebook(make_view(lc, "L2"))
    nb.concepts.append(IndexedConcept("x", "L1", ["L1.01"], "explained"))
    nb2 = Notebook.from_json(nb.to_json())
    assert len(nb2.entries) == len(nb.entries) and nb2.concepts[0].name == "x"
    assert {e.lesson_id for e in nb2.for_lessons(["L1"]).entries} == {"L1"}


# ------------------------------------------------------------------ Mason (solver + checker)

def scripted(solver: dict, checker: dict | None = None):
    def responder(req):
        sys = req["system"][0]["text"] if isinstance(req["system"], list) else req["system"]
        if sys.startswith("You are Mason"):
            return json.dumps(solver)
        assert checker is not None, "checker should not have been called"
        assert "ANSWER KEY" not in req["messages"][0]["content"][0]["text"]
        return json.dumps(checker)
    return responder


def test_abstains_without_calling_checker(lc, fake_llm):
    llm = fake_llm(scripted({"steps": [], "answer": "I don't know", "missing": "what induced fit means"}))
    a = NotebookStudent(llm).answer(make_view(lc, "L6"), lc.question("Q28"))
    assert a.status == "abstained" and a.notes == "what induced fit means"
    assert len(llm.backend.calls) == 1


def test_supported_answer_is_answered(lc, fake_llm):
    llm = fake_llm(scripted(
        {"steps": [{"claim": "Glycolysis takes place in the cytoplasm", "cites": ["L5.03"]}], "answer": "A", "missing": ""},
        {"steps": [{"index": 1, "verdict": "supported", "reason": "stated"}], "answer_follows": True, "reason": ""}))
    a = NotebookStudent(llm).answer(make_view(lc, "L6"), lc.question("Q31"))
    assert a.status == "answered" and a.answer == "A" and a.steps[0]["verdict"] == "supported"


def test_checker_strike_blocks_answer(lc, fake_llm):
    llm = fake_llm(scripted(
        {"steps": [{"claim": "The active site changes shape around the substrate", "cites": ["L4.15"]}],
         "answer": "The active site reshapes to fit the substrate.", "missing": ""},
        {"steps": [{"index": 1, "verdict": "unsupported", "reason": "slide only names the model"}],
         "answer_follows": True, "reason": ""}))
    a = NotebookStudent(llm).answer(make_view(lc, "L6"), lc.question("Q28"))
    assert a.status == "blocked" and a.answer is None
    assert "S1" in a.notes and a.steps[0]["reason"] == "slide only names the model"


def test_citing_untaught_material_is_struck_without_model(lc, fake_llm):
    """At lesson 3, a citation of L5.03 (not yet attended) or an invented id is struck deterministically."""
    llm = fake_llm(scripted(
        {"steps": [{"claim": "Glycolysis is in the cytoplasm", "cites": ["L5.03"]},
                   {"claim": "So the answer is A", "cites": ["S1"]}], "answer": "A", "missing": ""},
        {"steps": [{"index": 1, "verdict": "supported", "reason": "?"}, {"index": 2, "verdict": "supported", "reason": ""}],
         "answer_follows": True, "reason": ""}))
    a = NotebookStudent(llm).answer(make_view(lc, "L3"), lc.question("Q31"))
    assert a.status == "blocked"
    assert a.steps[0]["verdict"] == "unsupported" and "does not have: L5.03" in a.steps[0]["reason"]
    checker_prompt = llm.backend.calls[1]["messages"][0]["content"][0]["text"]
    assert "NOT AVAILABLE" in checker_prompt


def test_forward_step_reference_is_invalid(lc, fake_llm):
    llm = fake_llm(scripted(
        {"steps": [{"claim": "x", "cites": ["S2"]}, {"claim": "y", "cites": ["L1.01"]}], "answer": "A", "missing": ""},
        {"steps": [{"index": 1, "verdict": "supported", "reason": ""}, {"index": 2, "verdict": "supported", "reason": ""}],
         "answer_follows": True, "reason": ""}))
    a = NotebookStudent(llm).answer(make_view(lc, "L1"), lc.question("Q01"))
    assert a.status == "blocked" and a.steps[0]["verdict"] == "unsupported"


def test_answer_must_follow(lc, fake_llm):
    llm = fake_llm(scripted(
        {"steps": [{"claim": "Cells come from cells", "cites": ["L1.08"]}], "answer": "B", "missing": ""},
        {"steps": [{"index": 1, "verdict": "supported", "reason": ""}], "answer_follows": False, "reason": "picks B"}))
    a = NotebookStudent(llm).answer(make_view(lc, "L1"), lc.question("Q01"))
    assert a.status == "blocked" and "does not follow" in a.notes


def test_solver_prompt_is_gated_and_cached(lc, fake_llm):
    llm = fake_llm(scripted({"steps": [], "answer": "I don't know", "missing": ""}))
    st = NotebookStudent(llm)
    for qid in ["Q31", "Q38", "B10"]:
        st.answer(make_view(lc, "L3"), lc.question(qid))
    sent = json.dumps(llm.backend.calls)
    for marker in ["L4.", "L5.", "L6.", "Glycolysis takes place", "thylakoid", "adenosine triphosphate"]:
        assert marker not in sent, marker
    sys_blocks = llm.backend.calls[0]["system"]
    assert sys_blocks[-1]["cache_control"] == {"type": "ephemeral"}
    # identical notebook prefix for every question at the same lesson -> cache hits
    assert len({json.dumps(c["system"]) for c in llm.backend.calls}) == 1


def test_ablation_removes_lesson_from_notebook(lc, fake_llm):
    llm = fake_llm(scripted({"steps": [], "answer": "I don't know", "missing": ""}))
    NotebookStudent(llm).answer(make_view(lc, "L6", exclude=("L5",)), lc.question("Q31"))
    sent = json.dumps(llm.backend.calls)
    assert "[L5." not in sent and "[L6." in sent


# ------------------------------------------------------------------ live checks (cost money)

@pytest.mark.live
def test_live_m5_concept_coverage(lc):
    from mason.llm import LLM
    from mason.notebook_check import gold_concept_coverage
    llm = LLM.from_config()
    nb = build_notebook(make_view(lc, "L6"), llm)
    assert gold_concept_coverage(llm, lc, nb)["rate"] >= 0.9
    l4 = {c.name.lower(): c.depth for c in nb.concepts if c.lesson_id == "L4"}
    assert any("induced fit" in n and d == "mentioned_only" for n, d in l4.items())


@pytest.mark.live
def test_live_m6_pass_bar(lc):
    from mason.evals.harness import evaluate, llm_grader
    from mason.llm import LLM
    llm = LLM.from_config()
    rep = evaluate(lc, NotebookStudent(llm), llm_grader(llm), tests=("T1", "T2"))
    assert rep["passed"], [(r["test"], r["value"]) for r in rep["results"]]
