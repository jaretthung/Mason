"""`mason` command-line entry point."""

from __future__ import annotations

import argparse
import sys

from .config import load_config


def cmd_ping(args) -> int:
    from .llm import LLM

    llm = LLM.from_config()
    for i in range(2):
        r = llm.call("ping", "Reply with exactly the word: pong", max_tokens=2000, label="ping")
        tag = "cached, $0.00" if r.cached else f"${r.cost_usd:.5f}"
        print(f"call {i + 1}: {r.text.strip()!r} · {r.model} · in={r.usage.input_tokens} "
              f"out={r.usage.output_tokens} · {tag}")
    print(llm.ledger.summary())
    return 0


def cmd_spend(args) -> int:
    from .llm import Ledger

    cfg = load_config()
    ledger = Ledger(cfg.per_run_usd, cfg.per_month_usd, cfg.state_dir / "spend.json")
    print(f"This month: ${ledger.month_spend():.2f} of ${cfg.per_month_usd:.2f}")
    return 0


def cmd_validate(args) -> int:
    import json

    from .course_io import course_stats, validate_course

    lc, problems = validate_course(args.course_dir)
    stats = course_stats(lc)
    print(json.dumps(stats, indent=2))
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"\nOK: {lc.course.title}")
    return 0


def cmd_grade_calibrate(args) -> int:
    from .calibrate import AGREEMENT_BAR, run_calibration
    from .llm import LLM

    llm = LLM.from_config()
    res = run_calibration(llm, args.course_dir, args.labels)
    for d in res.disagreements:
        print(f"- {d['question']}: human={d['human']} ai={d['ai']} :: {d['answer'][:80]!r}\n    {d['rationale']}")
    print(f"\nAgreement: {res.agree}/{res.n} = {res.agreement:.0%} (bar {AGREEMENT_BAR:.0%}) -> "
          f"{'PASS' if res.passed else 'FAIL'}")
    print(llm.ledger.summary())
    return 0 if res.passed else 1


def cmd_eval(args) -> int:
    from .course_io import load_course
    from .evals.harness import evaluate, exact_key_grader, llm_grader, save_report, summarize
    from .student.base import GatedOracleStudent, OmniscientStudent

    lc = load_course(args.course_dir)
    llm = None
    if args.student == "omniscient":
        student, grader = OmniscientStudent(), exact_key_grader
    elif args.student == "oracle":
        student, grader = GatedOracleStudent(), exact_key_grader
    else:
        from .llm import LLM
        llm = LLM.from_config()
        grader = llm_grader(llm)
        if args.student == "baseline":
            from .student.baseline import BaselineStudent
            student = BaselineStudent(llm)
        else:
            from .student.notebook_student import NotebookStudent  # M6
            student = NotebookStudent(llm, lc)
    tests = tuple(t.strip().upper() for t in args.tests.split(","))
    ablate = args.ablate.split(",") if args.ablate else None
    report = evaluate(lc, student, grader, tests=tests, ablate=ablate, workers=args.workers,
                      progress=lambda m: print("  running", m, flush=True))
    if llm:
        report["cost"] = llm.ledger.summary()
    path = save_report(report)
    print(summarize(report))
    if llm:
        print(llm.ledger.summary())
    print(f"Full results: {path}")
    return 0 if report["passed"] else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mason", description="Mason, the AI student.")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("ping", help="Make one live Claude call (then repeat it from cache) to check setup and costs")
    sub.add_parser("spend", help="Show API spend this month")
    v = sub.add_parser("validate", help="Check a course folder (schema, files, tags, variants) and print stats")
    v.add_argument("course_dir")
    g = sub.add_parser("grade-calibrate", help="Check AI grader agreement with human labels (live API calls)")
    g.add_argument("course_dir")
    g.add_argument("--labels", default="calibration/grader_labels.yaml")
    e = sub.add_parser("eval", help="Run the evaluation harness (leakage T1, learning T2, ablation T3)")
    e.add_argument("course_dir")
    e.add_argument("--student", default="notebook", choices=["notebook", "baseline", "omniscient", "oracle"],
                   help="omniscient/oracle are offline fake students that test the harness itself")
    e.add_argument("--tests", default="T1,T2,T3")
    e.add_argument("--ablate", default="", help="comma-separated lesson ids for T3 (default: all)")
    e.add_argument("--workers", type=int, default=4)
    return p


COMMANDS = {"ping": cmd_ping, "spend": cmd_spend, "validate": cmd_validate,
            "grade-calibrate": cmd_grade_calibrate, "eval": cmd_eval}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
