# Mason v1 — Specification

*Status: draft for founder review (Phase 3). Source of truth for what v1 is. Research behind it: `RESEARCH.md`.*

## 1. What we're building

Mason is an AI student. It attends one course's lessons in order, learns **only** from the materials the teacher
uploads, then takes the course's exams. Because Mason can only use what the materials teach, its results show
**where the materials fall short**: concepts that didn't stick, questions it couldn't support from the lessons, and
the lesson text closest to each failure.

**Goal for v1:** one high school Biology teacher uses Mason on their real course in January 2027.

### The claim v1 makes, and the one it doesn't
- ✅ **Material-gap claim:** "Mason couldn't answer this from your materials. Here's the step it couldn't support
  and the closest lesson text."
- ❌ **No prediction of student mistakes in v1.** Research supports human-like mistakes only weakly (RESEARCH.md
  §2.1). The optional class comparison measures whether this holds. We don't promise it.

## 2. Users and flow

One teacher, no accounts. The founder may operate the app on the teacher's behalf.

1. **Create course:** title, grade (9–12), subject (Biology).
2. **Upload lessons in order.** Each lesson can hold slides, notes/handouts, readings and video transcripts.
3. **Review prerequisites:** Mason drafts a short "what students already know" list. The teacher edits and approves.
4. **Upload exam(s):** questions plus answer keys or rubrics.
5. **Review tags:** Mason proposes the concepts and lessons for each question. The teacher confirms or edits.
6. **Run:** Mason attends lessons 1..k (k = the lesson the exam follows) and takes the exam.
7. **Read report** (§5).
8. *(Optional)* upload class results (% correct per question) and see the comparison.

## 3. Decisions (from the Phase 2 interview)

| Area | Decision |
|---|---|
| Subject / level | High school Biology (grades 9–12), concept-heavy. A specific pilot course is lined up |
| Leakage approach | **Notebook + cite-every-step + independent checker**, with lesson gating enforced in code (RESEARCH.md §5). Strict-prompting baseline kept for comparison |
| Material formats | Slides (.pptx incl. speaker notes; PDF exports), notes/handouts (PDF, DOCX, TXT/MD), video **transcripts** (VTT/SRT/TXT). Images in slides are extracted for diagram questions |
| Slide-only lessons | Gaps in a lesson whose source is only slides with no speaker notes are labelled **"may be covered verbally"** |
| Videos | First choice: pull existing captions automatically (see open question Q1). Fallback: teacher exports captions. Videos with no transcript are listed as **"not seen by Mason"** |
| Question formats | Multiple choice (incl. T/F, matching), short answer, diagram/image, essay. **Build order: multiple choice → short answer → diagram → essay. If time runs short, essays are cut first, then diagrams** |
| Prerequisites | Mason auto-drafts from grade + course; teacher edits/approves. Mason may use only approved prerequisites + covered lessons |
| Question tagging | Mason auto-tags concept + lesson; teacher confirms |
| Grading | Multiple choice: exact match against the key. Short answer / diagram / essay: AI grader against key + rubric. **Gate:** the teacher hand-grades ~30 of Mason's answers once, and the AI grader must agree on **≥ 85%** of them before reports are shown |
| Pass bar (v1 done) | **Leakage ≤ 5%** on not-yet-covered questions (chance-corrected for multiple choice) **AND learning ≥ 80%** on covered questions whose material is marked sufficient. Both together, on the sample course |
| Budget | **≤ $10 per exam run**, **≤ $150 per month** of development API spend. Every run prints its cost, and a configurable hard cap stops runs that exceed it |
| Real student data | **Class averages only** (% correct per question). Upload rejects anything that looks like per-student rows (names, IDs, > 1 row per question). No student PII is stored |
| Course material privacy | School has approved sending the pilot materials to the Claude API. Pilot materials are **never committed** to the repo |
| Test data | Public **OpenStax Biology 2e** (CC BY 4.0) sample course in the repo, with founder-reviewed exams. The pilot course runs from a private local folder |
| Interface | Minimal web app (FastAPI + React) for upload → review → run → report. The CLI does everything too |
| Stack | Python 3.11+, FastAPI, SQLite, React (Vite), Claude API. No vector DB (lesson gating = SQL filter) |

