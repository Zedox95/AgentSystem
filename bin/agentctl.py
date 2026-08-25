"""agentctl — Kommandozeile der Control Plane.

Damit Skills tatsächlich handeln können statt nur zu beschreiben. Jede
Ausgabe ist JSON, damit sie maschinell auswertbar ist.

    python C:\\AgentSystem\\bin\\agentctl.py <befehl> [optionen]

Befehle:
    task new|state|show|open|readiness
                                    Task Contract, State Machine und Commit-Gate
    lock acquire|release|list       Resource Locks
    run start|finish                Run Ledger
    exp record|promote|deprecate|best|list|stale
    env show|known-good             Environment Fingerprint
    knowledge submit|list|search|approve|reject|review
    context build
    eval list
    metrics record|report
    skill-candidate create|list|report
    supervisor check
    checkpoint show|clear
    policy check                    Policy Guard manuell befragen
    status                          Kompakter Gesamtzustand
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agentsys import (  # noqa: E402
    context, evals, experience, fingerprint, knowledge, ledger, locks,
    policy, routing, skills_pipeline, supervisor,
)


def out(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def required(value: object, label: str) -> object:
    if value is None or value == "" or value == []:
        raise ValueError(f"{label} fehlt")
    return value


# --------------------------------------------------------------------------


def cmd_task(args: argparse.Namespace) -> int:
    if args.action == "new":
        task_id = ledger.create_task(
            goal=args.goal,
            risk_class=args.risk,
            target_resource=args.resource,
            desired_state=args.desired_state,
            planned_method=args.method,
            alternative_method=args.alternative,
            acceptance_criteria=args.acceptance,
            rollback_plan=args.rollback,
            fingerprint=fingerprint.digest(),
        )
        missing = [
            label for label, value in (
                ("acceptance_criteria", args.acceptance),
                ("rollback_plan", args.rollback),
            ) if not value
        ]
        out({"task_id": task_id, "state": "RECEIVED",
             "warning_missing": missing or None})
        return 1 if missing and args.risk.upper() in ("R2", "R3") else 0

    if args.action == "state":
        try:
            ledger.set_state(args.task_id, args.state.upper(), args.detail)
        except (KeyError, ValueError, RuntimeError) as error:
            out({"error": str(error), "readiness": ledger.completion_readiness(args.task_id)})
            return 1
        out(ledger.get_task(args.task_id))
        return 0

    if args.action == "show":
        task = ledger.get_task(args.task_id)
        if task is None:
            out({"error": f"Unbekannter Task: {args.task_id}"})
            return 1
        out(task)
        return 0

    if args.action == "readiness":
        report = ledger.completion_readiness(str(required(args.task_id, "--task-id")))
        out(report)
        return 0 if report["ready"] else 1

    out(ledger.open_tasks())
    return 0


def cmd_lock(args: argparse.Namespace) -> int:
    if args.action == "acquire":
        try:
            # Ueber die Kommandozeile gesetzte Locks gehoeren dem Task, nicht
            # diesem Prozess - er endet sofort nach dem Aufruf.
            owner = "task" if args.task_id else "process"
            lock = locks.acquire(args.resource, agent=args.agent,
                                 task_id=args.task_id, reason=args.reason or "",
                                 owner=owner)
        except locks.LockUnavailable as error:
            out({"acquired": False, "resource": args.resource,
                 "holder": error.holder, "message": str(error)})
            return 1
        out({"acquired": True, "resource": lock.resource, "token": lock.token})
        return 0

    if args.action == "release":
        released = locks.release(
            locks.Lock(resource=args.resource, path="", token=args.token)
        )
        out({"released": released, "resource": args.resource})
        return 0 if released else 1

    out(locks.list_locks())
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if args.action == "start":
        run_id = ledger.start_run(args.task_id, args.agent, args.tool,
                                  args.method, args.risk, args.locks)
        out({"run_id": run_id})
        return 0

    ledger.finish_run(
        args.run_id, args.outcome.upper(),
        change_summary=args.change, objective_tests=args.tests,
        verification=args.verification, duration_ms=args.duration or 0,
        retries=args.retries or 0, error=args.error, rollback=args.rollback,
    )
    out({"run_id": args.run_id, "outcome": args.outcome.upper()})
    return 0


def cmd_exp(args: argparse.Namespace) -> int:
    if args.action == "record":
        entry = experience.record(
            args.key, args.method, success=args.success,
            duration_ms=args.duration or 0, agent=args.agent, tool=args.tool,
            error=args.error, root_cause=args.root_cause,
            retries=args.retries or 0, rolled_back=args.rolled_back,
        )
        out(_expose(entry))
        return 0

    if args.action == "promote":
        try:
            entry = experience.promote(
                args.key, args.method,
                revalidate_when=args.revalidate_when or None,
            )
        except (KeyError, ValueError) as error:
            out({"error": str(error)})
            return 1
        out(_expose(entry))
        return 0

    if args.action == "deprecate":
        entry = experience.deprecate(args.key, args.method, args.reason or "veraltet")
        out(_expose(entry))
        return 0

    if args.action == "best":
        entry = experience.best_method(
            args.key, require_environment_match=not args.ignore_environment
        )
        out(_expose(entry) if entry else {"key": args.key, "best": None})
        return 0 if entry else 1

    if args.action == "stale":
        out([{**_expose(entry), "mismatched_keys": mismatches}
             for entry, mismatches in experience.stale_entries()])
        return 0

    out([_expose(entry) for entry in experience.all_entries()])
    return 0


def _expose(entry: experience.Experience) -> dict:
    return {
        "key": entry.key, "method": entry.method, "status": entry.status,
        "agent": entry.agent, "attempts": entry.attempts,
        "success_count": entry.success_count, "failure_count": entry.failure_count,
        "success_rate": entry.success_rate,
        "median_duration_ms": entry.median_duration_ms,
        "rollbacks": entry.rollbacks, "retries": entry.retries,
        "last_success_utc": entry.last_success_utc,
        "last_failure_utc": entry.last_failure_utc,
        "root_cause": entry.root_cause,
        "limitations": entry.limitations,
        "revalidate_when": entry.revalidate_when,
        "environment_digest": entry.environment_digest,
    }


def cmd_env(args: argparse.Namespace) -> int:
    data = fingerprint.collect()
    if args.action == "known-good":
        path = fingerprint.save_known_good(args.name, data)
        out({"saved": path, "digest": fingerprint.digest(data), "versions": data})
        return 0
    out({"digest": fingerprint.digest(data), "versions": data})
    return 0


def cmd_checkpoint(args: argparse.Namespace) -> int:
    from agentsys import paths
    if args.action == "clear":
        paths.CHECKPOINT_FILE.unlink(missing_ok=True)
        out({"cleared": True})
        return 0
    out(ledger.read_checkpoint() or {"checkpoint": None})
    return 0


def cmd_knowledge(args: argparse.Namespace) -> int:
    try:
        if args.action == "submit":
            payload = json.loads(Path(required(args.file, "--file")).read_text(encoding="utf-8"))
            out(knowledge.submit(payload))
        elif args.action == "list":
            out(knowledge.list_candidates(args.bucket))
        elif args.action == "search":
            out(knowledge.search(
                args.vault, args.query or "", entity=args.entity,
                project=args.project, statuses=set(args.status or []) or None,
                limit=args.limit,
            ))
        elif args.action == "approve":
            out(knowledge.approve(
                str(required(args.candidate_id, "--candidate-id")), vault_root=args.vault,
                task_id=str(required(args.task_id, "--task-id")),
                expected_sha256=str(required(args.expected_sha256, "--expected-sha256")),
            ))
        elif args.action == "reject":
            out(knowledge.reject(
                str(required(args.candidate_id, "--candidate-id")),
                task_id=str(required(args.task_id, "--task-id")),
                reason=str(required(args.reason, "--reason")),
            ))
        else:
            out(knowledge.review_task(
                str(required(args.task_id, "--task-id")),
                decision=str(required(args.decision, "--decision")),
                reason=str(required(args.reason, "--reason")),
                candidate_ids=args.review_candidate_id or [],
            ))
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as error:
        out({"error": str(error)})
        return 1
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    try:
        package = context.build(
            args.vault, args.query, entity=args.entity, project=args.project,
            statuses=set(args.status or []) or None,
            token_budget=args.budget, limit=args.limit,
        )
    except (OSError, ValueError) as error:
        out({"error": str(error)})
        return 1
    out(package.to_dict())
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    try:
        cases = evals.load_cases(args.directory)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        out({"error": str(error)})
        return 1
    out([case.__dict__ for case in cases])
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    try:
        if args.action == "record":
            payload = json.loads(Path(required(args.file, "--file")).read_text(encoding="utf-8"))
            out(evals.record_metric(payload, destination=args.events))
        else:
            out(evals.kpi_report(args.events))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        out({"error": str(error)})
        return 1
    return 0


def cmd_skill_candidate(args: argparse.Namespace) -> int:
    try:
        if args.action == "create":
            draft = Path(required(args.draft, "--draft")).read_text(encoding="utf-8")
            out(skills_pipeline.create_candidate(
                name=str(required(args.name, "--name")),
                rationale=str(required(args.rationale, "--rationale")),
                source_experience_keys=list(required(
                    args.source_experience, "--source-experience"
                )),
                draft_skill_md=draft,
            ))
        elif args.action == "list":
            out(skills_pipeline.list_candidates())
        else:
            out(skills_pipeline.capability_report())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        out({"error": str(error)})
        return 1
    return 0


def cmd_supervisor(args: argparse.Namespace) -> int:
    report = supervisor.check(args.vault)
    out(report)
    return 1 if report["status"] == "FAIL" else 0


def cmd_policy(args: argparse.Namespace) -> int:
    decision = policy.evaluate(args.tool, {"command": args.command,
                                           "file_path": args.command})
    out({"verdict": decision.verdict, "rule": decision.rule,
         "reason": decision.reason})
    return 0 if decision.verdict == policy.ALLOW else 1


def cmd_route(args: argparse.Namespace) -> int:
    """Ordnet einen Auftrag ein oder bestimmt die naechste Eskalationsstufe."""
    if args.escalate:
        model, effort, reason = routing.escalate(
            args.model or routing.ROUTINE,
            failed_attempts=args.attempts or 0,
            verifier_verdict=args.verdict,
        )
        out({"model": model, "effort": effort, "reason": reason})
        return 0
    if not args.prompt:
        out({"error": "--prompt fehlt (oder --escalate verwenden)"})
        return 1
    r = routing.classify(args.prompt)
    out({"domain": r.domain, "agent": r.agent, "risk": r.risk,
         "model": r.model, "effort": r.effort,
         "reasons": r.reasons, "signals": r.signals,
         "summary": r.summary()})
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    held = locks.list_locks()
    out({
        "open_tasks": [
            {"task_id": t["task_id"], "state": t["state"],
             "risk": t["risk_class"], "goal": t["goal"][:100]}
            for t in ledger.open_tasks()
        ],
        "active_locks": [
            {"resource": l.get("resource"), "agent": l.get("agent"),
             "owner": l.get("owner"), "task_id": l.get("task_id"),
             "stale": l.get("stale")} for l in held
        ],
        "stale_locks": [l.get("resource") for l in held if l.get("stale")],
        "checkpoint": ledger.read_checkpoint(),
        "experiences": len(experience.all_entries()),
        "stale_experiences": len(experience.stale_entries()),
        "environment_digest": fingerprint.digest(),
    })
    return 0


# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentctl", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    task = sub.add_parser("task")
    task.add_argument("action", choices=["new", "state", "show", "open", "readiness"])
    task.add_argument("--task-id")
    task.add_argument("--goal", default="")
    task.add_argument("--risk", default="R1")
    task.add_argument("--resource")
    task.add_argument("--desired-state")
    task.add_argument("--method")
    task.add_argument("--alternative")
    task.add_argument("--acceptance")
    task.add_argument("--rollback")
    task.add_argument("--state", default="")
    task.add_argument("--detail")
    task.set_defaults(func=cmd_task)

    lock = sub.add_parser("lock")
    lock.add_argument("action", choices=["acquire", "release", "list"])
    lock.add_argument("--resource", default="")
    lock.add_argument("--agent", default="lead")
    lock.add_argument("--task-id")
    lock.add_argument("--reason")
    lock.add_argument("--token", default="")
    lock.set_defaults(func=cmd_lock)

    run = sub.add_parser("run")
    run.add_argument("action", choices=["start", "finish"])
    run.add_argument("--run-id", default="")
    run.add_argument("--task-id")
    run.add_argument("--agent", default="lead")
    run.add_argument("--tool", default="")
    run.add_argument("--method", default="")
    run.add_argument("--risk", default="R1")
    run.add_argument("--locks")
    run.add_argument("--outcome", default="PASS")
    run.add_argument("--change")
    run.add_argument("--tests")
    run.add_argument("--verification")
    run.add_argument("--duration", type=int)
    run.add_argument("--retries", type=int)
    run.add_argument("--error")
    run.add_argument("--rollback")
    run.set_defaults(func=cmd_run)

    exp = sub.add_parser("exp")
    exp.add_argument("action",
                     choices=["record", "promote", "deprecate", "best", "list", "stale"])
    exp.add_argument("--key", default="")
    exp.add_argument("--method", default="")
    exp.add_argument("--success", action="store_true")
    exp.add_argument("--agent")
    exp.add_argument("--tool")
    exp.add_argument("--duration", type=int)
    exp.add_argument("--retries", type=int)
    exp.add_argument("--error")
    exp.add_argument("--root-cause")
    exp.add_argument("--rolled-back", action="store_true")
    exp.add_argument("--reason")
    exp.add_argument("--revalidate-when", action="append")
    exp.add_argument("--ignore-environment", action="store_true")
    exp.set_defaults(func=cmd_exp)

    env = sub.add_parser("env")
    env.add_argument("action", choices=["show", "known-good"])
    env.add_argument("--name", default="current")
    env.set_defaults(func=cmd_env)

    checkpoint = sub.add_parser("checkpoint")
    checkpoint.add_argument("action", choices=["show", "clear"])
    checkpoint.set_defaults(func=cmd_checkpoint)

    brain = sub.add_parser("knowledge", help="Second-Brain-Kandidaten und Suche")
    brain.add_argument(
        "action", choices=["submit", "list", "search", "approve", "reject", "review"]
    )
    brain.add_argument("--file")
    brain.add_argument("--bucket", choices=["pending", "accepted", "rejected"], default="pending")
    brain.add_argument("--vault", default=str(knowledge.DEFAULT_VAULT))
    brain.add_argument("--query")
    brain.add_argument("--entity")
    brain.add_argument("--project")
    brain.add_argument("--status", action="append")
    brain.add_argument("--limit", type=int, default=10)
    brain.add_argument("--candidate-id")
    brain.add_argument("--task-id")
    brain.add_argument("--expected-sha256")
    brain.add_argument("--decision", choices=["none", "captured", "deferred"])
    brain.add_argument("--review-candidate-id", action="append", default=[])
    brain.add_argument("--reason", default="")
    brain.set_defaults(func=cmd_knowledge)

    context_parser = sub.add_parser("context", help="Quellenbelegtes Kontextpaket")
    context_parser.add_argument("action", choices=["build"])
    context_parser.add_argument("--vault", default=str(knowledge.DEFAULT_VAULT))
    context_parser.add_argument("--query", required=True)
    context_parser.add_argument("--entity")
    context_parser.add_argument("--project")
    context_parser.add_argument("--status", action="append")
    context_parser.add_argument("--budget", type=int, default=2000)
    context_parser.add_argument("--limit", type=int, default=20)
    context_parser.set_defaults(func=cmd_context)

    eval_parser = sub.add_parser("eval", help="Versionierte Eval-Baseline")
    eval_parser.add_argument("action", choices=["list"])
    eval_parser.add_argument("--directory", default=str(Path(__file__).resolve().parents[1] / "evals"))
    eval_parser.set_defaults(func=cmd_eval)

    metrics = sub.add_parser("metrics", help="Append-only Metriken und KPI-Bericht")
    metrics.add_argument("action", choices=["record", "report"])
    metrics.add_argument("--file")
    from agentsys import paths as agentsys_paths
    metrics.add_argument("--events", default=str(agentsys_paths.METRIC_EVENTS_FILE))
    metrics.set_defaults(func=cmd_metrics)

    skill_candidate = sub.add_parser("skill-candidate", help="Gepruefte Skill-Entwuerfe")
    skill_candidate.add_argument("action", choices=["create", "list", "report"])
    skill_candidate.add_argument("--name")
    skill_candidate.add_argument("--rationale", default="")
    skill_candidate.add_argument("--source-experience", action="append", default=[])
    skill_candidate.add_argument("--draft")
    skill_candidate.set_defaults(func=cmd_skill_candidate)

    supervisor_parser = sub.add_parser("supervisor", help="Read-only Systemgesundheit")
    supervisor_parser.add_argument("action", choices=["check"])
    supervisor_parser.add_argument("--vault", default=str(knowledge.DEFAULT_VAULT))
    supervisor_parser.set_defaults(func=cmd_supervisor)

    pol = sub.add_parser("policy")
    pol.add_argument("action", choices=["check"])
    pol.add_argument("--tool", default="Bash")
    pol.add_argument("--command", required=True)
    pol.set_defaults(func=cmd_policy)

    route = sub.add_parser("route", help="Aufgabe einordnen oder Eskalation bestimmen")
    route.add_argument("--prompt")
    route.add_argument("--escalate", action="store_true")
    route.add_argument("--model")
    route.add_argument("--verdict", help="PASS, FAIL oder INCONCLUSIVE")
    route.add_argument("--attempts", type=int)
    route.set_defaults(func=cmd_route)

    status = sub.add_parser("status")
    status.set_defaults(func=cmd_status)

    return parser


if __name__ == "__main__":
    parsed = build_parser().parse_args()
    sys.exit(parsed.func(parsed))
