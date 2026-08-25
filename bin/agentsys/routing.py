"""Modell-Routing — deterministische Klassifikation einer Aufgabe.

Beantwortet drei Fragen, ohne selbst ein Modell zu befragen:

* Welche **Domäne** — und damit welcher Subagent?
* Welche **Risikoklasse** R0-R3?
* Wieviel **Denkleistung** braucht das — Modellstufe und Effort?

## Warum regelbasiert

Ein Klassifizierer, der selbst ein Modell aufruft, verbraucht genau das
Kontingent, das er einsparen soll — und braucht dafür wieder eine
Modellentscheidung. Diese Rekursion wird hier abgeschnitten: reine Muster,
keine Netzwerkaufrufe, Laufzeit im Millisekundenbereich.

## Was die Empfehlung *nicht* kann

Sie kann das Modell der laufenden Sitzung nicht wechseln — wenn sie greift,
hat dieses Modell den Prompt bereits gelesen. Sie wirkt an zwei Stellen:

1. als Hinweis an den Lead Agent, der eine Aufgabe **delegieren** und dabei
   das Modell pro Aufruf setzen kann — dort greift Routung tatsächlich
2. als Hinweis an den Benutzer, wenn ein Sitzungswechsel sich lohnt

## Modellstufen

Bewusst als Alias, nicht als Versions-ID: `sonnet` und `opus` zeigen immer auf
die aktuelle Generation. Damit veraltet nichts, und es wird kein bestimmtes
Modell verdrahtet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

ROUTINE = "sonnet"      # Ausführung, Bekanntes, Messbares
STRONG = "opus"         # Ambiguität, Planung, kritische Entscheidungen

EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


@dataclass
class Routing:
    """Das Ergebnis einer Klassifikation."""

    domain: str
    agent: str | None
    risk: str
    model: str
    effort: str
    reasons: list[str] = field(default_factory=list)
    signals: dict[str, list[str]] = field(default_factory=dict)

    @property
    def needs_stronger_model(self) -> bool:
        return self.model == STRONG

    def summary(self) -> str:
        return (f"{self.domain} / {self.risk} / {self.model}+{self.effort}"
                f" — {'; '.join(self.reasons) if self.reasons else 'Routinefall'}")


def _c(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# --------------------------------------------------------------------------
# Domäne -> zuständiger Subagent
# --------------------------------------------------------------------------

DOMAINS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    # `\w*?` nur vor den Substantiven, die typischerweise in Komposita
    # stecken — "Grafiktreiber", "Druckerspooler", "Systemdienst". Nicht
    # pauschal auf alle Muster: `\b\w*?git\b` würde sonst "digit" treffen.
    ("windows", "windows-agent", _c(
        r"\b(?:windows|powershell|registry|driver|event.?log|"
        r"geräte.?manager|geraete.?manager|bluescreen|bsod|autostart|"
        r"defender|smart\b|laufwerk\w*|arbeitsspeicher"
        r"|\w*?treiber\w*|\w*?dienst\w*|\w*?spooler\w*|\w*?service\w*"
        r"|\w*?datenträger\w*|\w*?datentraeger\w*|\w*?festplatte\w*)\b")),
    ("infrastruktur", "infrastructure-agent", _c(
        r"\b(linux|ssh|proxmox|docker|container|pterodactyl|wings|systemd|"
        r"nginx|apache|reverse.?proxy|vm\b|virtuelle maschine|ansible|"
        r"opentofu|terraform|kubernetes|debian|ubuntu)\b")),
    ("browser", "browser-agent", _c(
        r"\b(browser|playwright|webui|web.?oberfläche|web.?oberflaeche|"
        r"router|speedport|fritz.?box|panel|formular|webseite|website|"
        r"portfreigabe|portforward\w*|dyndns|anmeld\w*|login)\b")),
    ("gaming", "gaming-agent", _c(
        r"\b(minecraft|ark\b|survival ascended|gameserver|game.?server|"
        r"mod\b|mods\b|plugin\w*|egg\b|eggs\b|paper|spigot|forge|fabric|"
        r"neoforge|savegame|spielstand|welt\b)\b")),
    ("code", "implementation-agent", _c(
        r"\b(code|skript|script|python|javascript|typescript|refactor\w*|"
        r"bugfix|test\b|tests\b|funktion|klasse|modul|repository|git\b|"
        r"commit|implementier\w*|programmier\w*)\b")),
)


# --------------------------------------------------------------------------
# Risiko: die Handlung entscheidet, nicht das Objekt
# --------------------------------------------------------------------------
#
# "Treiber" allein ist kein Risiko — "Treiber installieren" schon. Wer nur
# nach Substantiven klassifiziert, stuft eine reine Diagnose als Änderung ein
# und verlangt Backup und Rollback für etwas, das nichts anfasst.

MUTATION = _c(
    r"\b(installier\w*|deinstallier\w*|entfern\w*|lösch\w*|loesch\w*|delete|"
    r"format\w*|aktivier\w*|deaktivier\w*|konfigurier\w*|ändere?\w*|"
    r"aendere?\w*|setz\w*|erstell\w*|anleg\w*|aktualisier\w*|update|upgrade|"
    r"behebe|beheb\w*|reparier\w*|starte neu|neustart\w*|reboot|"
    r"zurücksetz\w*|zuruecksetz\w*|migrier\w*|verschieb\w*|umzieh\w*|"
    r"richte\w* ein|einrichten|schalte\w*|stopp\w*|beende\w*)\b")

# Deutsche trennbare Verben: die Partikel steht oft am Satzende.
# "Starte den Druckerspooler **neu**" trifft ein Muster "starte neu" nicht —
# genau dieser Fall ist beim Testen aufgefallen.
MUTATION_SEPARABLE = _c(
    r"\b(start\w*|fahr\w*|schalt\w*|setz\w*|mach\w*|leg\w*|nimm)\b"
    r"[^.!?;]{0,60}?\b(neu|aus|ein|ab|hoch|herauf|hinauf|runter|herunter|"
    r"hinunter|zurück|zurueck|frei|an)\b")

READONLY_VERB = _c(
    r"\b(prüf\w*|pruef\w*|zeig\w*|list\w*|lies|lese\w*|analysier\w*|"
    r"untersuch\w*|diagnos\w*|vergleich\w*|bewert\w*|erklär\w*|erklaer\w*|"
    r"finde|such\w*|inventar\w*|status|report\w*|beschreib\w*|"
    r"was ist|wie viel\w*)\b")

# `\b\w*?` davor: deutsche Komposita. "Druckerspooler", "Grafiktreiber",
# "Systemdienst" — ohne den Vorspann verlangt `\bspooler` eine Wortgrenze,
# die im zusammengesetzten Wort nicht existiert. Das unterschätzt Risiko,
# also die gefährliche Richtung.
OBJECT_R3 = _c(
    r"\b\w*?(partition\w*|datenträger\w*|datentraeger\w*|festplatte\w*|bios|"
    r"firmware\w*|bootloader\w*|werkseinstell\w*|benutzerkonto\w*|"
    r"benutzer.?konten|datenbank\w*|savegame\w*|spielstand\w*|welt\b|"
    r"wan\b|produktiv\w*|migration\w*)\b")

OBJECT_R2 = _c(
    r"\b\w*?(treiber\w*|driver\w*|registry|dienst\w*|service\w*|firewall\w*|"
    r"netzwerk\w*|paket\w*|package\w*|vm\b|container\w*|snapshot\w*|"
    r"portfreigabe\w*|portforward\w*|dns|dhcp|wlan|router\w*|spooler\w*|"
    r"einstellung\w*|konfiguration\w*)\b")


# --------------------------------------------------------------------------
# Denkbedarf
# --------------------------------------------------------------------------
#
# Wortstämme bleiben nach hinten offen: `vergleich\b` würde "Vergleiche"
# nicht treffen — genau dieser Fehler ist beim Testen aufgefallen.

AMBIGUITY = _c(
    r"\b(warum|wieso|weshalb|analysier\w*|untersuch\w*|diagnos\w*|"
    r"root.?cause|ursach\w*|vergleich\w*|bewert\w*|entscheid\w*|abwäg\w*|"
    r"abwaeg\w*|empfehl\w*|empfiehl\w*|empfiel\w*|architektur|entwirf|"
    r"entwurf|konzept|planung|strategie|funktioniert nicht|geht nicht|"
    r"klappt nicht|kaputt|seltsam|merkwürdig\w*|merkwuerdig\w*|unerwartet|"
    r"widerspr\w*|inkonsistent|optimier\w*|verbesser\w*|lohnt sich|"
    r"ist besser|sinnvoll\w*)\b")

ROUTINE_SIGNALS = _c(
    r"\b(zeig\w*|list\w*|lies|status|version|prüfe ob|pruefe ob|wie viele|"
    r"welche datei|gib mir|finde|öffne|oeffne)\b")

EXPLICIT_INSTRUCTION = _c(r"\b(führe aus|fuehre aus|mach genau|nur\b)\b")


# --------------------------------------------------------------------------


def classify(prompt: str) -> Routing:
    """Klassifiziert einen Auftrag und empfiehlt Modellstufe und Effort."""
    text = (prompt or "").strip()
    reasons: list[str] = []
    signals: dict[str, list[str]] = {}

    # --- Domäne -----------------------------------------------------------
    domain, agent = "allgemein", None
    hits: list[tuple[str, str, int]] = []
    for name, subagent, pattern in DOMAINS:
        found = pattern.findall(text)
        if found:
            hits.append((name, subagent, len(found)))
            signals.setdefault("domäne", []).extend(
                sorted({f if isinstance(f, str) else f[0] for f in found})[:4])
    if hits:
        hits.sort(key=lambda h: -h[2])
        domain, agent = hits[0][0], hits[0][1]
        if len(hits) > 1 and hits[0][2] == hits[1][2]:
            reasons.append(f"mehrere Domänen gleich stark ({hits[0][0]}/{hits[1][0]})")

    # --- Risiko: Handlung vor Objekt --------------------------------------
    mutates = bool(MUTATION.search(text) or MUTATION_SEPARABLE.search(text))
    reads_only = bool(READONLY_VERB.search(text))

    if mutates and OBJECT_R3.search(text):
        risk = "R3"
        signals["risiko"] = ["mutierendes Verb + kritisches Objekt"]
    elif mutates and OBJECT_R2.search(text):
        risk = "R2"
        signals["risiko"] = ["mutierendes Verb + relevantes Objekt"]
    elif mutates:
        risk = "R1"
        signals["risiko"] = ["mutierendes Verb ohne erkanntes Zielobjekt"]
    else:
        risk = "R0"
        if (OBJECT_R3.search(text) or OBJECT_R2.search(text)) and reads_only:
            reasons.append("nur lesend trotz heikler Objekte — kein Preflight nötig")

    # --- Denkbedarf -------------------------------------------------------
    ambiguous = bool(AMBIGUITY.search(text))
    routine = bool(ROUTINE_SIGNALS.search(text))
    explicit = bool(EXPLICIT_INSTRUCTION.search(text))
    if ambiguous:
        signals["ambiguität"] = sorted({m for m in AMBIGUITY.findall(text)})[:4]

    model, effort = ROUTINE, "medium"

    if risk == "R3":
        model, effort = STRONG, "high"
        reasons.append("R3: schwer umkehrbar, Fehlentscheidung teuer")
    elif ambiguous:
        model, effort = STRONG, "high"
        reasons.append("offene Frage statt klarer Anweisung")
    elif risk == "R2":
        effort = "high"
        reasons.append("R2: reale Änderung, aber klar umrissen")
    elif routine:
        effort = "low" if explicit else "medium"
        reasons.append("abfragende oder klar umrissene Aufgabe")

    # Ein sehr langer Auftrag hat meist mehrere Teilziele.
    if len(text) > 700 and model == ROUTINE:
        effort = "high"
        reasons.append("umfangreicher Auftrag mit mehreren Teilzielen")

    if len(text) < 15:
        reasons.append("sehr kurzer Auftrag — Einordnung unsicher")

    return Routing(domain=domain, agent=agent, risk=risk,
                   model=model, effort=effort, reasons=reasons, signals=signals)


def escalate(current_model: str, *, failed_attempts: int = 0,
             verifier_verdict: str | None = None) -> tuple[str, str, str]:
    """Bestimmt die nächste Stufe nach einem Fehlschlag.

    Eskalation ist kein Automatismus für jeden Fehler: ein Tippfehler wird
    nicht durch ein stärkeres Modell behoben. Sie greift, wenn ein Versuch aus
    *Denkgründen* scheitert — der Verifier also FAIL meldet oder zwei
    inhaltlich verschiedene Ansätze gescheitert sind.
    """
    verdict = (verifier_verdict or "").upper()

    if verdict == "INCONCLUSIVE":
        return (current_model, "high",
                "Evidenz reicht nicht — mehr Prüftiefe, nicht mehr Modell")
    if verdict == "FAIL" or failed_attempts >= 2:
        if current_model == ROUTINE:
            return (STRONG, "high",
                    "Scheitern aus Denkgründen — stärkeres Modell mit Evidenz-Handoff")
        return (STRONG, "xhigh", "Bereits stark — Effort erhöhen statt Modell wechseln")
    return (current_model, "medium", "Kein Eskalationsgrund")
