# Mason v1 — Build Plan

*Status: draft for founder review (Phase 3). What we build is in `SPEC.md`; why is in `RESEARCH.md`.*

## 1. Architecture

```
            ┌──────────── teacher (web app or CLI) ────────────┐
            ▼                                                  ▼
   [ingest] files → SourceDocs          [exam] questions + keys/rubrics
            │  (pdf/docx/pptx/md/vtt)              │
            ▼                                      ▼
   [notebook] per-lesson extraction        [tagging] question → concepts/lessons
     entries + verbatim quotes                     │ (teacher confirms)
            │                                      │
            └──────────► [student] ◄───────────────┘
                 gate: lessons ≤ k only (SQL filter)
                 solver: numbered steps, each cites entries/prereqs
                 checker: strikes unsupported steps → blocked / answer
                            │
                            ▼
                 [grading] MC exact · AI rubric grader
                            │
                            ▼
                 [report] per-concept · missed Qs · gaps · not-seen
                            ▲
   [eval harness] T1–T7 (leak, learn, ablation, defects, counterfactual, invented course, class compare)
```

**Principles**
- **Leakage control lives in code, not prompts.** Gating is a DB filter. The checker is a separate call.
  Each question is answered in a fresh, stateless call.
- **One LLM wrapper** (`mason/llm.py`) handles every Claude call: model choice from config, retries, token and
  cost accounting, a hard budget cap, and a **disk cache keyed by request hash**, so re-running unchanged steps
  costs $0 and runs are reproducible.
- **Everything works offline in tests** through a `FakeLLM` that returns scripted responses. API-calling tests are
  marked `@pytest.mark.live` and skipped by default.
- **CLI first, web last.** The web app is a thin layer over the same Python functions.

**Models (configurable in `mason.toml`)**

| Role | Default | Why |
|---|---|---|
| Notebook extraction (once per lesson) | Claude Opus 5.5 | Quality matters most here, and it runs once per course |
| Solver | Claude Sonnet 5.5 | Per-question cost |
| Checker | Claude Sonnet 5.5 (escalate to Opus 5.5 if checker tests fail) | Must be reliable; measured in M6 |
| AI grader | Claude Sonnet 5.5 | Calibrated against human grades |
| Tagging / prerequisite draft | Claude Sonnet 5.5 | Cheap, and the teacher reviews it |

Batch API (50% off) for harness runs. Prompt caching for the gated notebook shared across questions.

**Dependencies (Python):** `anthropic`, `pydantic`, `sqlmodel`, `pyyaml`, `pypdf`, `python-pptx`, `python-docx`,
`jinja2`, `fastapi`, `uvicorn`, `pytest`. **Web:** React + Vite. Anything beyond this list needs the founder's
approval first (e.g. `youtube-transcript-api`, any speech-to-text service).

## 2. Repository layout

```
mason/                 Python package
  config.py            mason.toml loading, model + budget settings
  llm.py               Claude wrapper: cache, cost, budget cap, FakeLLM
  db.py / models.py    SQLite via SQLModel (data model below)
  course_io.py         load/validate course folders (course.yaml, exam.yaml)
  ingest/              pdf, docx, pptx (+speaker notes, images), md/txt, vtt/srt
  notebook.py          per-lesson extraction + quote verification
  prereqs.py           prerequisite draft
  tagging.py           question → concept/lesson tags
  student/             baseline.py (Approach A), notebook_student.py (B: solver + checker)
  grading.py           MC exact, rubric grader
  report/              report builder + HTML template
  evals/               harness, tests T1–T7, metrics, thresholds
  cli.py               `mason ...` commands
api/                   FastAPI app (M13)
web/                   React app (M13)
courses/
  sample-bio/          OpenStax-derived sample (in repo)
  invented-course/     fictional mini-course for T6 (in repo)
  private/             pilot course — gitignored
tests/                 pytest (offline by default)
```

