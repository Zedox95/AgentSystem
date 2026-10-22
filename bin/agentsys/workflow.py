"""Small provider-neutral work plans. A plan is advice, never authorization."""

from __future__ import annotations

import re

from . import routing


def plan(prompt: str, *, risk: str | None = None) -> dict:
    route = routing.classify(prompt)
    if risk is not None:
        if risk not in ("R0", "R1", "R2", "R3"):
            raise ValueError("Unknown risk class")
        route.risk = max(route.risk, risk)
        if route.risk >= "R2":
            route.effort = "high"
        if route.risk == "R3":
            route.model = routing.STRONG
    research = bool(re.search(
        r"latest|current|recommend|compare|source|research|aktuell|neueste|empfehl|vergleich|quelle|recherch",
        prompt, re.I,
    ))
    skills = ["evidence-research"] if research else []
    if route.risk != "R0":
        skills.extend(["preflight-change", "verify-change"])
    # Roles are candidates. Mentioning a domain alone does not spawn an agent.
    return {
        "risk_hint": route.risk,
        "requires_explicit_approval": route.risk == "R3",
        "model_tier": route.model,
        "effort": route.effort,
        "skills": skills,
        "specialist_if_delegated": route.agent,
        "independent_verifier": route.risk != "R0",
        "default_extra_agents": 0,
        "max_extra_agents": 2,
        "session_strategy": "one coherent task per session; shared managed memory",
        "memory": "retrieve when prior facts change the answer; review durable outcomes",
        "verification": "reuse unchanged evidence; independently recheck critical acceptance criteria",
        "advisory_only": True,
    }
