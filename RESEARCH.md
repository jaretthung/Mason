# Mason — Phase 1 Research: Stopping Knowledge Leakage

*Date: 2026-11-07. Status: Phase 1 deliverable, awaiting review. No code.*

> **How the sources were checked:** this session could not open arxiv.org directly. Paper claims come from abstracts,
> proceedings pages and search-indexed summaries. Treat the specific numbers below as "reported by the paper's
> abstract or a summary of it". Read the full text of the 3–4 papers we lean on hardest before quoting them externally.

---

## 1. The problem, from first principles

Mason's claim is: **"If Mason got it right, the course material taught it."** That claim holds only if every
correct answer *depends on* the material. So **leakage** has a precise definition:

> **Leakage = a correct (or partly correct) answer that does not depend on the course material Mason has seen so far.**

That definition gives a test: remove the material, and a correct answer that survives is a leak. (Section 4 builds
the evaluation harness around this.)

Leakage comes in four forms. They have different causes and need different defenses:

| # | Form | Example | Why it hurts Mason |
|---|------|---------|--------------------|
| L1 | **Recall**: answering an untaught topic from memory | Lesson 3 hasn't covered osmosis, but Mason defines it perfectly | Inflates scores on untaught topics |
| L2 | **Gap-filling**: the lesson is half-explained and the model silently fills in the rest | The slide skips *why* you flip the inequality sign; Mason does it anyway | **Most dangerous.** It hides exactly the bad explanations the teacher report is supposed to find |
| L3 | **Override**: the course uses a convention or simplification and the model "corrects" it | The course defines g = 10 m/s²; Mason uses 9.8 | Mason stops reflecting what *this* course teaches |
| L4 | **Skill leakage**: a procedure was never taught, but general reasoning solves it anyway | Solving a quadratic by inspection before factoring is taught | Hardest to stop. Reasoning ability *is* prior knowledge |

There is also knowledge Mason **should** have: reading, arithmetic, and the prerequisites a real student brings
into the course. A real 10th grader in chemistry already knows algebra. So the target is not "Mason knows nothing".
The target is **"Mason knows the declared prerequisites plus the material covered so far, and nothing else."**
The prerequisite list has to be an explicit input, one item for each course.

Two consequences shape everything below:

1. **Leakage cannot be driven to zero. It can be bounded and measured.** No method found in the research fully
   removes what a model already knows. The product therefore needs a leakage *score* and a pass threshold, not a
   promise.
2. **Which subject you pick matters more than any technique.** In fact-heavy courses (biology, history,
   economics, a niche elective), the course-specific knowledge carries the answer, so L1–L3 dominate, and those
   are the controllable forms. In skill-heavy courses (math, physics problem-solving), L4 dominates, and L4 is the
   hardest to control. This is a Phase 2 question.

---

## 2. What the research says

### 2.1 LLM-simulated students: how well do they match real students?