## 4. Leakage rules (the core of the product)

1. **Gating:** when Mason is "at lesson k", data from lessons > k is not loaded into anything Mason can read. This
   is enforced in code and covered by tests.
2. **Notebook:** Mason learns by writing notebook entries (concept, definition, fact, process, example), each with
   an **exact quote** from a source file. Entries whose quote isn't found word for word in the source are discarded.
3. **Answering:** one fresh, stateless call per question. Every reasoning step must cite notebook entry IDs or
   approved prerequisites. "I don't know" is always allowed.
4. **Checking:** a separate checker call judges each step against only its citations. Unsupported steps are
   struck. If the answer depends on a struck step, the attempt is recorded as **blocked** (a non-answer), and the
   struck step becomes a reported gap.
5. **Measured, not assumed:** the evaluation harness (PLAN.md M3, M7) measures leakage and learning on every
   change.

## 5. Teacher report (v1 contents)

1. **Summary:** score, # questions, concepts mastered / shaky / missing, run cost, lesson range attended.
2. **Per-concept table:** concept → lessons that teach it → questions → Mason's result (✅ correct, ⚠️ partial,
   ❌ wrong, 🚫 couldn't support) → status.
3. **Per missed question:**
   - Mason's answer and the grade.
   - The **step Mason couldn't support** (struck by the checker) or the step it got wrong.
   - The **closest lesson text** (quote + file + page/slide), or "no lesson text found for this concept".
   - Flags: *may be covered verbally* (slide-only source), *depends on an untaught lesson* (the question's tag
     points after lesson k).
4. **Not seen by Mason:** files that couldn't be read, videos without transcripts, images without text.
5. *(Optional)* **Class comparison:** Mason vs. class per question, a list of the biggest disagreements, and a
   correlation number, with a caveat that this does not validate predictions of student mistakes.
6. **Trust panel:** the latest leakage and learning numbers for this Mason version, and AI-grader agreement with
   the teacher.

## 6. Out of scope for v1
Learner profiles / students with learning differences · LMS integrations · user accounts / auth · billing · mobile ·
multiple teachers or courses at once · predicting student misconceptions · fine-tuning or unlearning models ·
math-heavy subjects · speech-to-text of raw audio (unless approved, see Q1) · per-student data of any kind.

## 7. Open questions

| # | Question | Current default | Decide by |
|---|---|---|---|
| Q1 | **Video transcripts:** YouTube's official captions API only serves video owners. The unofficial `youtube-transcript-api` library is free but can break or conflict with the terms of service. Paid speech-to-text is a new paid API | Try `youtube-transcript-api` (needs your OK as a new dependency). If that fails, the teacher exports captions. Speech-to-text only with explicit approval | M10 |
| Q2 | **All four formats by January** is tight for one part-time builder | Build in order; essays (M12) are the first cut | Mid-December checkpoint |
| Q3 | **Diagram questions:** slide images may lack labels, and Claude reading images adds cost and new ways to leak | Own leakage probes for image questions; report separately | M11 |
| Q4 | **Hosting** the web app for the teacher | You run it locally and screen-share, or use a cheap private host | M13 |
| Q5 | **Pilot exam timing:** which unit and exam the pilot runs on, and how many lessons it covers | Ask the teacher; assume ~6–10 lessons, one unit test | Before M15 |
| Q6 | **Essay rubric:** what a "gap" means for an essay | Per-rubric-criterion results; an unmet criterion = gap | M12 |
| Q7 | Statistical confidence: 5% leakage needs enough probes to mean anything | ≥ 60 leakage probes in the sample course; report the 95% interval alongside the point estimate | M1 |
