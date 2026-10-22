"""Portable workflow entry point; no LLM API, login or background model calls."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agentsys import context, knowledge, ledger, workflow


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    route = commands.add_parser("plan")
    route.add_argument("--prompt", required=True)
    route.add_argument("--risk", choices=["R0", "R1", "R2", "R3"])
    lookup = commands.add_parser("context")
    lookup.add_argument("--query", required=True)
    lookup.add_argument("--project")
    lookup.add_argument("--budget", type=int, default=2000)
    lookup.add_argument("--vault", type=Path, default=knowledge.DEFAULT_VAULT)
    importer = commands.add_parser("import-memory")
    importer.add_argument("--file", type=Path, required=True)
    importer.add_argument("--stage", action="store_true", help="Stage pending candidates; never auto-approve imports")
    checkpoint = commands.add_parser("checkpoint")
    checkpoint.add_argument("action", choices=["show", "save", "clear"])
    checkpoint.add_argument("--session-id", required=True)
    checkpoint.add_argument("--file", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "plan":
            result = workflow.plan(args.prompt, risk=args.risk)
        elif args.command == "context":
            result = context.build(args.vault, args.query, project=args.project,
                                   token_budget=args.budget).__dict__
        elif args.command == "import-memory":
            from agentsys.memory_import import import_file
            result = import_file(args.file, stage=args.stage)
        else:
            if args.action == "save":
                if args.file is None:
                    raise ValueError("save requires --file containing a JSON object")
                payload = json.loads(args.file.read_text(encoding="utf-8-sig"))
                if not isinstance(payload, dict):
                    raise ValueError("Checkpoint must be an object")
                ledger.write_checkpoint(payload, args.session_id)
            elif args.action == "clear":
                ledger.checkpoint_path(args.session_id).unlink(missing_ok=True)
            result = ledger.read_checkpoint(args.session_id) or {"checkpoint": None}
        print(json.dumps(result, ensure_ascii=False, indent=2,
                         default=lambda value: value.__dict__))
        return 0
    except (ValueError, OSError) as error:
        print(json.dumps({"status": "FAIL", "error": ledger.redact(str(error))}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