| Study | What they did | Finding relevant to Mason |
|---|---|---|
| **Generative Students** (Lu & Wang, L@S 2024) [1] | GPT-4 given knowledge-component profiles (each concept mastered, confused, or unknown); 45 simulated students answered 20 multiple-choice questions | Simulated vs real per-item responses correlated at **r = 0.72**. Asking the model to *predict what a student with this profile would answer* worked better than asking it to *be* the student. An instructor used the results to improve questions. Closest prior work to Mason, but small (one topic, multiple choice only) |
| **Can LLMs simulate real students' abilities?** (Srivatsa, Maurya & Kochmar, BEA 2025) [2] | 11 LLMs placed on the same IRT ability scale as real students, using 489 NAEP items (math and reading, grades 4/8/12) | Strong models **beat the average student at every grade**. Grade-level prompts move scores, but **no model + prompt combination matched students across subjects and grades**. Weaker models match "only by accident" |
| **Do LLMs make mistakes like students?** (Liu, Sonkar & Baraniuk, 2025) [3] | Compared LLM wrong-answer choices with the distractors real students picked | Only **moderate** alignment (**r = 0.28–0.37**). When wrong, models pick students' most common wrong answer 51–59% of the time. Small models align about as well as large ones |
| **The Imperfect Learner** (Liu et al., 2025) [4] | Simulated students with a hierarchical, structured memory vs plain prompting (GPT-4o) | Without a memory mechanism, simulated grade-1 students scored **179% of grade-level expectations**. With structured memory they stayed within curriculum standards (77–92%). **Explicitly bounded knowledge state > persona prompt** |
| **Towards Valid Student Simulation** (Yuan et al., 2026) [5] | Theory paper (no experiments) | Names the **"competence paradox"**: capable LLMs asked to act partly knowledgeable produce unrealistic errors. Proposes an *Epistemic State Specification* that defines what the simulated learner can access, so simulation becomes a constrained generation problem. This matches Mason's design |
| **Too Smart for Its Own Good? Competence leakage** (NeurIPS 2026) [6] | Measured simulators drifting outside their assigned knowledge state | Leakage is mostly **over-competence**. **Multi-turn conversations leak more than single questions.** Stronger reasoning helps single-turn fidelity but leaks more across turns. *Design implication: answer each exam question in a fresh, stateless call* |
| **Simulated Students in Tutoring Dialogues: Substance or Illusion?** (Scarlatos et al., ACL 2026) [7] | Real middle-school math tutoring dialogues | **Prompt-only simulation performs poorly.** Fine-tuning plus preference optimization is much better but "still limited" |
| **StudentSim** (Microsoft/UIUC, 2026) [8] | LoRA fine-tuning of a 4B model on pooled real-student records, then per-student adaptation | Beats GPT-5.4 at matching individual students. **But it needs real student response data**, which Mason v1 won't have |
| **LLM cognitive models with misconceptions** (Sonkar et al., 2024) [9] | Fine-tuned Llama on algebra solutions containing known misconceptions | Models learn to reproduce specific misconceptions, but this **damages correct solving** unless the mix of correct to wrong examples is tuned carefully |
| **SimStudent** (Matsuda, Koedinger et al., 2007–2015) [10] | Pre-LLM simulated learner that learns *only* from demonstrations | Explicitly proposed as a **"crash test" for instruction**. That is Mason's exact idea, 15+ years earlier. It worked because the learner genuinely started blank, which only held for narrow procedural domains |

**What this means for Mason:**

- "Act like a student who hasn't learned X" **does not work** with prompting alone [2][4][5][6][7]. The model's
  knowledge has to be limited by *architecture* (what it is allowed to see and use), not by *instruction*.
- Evidence that LLM *mistakes* resemble human mistakes is **weak to moderate** [1][3][7][9]. Mason's core claim,
  "it can't solve it, so the lesson didn't explain it", is about whether the *material is sufficient*, and that is
  well defined and testable. The secondary claim, "if Mason makes this mistake, real students will too", is **not
  yet supported** by the literature. In v1, test it with the optional real-class comparison and don't promise it.
  (Phase 2 question.)

### 2.2 Making an LLM answer only from provided material

