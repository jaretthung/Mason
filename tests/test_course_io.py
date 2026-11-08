from pathlib import Path

import pytest
from pydantic import ValidationError

from mason.course_io import Question, course_stats, load_course, validate_course

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "courses" / "sample-bio"
INVENTED = ROOT / "courses" / "invented-course"


@pytest.mark.parametrize("course", [SAMPLE, INVENTED])
def test_course_validates(course):
    _, problems = validate_course(course)
    assert problems == []


def test_sample_meets_m1_requirements():
    lc = load_course(SAMPLE)
    s = course_stats(lc)
    assert s["lessons"] == 6
    assert s["slide_only_lessons"] == ["L4"]
    assert s["leakage_probe_instances"] >= 60          # PLAN M1 / SPEC Q7
    assert s["covered_sufficient"] >= 35
    assert s["defects"] >= 6 and s["counterfactuals"] >= 6
    assert s["missing_gold_tags"] == [] and s["missing_sufficient"] == []
    assert set(s["by_type"]) == {"mc", "short"}


def test_every_concept_is_tested():
    lc = load_course(SAMPLE)
    tested = {c for q in lc.exam.questions for c in q.tags.concepts}
    untested = {c.id for c in lc.concepts} - tested
    # a few concepts may stay untested, but most must have a question
    assert len(untested) <= 6, untested


def test_question_tag_lessons_match_concept_lessons():
    lc = load_course(SAMPLE)
    concept_lesson = {c.id: c.lesson for c in lc.concepts}
    for q in lc.exam.questions:
        for cid in q.tags.concepts:
            assert concept_lesson[cid] in q.tags.lessons, (q.id, cid)


def test_prereqs_do_not_name_taught_concepts():
    lc = load_course(SAMPLE)
    text = " ".join(lc.prerequisites).lower()
    for term in ["mitochondri", "osmosis", "glycolysis", "chlorophyll", "enzyme", "atp", "ribosome",
                 "photosynthesis", "cell theory", "nucleus", "membrane"]:
        assert term not in text, term


def test_invalid_questions_rejected():
    with pytest.raises(ValidationError):
        Question(id="x", type="mc", stem="?", choices={"A": "a", "B": "b"}, answer="C")
    with pytest.raises(ValidationError):
        Question(id="x", type="short", stem="?", answer="a")  # no rubric
    with pytest.raises(ValidationError):
        Question(id="x", type="mc", stem="?", choices={"A": "a", "B": "b"}, answer="A",
                 tags={"lessons": ["L1"]}, probe="beyond")


def test_validator_catches_bad_defect(tmp_path):
    import shutil
    dst = tmp_path / "c"
    shutil.copytree(SAMPLE, dst)
    p = dst / "variants" / "defects.yaml"
    p.write_text(p.read_text().replace("Glycolysis takes place in the cytoplasm", "Glycolysis happens in the cytoplasm"))
    _, problems = validate_course(dst)
    assert any("D2" in x for x in problems)
