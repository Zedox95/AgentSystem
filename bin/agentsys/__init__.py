"""agentsys — Kernbibliothek der Control Plane.

Module:

* `paths`       — zentrale Pfade und Schutz der Control Plane
* `policy`      — deterministischer Policy Guard (ALLOW / ASK / DENY)
* `ledger`      — Run Ledger, Task State Machine, Checkpointing
* `locks`       — Resource Locks
* `fingerprint` — Environment Fingerprint und Known-Good-Versionen
* `experience`  — Experience Store mit CANDIDATE / VERIFIED / DEPRECATED
"""

from __future__ import annotations

__all__ = ["paths", "policy", "ledger", "locks", "fingerprint", "experience"]
__version__ = "0.1.0"