| Approach | Evidence | Verdict |
|---|---|---|
| **Strict context-only prompting** ("answer only from the passages") | Context-faithful prompting [11] showed that *opinion-based* framing ("According to the notes…") and *counterfactual demonstrations* improve faithfulness when context conflicts with memory. But the **Sufficient Context** paper [12] found that Gemini, GPT and Claude, given *insufficient* context, still answered **correctly 35–62% of the time** (i.e., from memory) and often hallucinated instead of abstaining. FaithfulRAG and related 2025 work [13] confirm that models blend retrieved text with their own knowledge, worst when the two conflict | Necessary, but **not sufficient on its own**. Mainly helps with L3 (override). L1, L2 and L4 get through |
| **Abstention / "say I don't know"** | Abstention survey [14]: training or tuning for abstention helps; prompting alone helps a little. The selective-generation method in [12] improved precision 2–10% | Useful as an output channel, but **unreliable as a gate**. Models rarely abstain on their own |
| **Lesson-by-lesson context limits** (only lessons ≤ k exist) | TimeChara [15] (role-play at a point in a story's timeline): even GPT-4o leaked "future" knowledge, and **naive RAG did worst**, so indiscriminately adding context hurts. LLMs struggle to keep a consistent timeline when told to [16] | **Enforce it in code, never by instruction.** Lessons after k must not exist in the data Mason can reach. This is easy and fully reliable for *material*. It does nothing about the model's own memory |
| **Small or weaker models** | NAEP study [2]: weak models match students only by accident. Small models still carry broad pretraining knowledge [3], and they are worse at *reading* the material, which makes Mason fail for the wrong reason | **Rejected.** It lowers competence everywhere instead of removing specific knowledge, and it can't separate "lesson unclear" from "model too weak" |
| **Unlearning** (erasing topics from model weights) | TOFU [17]: no baseline method effectively unlearned. Relearning attacks [18]: small related fine-tunes bring "unlearned" knowledge back, across WMDP, TOFU and Who's-Harry-Potter | **Rejected.** Doesn't work reliably. Needs open-weights models, GPUs and per-course runs |
| **Fine-tuning a student model** | Helps realism *when you have real student data* [7][8]. Teaching a model new facts by fine-tuning is unreliable, and per-course training is heavy for one maintainer | **Not for v1.** Revisit in v2 if teachers upload real responses |
| **Training from scratch on only the course** | "Chronologically consistent" LLMs [16] train only on text up to a date. That takes a whole corpus. One course's text cannot teach a model to read | **Impossible** for this data size |
| **Term masking / renaming** | In finance, masking company names reduces look-ahead bias, but it destroys information and doesn't fully stop highly capable models [16] | **Not a defense, but a good *measuring tool*** (see harness test T5) |
| **Grounded "notebook" + cite-every-step + independent checker** | Learning from a provided textbook in context *does* work for truly unseen material: MTOB [19] (LLM learning the Kalamang language from one grammar book, close to human-learner scores). Structured, bounded memory gives grade-appropriate behavior [4][5]. Attribution research [20][21] provides the check "is this claim supported by this source?", though automatic checkers are imperfect and miss paraphrased unsupported claims [21]. The Claude API has native **Citations**, which return exact quoted spans from provided documents | **Most promising.** It turns leakage from a behavior request into a **checked, logged rule**. Details below |

---

## 3. The three best approaches compared

### A. Strict context-only prompting (the baseline)
Per question: give the model the material from lessons 1..k (whole or retrieved chunks), a strict "answer only from
these notes; otherwise say NOT IN NOTES" instruction, opinion-based framing [11], and a few counterfactual
examples. One call per question, plus grading.

### B. Notebook + cite-every-step + independent checker (recommended)
Separate *learning* from *answering*, and check the answering step.

1. **Attend (once per lesson):** an extractor turns each lesson into **notebook entries**: concepts, definitions,
   rules and procedures, worked examples. Each entry carries the **exact quote** it came from (Citations API) and
   its lesson number. Entries without a valid quote are dropped. The teacher's prerequisite list is stored as a
   separate, explicit "prior knowledge" notebook.
2. **Answer (each question, a fresh stateless call, per [6]):** a solver sees only notebook entries from lessons
   ≤ k (gated in code) and must write the solution as **numbered steps, each citing notebook entry IDs or a
   prerequisite**. It may answer "I don't know" at any step.
3. **Audit (separate call, separate prompt, no access to the question's answer key):** a checker judges each step
   only against its cited entries: *supported / not supported / uses an untaught concept*. Any unsupported step is
   **struck**. If the final answer depends on a struck step, the result becomes "Mason couldn't do this"
   (recorded as *leak blocked*).
4. **Grade:** compare with the answer key. For free-response, grade with a rubric. Each result is linked to the
   concepts and lessons whose entries were cited.

Why this fits the product: **the struck step is the teacher report.** "Mason needed a step it couldn't support
from Lesson 4 at this point" points straight at the gap in the explanation (L2). Every answer comes with a trace
of exactly which lesson material it used.

Known weaknesses:
- The checker is itself an LLM and can wave through a fluent paraphrase [21]. Mitigation: measure its error rate
  in the harness (T3/T4) and calibrate it with planted leaks.
- Skill steps ("simplify the expression") are harder to judge as supported than fact steps. Mitigation: make
  procedures notebook entries in their own right, and list general skills explicitly as prerequisites.
- Extraction can misread a lesson. In the product that is partly a *feature* ("Mason misread slide 12"). The
  quote requirement keeps extraction honest.

### C. Fine-tuned / unlearned open-weights student model
LoRA-train an open 4–8B model per course, or unlearn topics, and run it locally. Included for completeness. The
research above says it's the weakest option for v1.

### Comparison

| | **A. Strict prompting** | **B. Notebook + checker** | **C. Fine-tune / unlearn** |
|---|---|---|---|
| Stops L1 recall | Partly. Models still answer 35–62% of insufficient-context questions [12] | **Yes, mostly.** An uncited fact gets struck | Partly. Unlearned knowledge comes back [18] |
| Stops L2 gap-filling | **Poorly.** Invisible | **Best.** The gap shows up as a struck step | Poorly |
| Stops L3 override | Moderately [11] | Well. The checker compares against the course's own wording | Unclear |
| Stops L4 skill leakage | No | Partly. Depends on procedures being entries | Partly |
| Explains *why* Mason failed | No | **Yes, step by step** | No |
| Est. API cost per 30-question exam* | **≈ $1–2** | **≈ $3–6** (≈ $2–3 with Batch API) | Pennies to run, plus GPU-hours per course to train |
| Build effort (one part-time founder) | ~1 week | ~3–5 weeks | Months. Needs ML ops and GPUs |
| Maintainability | Very simple | Simple: plain Python + SQLite, 3–4 prompts | Hard |

\*Assumptions: course ≈ 12 lessons ≈ 100k tokens of material; per question ≈ 10k tokens input, ≈ 3k output.
A uses Claude Sonnet 5.5 ($2 / $10 per M input/output tokens). B uses Sonnet 5.5 as solver and checker, plus a
one-time notebook build per course on Claude Opus 5.5 ($4 / $20) ≈ $1–2 per course. Batch API is 50% off. Cached
prompt reads are much cheaper than fresh input. Prices are from Anthropic's model table as of Oct 2026; verify on
the pricing page before budgeting. **The evaluation harness costs more than a single exam** because it runs many
ablation variants: expect roughly $20–100 per full harness run on a sample course, less with batching and Haiku
for cheap probes.

---

## 4. How we'd measure whether it works (the Phase 4 harness)

Each test applies the leakage definition from Section 1: **does the answer depend on the material?**

| Test | How | Metric | Catches |
|---|---|---|---|
| **T1. Not-yet-covered** (the leakage test you specified) | After lesson k, ask questions whose concepts are taught in lessons > k. Prefer free-response: multiple choice has a 25% guessing floor | **Leak rate** = % answered correctly (above chance for multiple choice). Target set in Phase 2 (e.g., ≤ 5–10%) | L1, L4 |
| **T2. Covered** (the learning test you specified) | Questions on taught concepts where a human confirmed the material is sufficient | **Learning accuracy** (e.g., ≥ 80–90%) | Over-blocking: Mason too timid |
| **T3. Lesson ablation** | Re-run the exam with one lesson removed. Questions that depend on it should drop to near chance | **Dependence gap** per lesson | L1, L2. This is the core causal test |
| **T4. Broken-explanation** | Delete one key step from a lesson's explanation (planted defect). Dependent questions should fail *and* the report should point at that lesson | **Defect detection rate** | L2. **Directly tests the product promise** |
| **T5. Counterfactual / renamed course** | (a) Change a fact or convention in the material (g = 10, a made-up definition) and check that Mason follows the course. (b) Rename key terms consistently (masking) and compare accuracy | **Course-adherence rate**; masked-vs-unmasked accuracy gap = leakage estimate | L3, residual L1 |
| **T6. Invented mini-course** (control) | A short course on something that can't be in pretraining (invented game rules, fictional chemistry), MTOB-style [19] | Learning accuracy where leakage is impossible | Shows learning is real, not recall |
| **T7. Real-class comparison** (optional) | Teacher uploads % correct per question | Pearson / Spearman r between Mason's and the class's per-item difficulty. Literature reference points: r ≈ 0.72 [1] (best case, multiple choice); distractor alignment r ≈ 0.3 [3] | The human-likeness claim |

Each test runs on every candidate approach, so A serves as the measured baseline for B. Each test is
**single-turn and stateless** to avoid multi-turn drift [6].

---

## 5. Recommendation

**Build Approach B (notebook + cite-every-step + independent checker), with lesson gating enforced in code, and
use Approach A as the harness baseline.**

Reasoning:
1. **Constraints that work are structural, not instructional.** Every study that tried "please act like you don't
   know" failed [2][4][5][6][7]. B limits what the model *can use*, and it *checks* compliance on every answer.
2. **It aims at the leak that destroys the product (L2).** Strict prompting hides gap-filling. B exposes it as a
   struck step, and that step is the teacher-report output.
3. **It is auditable.** Each claim in the teacher report traces back to quoted lesson text. Teachers can verify
   it, and so can we when debugging.
4. **It fits the stack and the team.** FastAPI + SQLite + React + Claude API is the right choice. A ~12-lesson
   course fits in context, so **no vector database is needed** in v1: lesson gating is a `WHERE lesson <= k`
   query. Everything is Python and a few prompts. No GPUs.
5. **It degrades honestly.** When the checker is unsure, Mason says "I couldn't do this", which is the
   conservative failure for a tool that is meant to find gaps.

What I'm **not** recommending, and why: unlearning or fine-tuning (doesn't hold [17][18], needs data and GPUs
Mason doesn't have), weak models (confound "unclear lesson" with "weak model" [2]), and a persona prompt alone
(the most-refuted approach in the literature).

### Open risks to carry into Phase 2
- **Subject choice** determines whether L4 dominates. Fact- and concept-heavy courses are much safer for v1 than
  math problem-solving.
- **Prerequisites must be declared.** Who writes the "what a student already knows" list, and how detailed is it?
- **Human-likeness of mistakes is unproven.** Should v1 market only "material-sufficiency" findings?
- **Checker reliability** must be measured, not assumed [21].
- **Question formats:** multiple choice is cheap to grade but has a guessing floor. Free-response needs rubric
  grading (LLM-graded, so also validated).

---

## Sources

1. Lu, X. & Wang, X. (2024). *Generative Students: Using LLM-Simulated Student Profiles to Support Question Item Evaluation.* ACM L@S '24. https://arxiv.org/abs/2405.11591
2. Srivatsa, K.V.A., Maurya, K.K. & Kochmar, E. (2025). *Can LLMs Reliably Simulate Real Students' Abilities in Mathematics and Reading Comprehension?* BEA @ ACL 2025. https://aclanthology.org/2025.bea-1.75 · https://arxiv.org/abs/2507.08232
3. Liu, N., Sonkar, S. & Baraniuk, R.G. (2025). *Do LLMs Make Mistakes Like Students? Exploring Natural Alignment between Language Models and Human Error Patterns.* https://arxiv.org/abs/2502.15140
4. Liu, Z., Yin, S.X. et al. (2025). *The Imperfect Learner: Incorporating Developmental Trajectories in Memory-based Student Simulation.* https://arxiv.org/abs/2511.05903
5. Yuan, Z. et al. (2026). *Towards Valid Student Simulation with Large Language Models.* https://arxiv.org/abs/2601.05473
6. *Too Smart for Its Own Good? Competence Leakage in Multi-Turn Cognitive Simulation.* NeurIPS 2026. https://neurips.cc/virtual/2026/176564 · https://arxiv.org/abs/2605.12922
7. Scarlatos, A., Lee, J., Woodhead, S. & Lan, A. (2026). *Simulated Students in Tutoring Dialogues: Substance or Illusion?* ACL 2026. https://arxiv.org/abs/2601.04025 · https://aclanthology.org/2026.acl-long.1960.pdf
8. Yang, K., Wang, C. et al. (2026). *StudentSim: Training LLM-based Student Simulators.* https://arxiv.org/abs/2609.01591
9. Sonkar, S., Chen, X., Liu, N., Baraniuk, R.G. & Sachan, M. (2024). *LLM-based Cognitive Models of Students with Misconceptions.* https://arxiv.org/abs/2410.12294
10. Koedinger, K., Matsuda, N., MacLellan, C. & McLaughlin, E. (2015). *Methods for Evaluating Simulated Learners: Examples from SimStudent.* AIED 2015 Workshop. https://ceur-ws.org/Vol-1432/sl_pap6.pdf
11. Zhou, W., Zhang, S., Poon, H. & Chen, M. (2023). *Context-faithful Prompting for Large Language Models.* Findings of EMNLP 2023. https://aclanthology.org/2023.findings-emnlp.968
12. Joren, H., Zhang, J., Ferng, C.-S., Juan, D.-C., Taly, A. & Rashtchian, C. (2025). *Sufficient Context: A New Lens on Retrieval Augmented Generation Systems.* ICLR 2025. https://arxiv.org/abs/2411.06037
13. FaithfulRAG (ACL 2025), https://arxiv.org/abs/2506.08938; Knowledgeable-R1, https://arxiv.org/abs/2506.05154
14. Wen, B. et al. (2025). *Know Your Limits: A Survey of Abstention in Large Language Models.* TACL. https://arxiv.org/abs/2407.18418
15. Ahn, J. et al. (2024). *TimeChara: Evaluating Point-in-Time Character Hallucination of Role-Playing Large Language Models.* Findings of ACL 2024. https://arxiv.org/abs/2405.18027
16. He, S., Lv, L., Manela, A. & Wu, J. (2025). *Chronologically Consistent Large Language Models.* https://arxiv.org/abs/2502.21206 (discusses Glasserman & Lin's entity masking and its limits); Wongchamcharoen & Glasserman, *Do LLMs Understand Chronology?* https://arxiv.org/abs/2511.14214
17. Maini, P. et al. (2024). *TOFU: A Task of Fictitious Unlearning for LLMs.* https://arxiv.org/abs/2401.06121
18. Hu, S. et al. (2024). *Jogging the Memory of Unlearned LLMs Through Targeted Relearning Attacks.* https://arxiv.org/abs/2406.13356
19. Tanzer, G. et al. (2024). *A Benchmark for Learning to Translate a New Language from One Grammar Book (MTOB).* ICLR 2024. https://arxiv.org/abs/2309.16575 · critique: Aycock et al., ICLR 2025, https://arxiv.org/abs/2409.19151
20. Rashkin, H. et al. (2023). *Measuring Attribution in Natural Language Generation Models.* Computational Linguistics 49(4). https://aclanthology.org/2023.cl-4.2/
21. *Verify with Caution: The Pitfalls of Relying on Imperfect Factuality Metrics* (2025). https://arxiv.org/abs/2501.14883
22. Anthropic, Claude API: Citations and Message Batches docs, model pricing table (accessed via the Claude API reference, Oct 2026). https://docs.claude.com/en/docs/build-with-claude/citations
