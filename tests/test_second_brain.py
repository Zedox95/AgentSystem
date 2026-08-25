"""Isolierte Tests fuer Candidate Queue, Suche und Archivist."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"C:\AgentSystem")
_TMP = Path(tempfile.mkdtemp(prefix="agentsys-brain-"))
_VAULT = _TMP / "vault"
(_VAULT / "01 Inbox").mkdir(parents=True)
os.environ["AGENTSYSTEM_ROOT"] = str(_TMP / "system")
os.environ["AGENTSYSTEM_VAULT"] = str(_VAULT)
sys.path.insert(0, str(ROOT / "bin"))

from agentsys import knowledge, ledger, locks  # noqa: E402
from agentsys.contracts import KnowledgeCandidate, file_hash  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def make_candidate(value: str, *, source_type: str = "measurement",
                   source_ref: str = "local-check") -> KnowledgeCandidate:
    return KnowledgeCandidate(
        entity="router-speedport-smart4", fact_key="firmware.version",
        value=value, status="current", confidence="high",
        source_type=source_type, source_ref=source_ref,
        valid_from="2026-08-23", last_verified="2026-08-23",
        created_by="test",
    )


task_id = ledger.create_task(
    "Wissenstest", "R1", acceptance_criteria="Notiz korrekt",
    rollback_plan="Temp-Vault entfernen",
)
for state in ("PLANNED", "PREFLIGHT", "LOCKED", "BASELINED", "BACKED_UP", "EXECUTING"):
    ledger.set_state(task_id, state)

first = knowledge.submit(make_candidate("12.0.1"))
duplicate = knowledge.submit(make_candidate("12.0.1"))
check(first["duplicate"] is False, "Erster Candidate darf kein Duplikat sein")
check(duplicate["duplicate"] is True, "Identischer Candidate muss dedupliziert werden")
check(len(knowledge.list_candidates()) == 1, "Queue muss genau einen Candidate enthalten")

decision = knowledge.approve(
    first["candidate_id"], vault_root=_VAULT,
    task_id=task_id, expected_sha256="NEW",
)
note = _VAULT / decision["target_note"]
check(note.is_file(), "Archivist muss die Entity-Notiz anlegen")
text = note.read_text(encoding="utf-8")
check("entity: \"router-speedport-smart4\"" in text,
      "Entity-Frontmatter fehlt")
check("agentsystem:facts:start" in text and "12.0.1" in text,
      "Verwalteter Faktenblock fehlt")
check(not knowledge.list_candidates(), "Akzeptierter Candidate muss pending verlassen")
check(len(knowledge.list_candidates("accepted")) == 1,
      "Akzeptierter Candidate muss historisiert werden")

# Unverwaltete und private Notizen werden nicht in automatische Kontexte gezogen.
(_VAULT / "private.md").write_text("Mein privater Text zum Router", encoding="utf-8")
managed_looking_private = _VAULT / "private-with-frontmatter.md"
managed_looking_private.write_text(
    "---\ntype: system_entity\nentity: router-speedport-smart4\nstatus: current\n"
    "confidence: high\nsource_type: user_confirmed\nvalid_from: 2026-08-23\n"
    "last_verified: 2026-08-23\n---\nPrivate Router-Notiz ohne AgentSystem-Block",
    encoding="utf-8",
)
daily = _VAULT / "05 Daily Notes" / "2026-08-23.md"
daily.parent.mkdir(parents=True)
daily.write_text(
    "---\ntype: note\nentity: router-speedport-smart4\nstatus: current\n"
    "confidence: high\nsource_type: user_confirmed\nvalid_from: 2026-08-23\n"
    "last_verified: 2026-08-23\n---\nPrivat", encoding="utf-8",
)
matches = knowledge.search(_VAULT, "Firmware Router", entity="router-speedport-smart4")
check(len(matches) == 1 and matches[0]["source_path"] == decision["target_note"],
      f"Suche muss nur verwaltete, nicht-private Notiz liefern: {matches}")

# Selbst vollstaendiges Frontmatter macht eine private Notiz nicht verwaltet;
# ein explizites target_note darf diese Grenze ebenfalls nicht umgehen.
private_candidate = KnowledgeCandidate(
    entity="private-router-note", fact_key="should.not.write", value="blocked",
    status="current", confidence="high", source_type="user_confirmed",
    source_ref="test-private-boundary", valid_from="2026-08-23",
    last_verified="2026-08-23", target_note="private-with-frontmatter.md",
    created_by="test",
)
private_submission = knowledge.submit(private_candidate)
before_private = managed_looking_private.read_bytes()
try:
    knowledge.approve(
        private_submission["candidate_id"], vault_root=_VAULT,
        task_id=task_id, expected_sha256=file_hash(managed_looking_private),
    )
    FAILURES.append("Explizites target_note darf private Notiz nicht veraendern")
except knowledge.KnowledgeConflict:
    pass
check(managed_looking_private.read_bytes() == before_private,
      "Blockierte private Notiz muss byte-identisch bleiben")

# Versionierende Felder duerfen nicht in einer alten Candidate-ID verschwinden.
reverified = KnowledgeCandidate(
    entity="router-speedport-smart4", fact_key="firmware.version",
    value="12.0.1", status="current", confidence="high",
    source_type="measurement", source_ref="local-check",
    valid_from="2026-08-23", last_verified="2026-08-24", created_by="test",
)
reverified_submission = knowledge.submit(reverified)
check(reverified_submission["candidate_id"] != first["candidate_id"],
      "Neues last_verified braucht eine eigene Candidate-ID")

# Bereits akzeptierter Inhalt wird auch bucket-uebergreifend dedupliziert.
accepted_duplicate = knowledge.submit(make_candidate("12.0.1"))
check(accepted_duplicate["duplicate"] and accepted_duplicate["status"] == "ACCEPTED",
      "Deduplizierung muss accepted/rejected Buckets einbeziehen")

# Eine schwaechere Bestaetigung desselben Werts darf die fuer Retrieval
# verwendete Notizprioritaet nicht degradieren.
same_value_weak = knowledge.submit(make_candidate(
    "12.0.1", source_type="community", source_ref="forum:gleicher-wert"))
knowledge.approve(
    same_value_weak["candidate_id"], vault_root=_VAULT,
    task_id=task_id, expected_sha256=file_hash(note),
)
frontmatter_after_weak = note.read_text(encoding="utf-8")
check('source_type: "measurement"' in frontmatter_after_weak,
      "Schwaechere Quelle mit gleichem Wert darf Frontmatter nicht degradieren")
retrieved_after_weak = knowledge.search(
    _VAULT, "Firmware", entity="router-speedport-smart4"
)
check(retrieved_after_weak[0]["source_type"] == "measurement",
      "Retrieval muss weiterhin die staerkste aktive Quelle melden")

# Optimistic Concurrency verhindert Lost Updates.
second = knowledge.submit(make_candidate("12.0.2"))
try:
    knowledge.approve(second["candidate_id"], vault_root=_VAULT,
                      task_id=task_id, expected_sha256="0" * 64)
    FAILURES.append("Falscher erwarteter Hash muss blockieren")
except knowledge.KnowledgeConflict:
    pass

# Eine schwaechere Quelle darf einen Messwert nicht ersetzen.
weak = knowledge.submit(make_candidate(
    "13.0.0", source_type="community", source_ref="forum:beitrag-1"))
try:
    knowledge.approve(weak["candidate_id"], vault_root=_VAULT,
                      task_id=task_id, expected_sha256=file_hash(note))
    FAILURES.append("Schwaechere Quelle darf Messwert nicht ueberschreiben")
except knowledge.KnowledgeConflict:
    pass

# Ein zweiter Writer wird durch den Entity-Lock abgehalten.
held = locks.acquire("obsidian:entity:router-speedport-smart4",
                     agent="other-writer", owner="process")
try:
    try:
        knowledge.approve(second["candidate_id"], vault_root=_VAULT,
                          task_id=task_id, expected_sha256=file_hash(note))
        FAILURES.append("Zweiter Writer muss am Entity-Lock scheitern")
    except locks.LockUnavailable:
        pass
finally:
    locks.release(held)

# Nach Freigabe kann der gleich starke, neu gemessene Wert historisiert werden.
knowledge.approve(second["candidate_id"], vault_root=_VAULT,
                  task_id=task_id, expected_sha256=file_hash(note))
payload_text = note.read_text(encoding="utf-8")
check('"status": "superseded"' in payload_text and "12.0.2" in payload_text,
      "Alter Messwert muss historisiert und neuer Wert aktuell sein")

print(json.dumps({
    "status": "FAIL" if FAILURES else "PASS",
    "candidate_id": first["candidate_id"],
    "target_note": decision["target_note"],
    "search_results": len(matches),
    "failures": FAILURES,
    "temp_root": str(_TMP),
}, ensure_ascii=False, indent=2))
sys.exit(1 if FAILURES else 0)
