# Second Brain and Learning Agent System

## Target picture

The extension separates data contracts, knowledge, context, measurement, and learning. The Second
Brain is not an unchecked chat history: only structured, source-backed facts may go live through a
controlled single-writer path.

```text
Observation -> Knowledge Candidate -> Archivist review -> managed vault note
                                              |
                  Read-only search -> Context Builder -> source package
                                              |
                   Eval + Metric Events -> KPI/capability report
                                              |
                           Skill Candidate -> manual review
```

## Safety boundaries

- Schemas and runtime contracts live in `schemas/` and `bin/agentsys/contracts.py`.
- New facts start in `state/knowledge-candidates/pending`.
- Only `knowledge.approve` writes to the managed knowledge store. It requires an open R1+ task, an
  entity lock, an expected file hash, and, for existing notes, a verified backup.
- Weaker sources do not overwrite stronger ones. Earlier values are kept as `superseded`.
- Only Markdown files with complete status frontmatter are read automatically. Unmanaged notes and
  private areas remain excluded.
- Context packages carry path, SHA-256, status, verification date, ranking, and a fixed token
  budget.
- Skill proposals land only under `state/skill-candidates`. There is no automatic activation or
  promotion path.
- The supervisor checks the ledger, checkpoint, locks, candidates, metrics, evals, knowledge store,
  and index drift in a strictly read-only manner. It fixes nothing itself.

## Usage

All commands print machine-readable JSON:

```powershell
agentctl knowledge submit --file candidate.json
agentctl knowledge list --bucket pending
agentctl knowledge search --query <search term> --entity <entity-id>
agentctl knowledge approve --candidate-id kc-... --task-id task-... --expected-sha256 NEW
agentctl knowledge review --task-id task-... --decision captured `
  --review-candidate-id kc-... --reason "Confirmed system state adopted"

agentctl context build --query <search term> --entity <entity-id> --budget 2000
agentctl eval list
agentctl metrics record --file metric.json
agentctl metrics report

agentctl skill-candidate create --name new-skill --rationale "..." `
  --source-experience experience.key --draft SKILL.md
agentctl skill-candidate report
agentctl supervisor check
```

`knowledge reject` additionally requires `--task-id` and `--reason`. For an existing note in the
knowledge store, `knowledge approve` is given the currently measured SHA-256 instead of `NEW`.

After the last completed run and before `COMMITTED`, a knowledge review is mandatory.
`none` documents with justification that no permanent fact was created; `captured` requires
candidate IDs accepted under the same task; `deferred` refers to pending or rejected candidates.
`agentctl task readiness` deterministically shows all commit prerequisites that are still missing.

## Objective tests

The central regression tests run via:

```powershell
python tests/run-all.py
```

Covered are contracts, the candidate queue, single-writer behavior, source priority,
optimistic concurrency, context reproducibility, budgeting, evals, KPI aggregation,
skill isolation, supervisor detection, and CLI smoke tests.
