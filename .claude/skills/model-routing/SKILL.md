---
name: model-routing
description: Choose a suitable available model capability and reasoning effort for a bounded task; escalate only when evidence shows reasoning limitations rather than missing access or broken tools.
---

Use balanced or reasoning as provider-neutral capability tiers, not model IDs. Resolve them to the current client's actually available subscription models. Never configure a paid API, automatic credits or an unavailable provider fallback.

Run `python bin/assistantctl.py plan --prompt "<task>"` from the repository root for a cheap advisory classification. It cannot change the running session's model or authorize a risky operation. Domain classification does not require delegation.

Use the current agent for routine work and existing workflows. Increase depth for ambiguous diagnosis, architecture and consequential decisions. A typo, permission denial, missing host or absent evidence needs diagnosis, not necessarily a stronger model. Delegate only a bounded part that benefits from specialization, parallelism or independent verification.

On uncertainty, obtain the missing evidence. On repeated reasoning failure, escalate with the user goal, versions, observed state, failed approaches and unmet criteria. Keep the established risk and verification gates. Never cycle through models without a corrected cause or a stopping condition.
