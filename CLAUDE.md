# CLAUDE.md — Mason

Mason is an AI student that learns only from one course's materials (in lesson order) and takes its exams, so a
teacher sees where the materials fall short. Read `SPEC.md` (what), `PLAN.md` (how and milestones), and
`RESEARCH.md` (why).

## Commands (planned; update as they land)
- Install: `pip install -e ".[dev]"` (Python 3.11+)
- Tests (offline, FakeLLM): `python3 -m pytest` · live API tests (cost money): `python3 -m pytest -m live`
- Check API setup + cost: `mason ping` · spend this month: `mason spend`
- Demo end to end: `mason demo`
- Evaluate: `mason eval courses/sample-bio [--approach notebook|baseline] [--all]`
- Validate a course folder: `mason validate <course_dir>`
- Web: `uvicorn api.main:app --reload` and `cd web && npm run dev`

## Structure
`mason/` core package (llm, ingest, notebook, student, grading, report, evals, cli) · `api/` FastAPI ·
`web/` React · `courses/sample-bio`, `courses/invented-course` (in repo) · `courses/private/` (gitignored) ·
`tests/`

## Key decisions (don't change without the founder)
- **Leakage control is structural:** lesson gating is a DB filter (lessons > k never reach a prompt). Each
  question is a fresh, stateless call. Every solver step cites notebook entries or approved prerequisites. A
  separate checker strikes unsupported steps.
- Notebook entries must carry a quote found verbatim in the source; otherwise they are discarded.
- Pass bar: **leak ≤ 5% AND learning ≥ 80%** on `courses/sample-bio`. Run `mason eval` after any change to the
  student, notebook, or prompts.
- All Claude calls go through `mason/llm.py` (cache, cost, budget cap). Budget: ≤ $10/exam, ≤ $150/month dev.
- Report claims material gaps only; it never predicts student misconceptions.
- Real student data: class averages only; reject per-student uploads. Never commit `courses/private/`.
- Ask the founder before adding any paid service, new API, or large dependency.
- Each milestone ends with its check from PLAN.md passing; commit with a clear message after each.
