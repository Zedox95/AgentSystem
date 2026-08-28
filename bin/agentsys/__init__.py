"""agentsys — core library of the control plane.

Modules:

* `paths`       — central paths and control-plane protection
* `policy`      — deterministic policy guard (ALLOW / ASK / DENY)
* `ledger`      — run ledger, task state machine, checkpointing
* `locks`       — resource locks
* `fingerprint` — environment fingerprint and known-good versions
* `experience`  — experience store with CANDIDATE / VERIFIED / DEPRECATED
"""

from __future__ import annotations

__all__ = ["paths", "policy", "ledger", "locks", "fingerprint", "experience"]
__version__ = "0.1.0"
