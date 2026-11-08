"""M5 check: does the AI concept index cover the course's gold concepts? (eval courses only)"""

from __future__ import annotations

from .course_io import LoadedCourse
from .llm import LLM
from .notebook import Notebook

SCHEMA = {
    "type": "object",
    "properties": {"matches": {"type": "array", "items": {
        "type": "object",
        "properties": {"gold_id": {"type": "string"}, "indexed": {"type": "array", "items": {"type": "string"}}},
        "required": ["gold_id", "indexed"], "additionalProperties": False}}},
    "required": ["matches"], "additionalProperties": False,
}


def gold_concept_coverage(llm: LLM, lc: LoadedCourse, nb: Notebook) -> dict:
    gold = "\n".join(f"{c.id} (lesson {c.lesson}): {c.name}" for c in lc.concepts)
    idx = "\n".join(f"- [{c.lesson_id}] {c.name}" for c in nb.concepts)
    prompt = (f"GOLD CONCEPTS:\n{gold}\n\nINDEXED CONCEPTS:\n{idx}\n\nFor every gold concept, list the indexed "
              "concept names (copied exactly) from the SAME lesson that cover the same idea. Use [] if none.")
    r = llm.call("tagger", prompt, schema=SCHEMA, max_tokens=8000, label="notebook-check")
    got = {m["gold_id"]: m["indexed"] for m in r.data["matches"]}
    names = {c.name for c in nb.concepts}
    covered = [c.id for c in lc.concepts if any(n in names for n in got.get(c.id, []))]
    return {"total": len(lc.concepts), "covered": len(covered), "rate": len(covered) / len(lc.concepts),
            "uncovered": [c.id for c in lc.concepts if c.id not in covered]}
