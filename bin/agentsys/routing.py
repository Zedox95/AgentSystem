"""Model routing — deterministic classification of a task.

Answers three questions without consulting a model itself:

* Which **domain** — and therefore which subagent?
* Which **risk class** R0-R3?
* How much **thinking power** does this need — model tier and effort?

## Why rule-based

A classifier that itself calls a model consumes exactly the quota it's
meant to save — and needs another model decision to do so. This recursion
is cut off here: pure patterns, no network calls, runtime in the
millisecond range.

## What the recommendation *cannot* do

It cannot switch the model of the running session — by the time it applies,
that model has already read the prompt. It acts in two places:

1. as a hint to the lead agent, which can **delegate** a task and set the
   model per call — that's where routing actually takes effect
2. as a hint to the user, when a session switch would be worthwhile

## Model tiers

Deliberately an alias, not a version ID: `sonnet` and `opus` always point to
the current generation. That way nothing goes stale, and no specific model
is hardwired.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

ROUTINE = "sonnet"      # execution, known territory, measurable
STRONG = "opus"         # ambiguity, planning, critical decisions

EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


@dataclass
class Routing:
    """The result of a classification."""

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
# Domain -> responsible subagent
# --------------------------------------------------------------------------

DOMAINS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    # `\w*?` only in front of the nouns that typically appear in German
    # compounds — "Grafiktreiber", "Druckerspooler", "Systemdienst". Not
    # applied blanket to every pattern: `\b\w*?git\b` would otherwise match
    # "digit".
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
# Risk: the action decides, not the object
# --------------------------------------------------------------------------
#
# "Driver" alone is not a risk — "install driver" is. A classifier that only
# looks at nouns would rate a pure diagnosis as a change and demand backup
# and rollback for something that touches nothing.

MUTATION = _c(
    r"\b(installier\w*|deinstallier\w*|entfern\w*|lösch\w*|loesch\w*|delete|"
    r"format\w*|aktivier\w*|deaktivier\w*|konfigurier\w*|ändere?\w*|"
    r"aendere?\w*|setz\w*|erstell\w*|anleg\w*|aktualisier\w*|update|upgrade|"
    r"behebe|beheb\w*|reparier\w*|starte neu|neustart\w*|reboot|"
    r"zurücksetz\w*|zuruecksetz\w*|migrier\w*|verschieb\w*|umzieh\w*|"
    r"richte\w* ein|einrichten|schalte\w*|stopp\w*|beende\w*)\b")

# German separable verbs: the particle often sits at the end of the
# sentence. "Starte den Druckerspooler **neu**" does not match a pattern
# "starte neu" — this exact case turned up during testing.
MUTATION_SEPARABLE = _c(
    r"\b(start\w*|fahr\w*|schalt\w*|setz\w*|mach\w*|leg\w*|nimm)\b"
    r"[^.!?;]{0,60}?\b(neu|aus|ein|ab|hoch|herauf|hinauf|runter|herunter|"
    r"hinunter|zurück|zurueck|frei|an)\b")

READONLY_VERB = _c(
    r"\b(prüf\w*|pruef\w*|zeig\w*|list\w*|lies|lese\w*|analysier\w*|"
    r"untersuch\w*|diagnos\w*|vergleich\w*|bewert\w*|erklär\w*|erklaer\w*|"
    r"finde|such\w*|inventar\w*|status|report\w*|beschreib\w*|"
    r"was ist|wie viel\w*)\b")

# `\b\w*?` in front: German compound words. "Druckerspooler",
# "Grafiktreiber", "Systemdienst" — without the prefix, `\bspooler` requires
# a word boundary that doesn't exist inside the compound word. That
# underestimates risk, i.e. the dangerous direction.
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
# Thinking requirement
# --------------------------------------------------------------------------
#
# Word stems are left open-ended at the tail: `vergleich\b` would not match
# "Vergleiche" — this exact bug turned up during testing.

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
    """Classifies a task and recommends a model tier and effort."""
    text = (prompt or "").strip()
    reasons: list[str] = []
    signals: dict[str, list[str]] = {}

    # --- Domain -------------------------------------------------------------
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
            reasons.append(f"multiple domains equally strong ({hits[0][0]}/{hits[1][0]})")

    # --- Risk: action before object ------------------------------------
    mutates = bool(MUTATION.search(text) or MUTATION_SEPARABLE.search(text))
    reads_only = bool(READONLY_VERB.search(text))

    if mutates and OBJECT_R3.search(text):
        risk = "R3"
        signals["risiko"] = ["mutating verb + critical object"]
    elif mutates and OBJECT_R2.search(text):
        risk = "R2"
        signals["risiko"] = ["mutating verb + relevant object"]
    elif mutates:
        risk = "R1"
        signals["risiko"] = ["mutating verb without a recognized target object"]
    else:
        risk = "R0"
        if (OBJECT_R3.search(text) or OBJECT_R2.search(text)) and reads_only:
            reasons.append("read-only despite sensitive objects — no preflight needed")

    # --- Thinking requirement -----------------------------------------------
    ambiguous = bool(AMBIGUITY.search(text))
    routine = bool(ROUTINE_SIGNALS.search(text))
    explicit = bool(EXPLICIT_INSTRUCTION.search(text))
    if ambiguous:
        signals["ambiguität"] = sorted({m for m in AMBIGUITY.findall(text)})[:4]

    model, effort = ROUTINE, "medium"

    if risk == "R3":
        model, effort = STRONG, "high"
        reasons.append("R3: hard to reverse, a wrong decision is costly")
    elif ambiguous:
        model, effort = STRONG, "high"
        reasons.append("open question instead of a clear instruction")
    elif risk == "R2":
        effort = "high"
        reasons.append("R2: real change, but clearly scoped")
    elif routine:
        effort = "low" if explicit else "medium"
        reasons.append("query-style or clearly scoped task")

    # A very long task usually has several sub-goals.
    if len(text) > 700 and model == ROUTINE:
        effort = "high"
        reasons.append("extensive task with multiple sub-goals")

    if len(text) < 15:
        reasons.append("very short task — classification uncertain")

    return Routing(domain=domain, agent=agent, risk=risk,
                   model=model, effort=effort, reasons=reasons, signals=signals)


def escalate(current_model: str, *, failed_attempts: int = 0,
             verifier_verdict: str | None = None) -> tuple[str, str, str]:
    """Determines the next tier after a failure.

    Escalation is not an automatism for every error: a typo is not fixed by
    a stronger model. It applies when an attempt fails for *thinking
    reasons* — i.e. the verifier reports FAIL, or two substantively
    different approaches have failed.
    """
    verdict = (verifier_verdict or "").upper()

    if verdict == "INCONCLUSIVE":
        return (current_model, "high",
                "Evidence is insufficient — more depth of testing, not a bigger model")
    if verdict == "FAIL" or failed_attempts >= 2:
        if current_model == ROUTINE:
            return (STRONG, "high",
                    "Failure for reasoning-related reasons — stronger model with evidence handoff")
        return (STRONG, "xhigh", "Already strong — raise effort instead of switching model")
    return (current_model, "medium", "No reason to escalate")