**Course folder format** (what the teacher's upload becomes):
```yaml
# course.yaml
title: Biology — Unit 2 Cells
grade: 10
prerequisites_file: prereqs.yaml     # drafted by Mason, approved by teacher
lessons:
  - id: L1
    title: Cell theory
    files: [L1/slides.pptx, L1/notes.pdf, L1/video.vtt]
# exam.yaml
questions:
  - id: Q1
    type: mc | short | diagram | essay
    stem: "..."
    choices: [...]          # mc only
    answer: "B" | "model answer"
    rubric: [...]           # short/essay/diagram
    image: Q1.png           # diagram only
    tags: {concepts: [...], lessons: [L2]}   # gold tags in sample; confirmed tags in real courses
    sufficient: true        # sample only: material fully explains it (for T2)
    probe: leak             # sample only: marks T1 leakage probes
```

## 3. Data model (SQLite)

| Table | Key fields |
|---|---|
| `course` | id, title, grade, subject |
| `lesson` | id, course_id, **order**, title |
| `source_doc` | id, lesson_id, kind (slides/notes/reading/transcript), path, text, `slide_only` flag, unreadable flag |
| `source_span` | id, source_doc_id, locator (page/slide/timestamp), text |
| `notebook_entry` | id, course_id, **lesson_order**, kind (concept/definition/fact/process/example), title, content, **quote**, source_span_id, verified |
| `concept` | id, course_id, name |
| `entry_concept` | entry_id, concept_id |
| `prerequisite` | id, course_id, text, approved |
| `exam` / `question` | id, course_id, after_lesson_order / id, exam_id, type, stem, choices, answer, rubric, image_path |
| `question_tag` | question_id, concept_id, lesson_order, source (auto/teacher), confirmed |
| `run` | id, course_id, as_of_lesson, approach, config_hash, cost_usd, started/finished, mason_version |
| `attempt` | id, run_id, question_id, steps (JSON: text, citations, verdict), final_answer, status (answered/abstained/blocked), cost_usd |
| `grade` | attempt_id, score (0–1), correct, grader (exact/ai/teacher), rationale |
| `class_result` | question_id, pct_correct, n_students (optional) |
| `eval_result` | id, run_ids, test (T1–T7), metric, value, ci_low, ci_high, passed |

## 4. Metrics (definitions used by the harness)

- **Leak rate (T1):** over leakage probes (questions whose gold lesson > k), the share graded correct.
  Abstained/blocked = not leaked. For multiple-choice probes we use a chance-corrected score:
  `max(0, (acc − 1/n_choices) / (1 − 1/n_choices))`. **Pass: ≤ 5%.** We also report the 95% Wilson interval.
- **Learning (T2):** share correct over covered questions with `sufficient: true`. **Pass: ≥ 80%.**
- **Dependence gap (T3):** for each lesson L, accuracy on L-dependent questions with L present minus with L
  removed. Target: dropping a lesson pulls its questions near the leak floor (gap ≥ 60 points on average).
- **Defect detection (T4):** for planted broken explanations, the share where the dependent question fails **and**
  the report points at the right lesson. Target ≥ 70%.
- **Course adherence (T5):** with a changed fact or convention in the material, the share of answers that follow
  the course, not the outside world. Target ≥ 90%. Plus the masked-vs-unmasked accuracy gap (reported only).
- **Invented-course learning (T6):** learning accuracy on a fictional course. Target ≥ 80% (proves real learning).
- **Checker recall:** on planted unsupported steps, the share struck. Target ≥ 90%.
- **Grader agreement:** AI grade vs. human grade (correct/incorrect, or within one rubric point). Target ≥ 85%.
- **Class correlation (T7):** Spearman ρ between Mason's and the class's per-question difficulty. Reported only,
  no pass bar.

## 5. Milestones

Each milestone ends with a **check**: a command that must pass before the commit. Estimates assume ~12–15
hrs/week. Dates are targets; the mid-December checkpoint decides whether essays (M12) slip.

| # | Milestone | Deliverable | ✅ Check (proves it works) | Target |
|---|---|---|---|---|
| **M0** | Skeleton + LLM wrapper | Package, config, `llm.py` with cache, cost tracking, budget cap, `FakeLLM`; CI-able pytest | `pytest` green (offline). `mason ping` makes 1 live call and prints tokens + cost. A second identical call shows `cached, $0.00`. A test proves the budget cap raises before overspend | Nov 14 |
| **M1** | Sample + invented courses | `courses/sample-bio` (~6 OpenStax lessons as MD, incl. 1 slide-only lesson) with ~40 exam questions (multiple choice + short answer), **≥ 60 leakage probes**, ≥ 6 planted-defect variants, ≥ 6 counterfactual variants. `courses/invented-course` (fictional organism, 3 lessons, 15 questions). Founder reviews the questions | `mason validate courses/sample-bio` passes the schema; a script prints counts per type, per lesson, probes ≥ 60, and every question has gold tags and `sufficient` set | Nov 21 |
| **M2** | Grading | MC exact grader; AI rubric grader for short answers; human-labelled calibration set (~40 answers, founder-labelled on the sample) | `mason grade-calibrate` shows grader agreement **≥ 85%**; unit tests for MC edge cases (T/F, matching, "B" vs "b) …") | Nov 25 |
| **M3** | **Evaluation harness** + baseline A | `mason eval` runs T1, T2, T3 with any "student"; baseline strict-prompting student (Approach A); results saved to `eval_result` + `evals/out/*.json` | **The harness tests itself:** an *omniscient* fake student → leak ≈ 100%; a *gated oracle* fake student → leak = 0% and learning = 100%. Then a live baseline run records real numbers (expected to fail the bar; that's the point) | Dec 2 |
| **M4** | Ingestion | Parsers for md/txt, PDF, DOCX, PPTX (text + speaker notes + images + `slide_only`), VTT/SRT; unreadable files reported | `pytest tests/ingest` on small fixture files: expected text per page/slide, speaker notes captured, slide-only flag set, a corrupt file → "unreadable" not a crash | Dec 6 |
| **M5** | Notebook | Per-lesson extraction with quote verification and concept links | `mason notebook courses/sample-bio`, then check script: **100%** of stored entries' quotes are found verbatim in the source; **≥ 90%** of gold concepts have ≥ 1 entry; no entry is stored under an earlier lesson than its source | Dec 10 |
| **M6** | **Mason student (B)** | Gated solver + checker + blocked/abstain logic; prompt caching; batch mode | Gating unit test (lesson > k can never reach a prompt, checked on the recorded prompt). Checker recall **≥ 90%** on planted unsupported steps. **`mason eval` on sample-bio: leak ≤ 5% AND learning ≥ 80%**, and better than baseline A on leak. Cost per exam ≤ $10 | Dec 17 |
| — | **Mid-Dec checkpoint** | Review numbers with founder; decide essay scope | — | Dec 17 |
| **M7** | Full harness | T4 planted defects, T5 counterfactual + masking, T6 invented course, 3-run variance | `mason eval --all`: T4 ≥ 70%, T5 ≥ 90%, T6 ≥ 80%; results are stable across 3 runs (± 5 pts) | Dec 22 |
| **M8** | Prereqs + tagging | Auto-draft prerequisites; auto-tag questions; teacher-confirm data flow | On sample-bio, auto-tags match gold lesson tags on **≥ 85%** of questions; the prereq draft contains no concept that's taught in the course (check against the concept list) | Dec 27 |
| **M9** | Report + **one command** | `mason demo` = load sample → notebook → exam → grade → HTML report; README | **v1 core done:** `mason demo` runs from a clean checkout with only `ANTHROPIC_API_KEY` set; the report has per-concept results and, for every missed question, a lesson reference or "no lesson text found"; a snapshot test on report structure; total cost printed | Dec 31 |
| **M10** | Video transcripts | VTT/SRT already in M4; YouTube caption pull (**needs approval**, Q1); "not seen" list | Test: a lesson with an unavailable video lists it under "not seen by Mason"; with approval, a live test pulls one public captioned video | Jan 4 |
| **M11** | Diagram questions | Image extraction from slides; image questions to solver/checker; image leakage probes | Sample gets ≥ 8 diagram questions + ≥ 8 image probes; `mason eval --types diagram`: leak ≤ 5%, learning ≥ 75%, grader agreement ≥ 85% | Jan 9 |
| **M12** | Essays *(first to cut)* | Rubric-criterion grading; each unmet criterion is a gap in the report | ≥ 4 essay questions with founder-graded answers; grader agreement within 1 rubric point on ≥ 85% of criteria | Jan 13 |
| **M13** | Web app | FastAPI endpoints over the CLI functions; React pages: course → upload → prereqs → tags → run → report | API tests (`pytest tests/api`) cover each step on sample-bio with FakeLLM; a Playwright smoke test clicks through upload → report | Jan 18 |
| **M14** | Class comparison | Class-averages CSV upload with per-student rejection; comparison section | Tests: a per-student-looking CSV (names / IDs / duplicate question rows) is rejected; a valid CSV produces ρ and a disagreement list | Jan 20 |
| **M15** | Pilot readiness | Run the private pilot course; teacher grades ~30 answers; final README | Teacher-calibration gate: grader agreement **≥ 85%** with the teacher; the pilot report is generated end to end; `git status` shows no pilot files tracked | Jan 27 |

**Definition of done (v1):** M9 + M6 pass bar + README (that's the spec's definition of done), then M10–M15 for
the full pilot.

## 6. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Leak bar not met by M6 | Escalate the checker to Opus 5.5; stricter citation rules; more counterfactual examples. If it's still failing at the mid-Dec checkpoint, revisit with the founder before building the UI |
| Mason too timid (learning < 80%) | Inspect struck steps: these are either real material gaps (fix the sample) or checker over-strictness (tune with T2 failures) |
| Cost over budget | Disk cache, Batch API, prompt caching, Haiku for cheap probes, smaller harness subsets in day-to-day work |
| Schedule (one part-time builder) | Essays first to cut, then diagrams; the web app stays minimal; the CLI demo is the safety net |
| AI grader errors look like lesson gaps | Grader agreement gate before any report is shown (M2, M15) |
