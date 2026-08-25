"""UserPromptSubmit — klassifiziert jeden Auftrag, bevor er bearbeitet wird.

Der Hook kann das Modell der laufenden Sitzung **nicht** wechseln — wenn er
feuert, hat dieses Modell den Prompt bereits gelesen. Sein Zweck ist ein
anderer: er sorgt dafür, dass die Einordnung **deterministisch** passiert und
nicht dem Bauchgefühl des Modells überlassen bleibt, das gerade antwortet.

Wirken kann die Empfehlung an zwei Stellen:

1. Der Lead Agent delegiert die Aufgabe an einen Subagenten und setzt dabei
   das Modell pro Aufruf — dort greift die Routung tatsächlich.
2. Bei einem deutlichen Missverhältnis bekommt der Benutzer den Hinweis, dass
   ein Sitzungswechsel sich lohnt.

Bewusst zurückhaltend: Der Hook meldet sich nur, wenn er etwas beizutragen
hat. Ein Hinweis bei jedem Prompt wäre Lärm und würde nach kurzer Zeit
überlesen.
"""

from __future__ import annotations

import hooklib

# Unterhalb dieser Länge lohnt keine Einordnung — "ja", "weiter", "danke".
MIN_LENGTH = 25


def main() -> None:
    data = hooklib.read_input()
    prompt = str(data.get("user_input") or "").strip()

    if len(prompt) < MIN_LENGTH:
        hooklib.emit_nothing()

    from agentsys import routing

    result = routing.classify(prompt)

    # Der Normalfall bleibt stumm: Routineaufgabe, kein Risiko, kein
    # Subagent — dazu gibt es nichts zu sagen.
    if (not result.needs_stronger_model and result.risk in ("R0", "R1")
            and result.agent is None):
        _record(data, result)
        hooklib.emit_nothing()

    lines = [f"Einordnung (regelbasiert, ohne Modellaufruf): "
             f"**{result.domain} · {result.risk} · empfohlen {result.model} "
             f"mit Effort {result.effort}**"]

    if result.reasons:
        lines.append("Grund: " + "; ".join(result.reasons))

    if result.agent:
        lines.append(
            f"Zuständig wäre `{result.agent}`. Bei Delegation das Modell pro "
            f"Aufruf auf `{result.model}` setzen — dort greift die Routung "
            "tatsächlich."
        )

    if result.risk in ("R2", "R3"):
        lines.append(
            f"{result.risk}: vor der ersten Änderung `preflight-change` — "
            "Task Contract, Lock, Baseline, Backup, Rollback-Plan."
            + (" R3 braucht zusätzlich die ausdrückliche Freigabe des Benutzers."
               if result.risk == "R3" else "")
        )

    if result.needs_stronger_model:
        lines.append(
            "Wenn diese Sitzung auf dem schwächeren Modell läuft: entweder die "
            "denkintensiven Teile an einen Subagenten mit `model: opus` "
            "delegieren, oder dem Benutzer einen Sitzungswechsel vorschlagen. "
            "Die Einordnung allein ist kein Grund, ungefragt zu wechseln."
        )

    lines.append(
        "Diese Einordnung ist ein Hinweis, keine Anweisung. Widerspricht sie "
        "dem, was du am System siehst, gilt die Beobachtung."
    )

    _record(data, result)
    hooklib.additional_context("UserPromptSubmit", "\n".join(lines))


def _record(data: dict, result) -> None:
    """Protokolliert nur die Einordnung; Prompt-Inhalte bleiben aus dem Ledger."""
    try:
        from agentsys import ledger
        ledger.log_event(
            "PROMPT_ROUTED",
            session_id=data.get("session_id"),
            detail={
                "domain": result.domain,
                "agent": result.agent,
                "risk": result.risk,
                "model": result.model,
                "effort": result.effort,
                "reasons": result.reasons,
            },
        )
    except Exception:  # noqa: BLE001 - Protokollierung darf nie blockieren
        pass


hooklib.safe(main)
