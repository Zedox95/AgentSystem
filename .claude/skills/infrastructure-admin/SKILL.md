---
name: infrastructure-admin
description: Chooses the most reliable route for an infrastructure task - Proxmox API, qm and pct, SSH and Bash, Docker, Pterodactyl API, Ansible, or OpenTofu - and knows the actual state of this environment. Use for Linux servers, VMs, containers, game server hosting, network services, and infrastructure diagnostics.
allowed-tools: Bash(python C:\AgentSystem\bin\agentctl.py *), Read, Grep, Glob
---

# Routing infrastructure tasks correctly

## Actual state of the environment — as of 2026-08-21

Measured, not assumed:

- **No** own Proxmox host
- **No** own Linux server
- **No** SSH access — neither `~/.ssh` nor keys nor `known_hosts`
- **Pterodactyl** exists only as a provider's web panel, no own
  installation, no Wings access
- Docker Desktop 29.7.2 installed, **engine stopped**, WSL distro
  `docker-desktop` Stopped

Don't invent hosts, IPs, or credentials. If a target is unreachable or not
configured, report that — it's a result, not a blocker.

## Choosing a method

**Proxmox:** API → `qm`/`pct` → SSH → Playwright → computer use.
The API is structured and verifiable; the web UI is not.

**Linux in general:** SSH with Bash, `systemctl`, `journalctl`, package
manager, Docker, Git, `curl`, `ss`/`netstat`, direct file management. No GUI
when the CLI is more reliable.

**Pterodactyl:** API → SSH/Wings → files and CLI → Playwright → computer use.

**Configuration management:** Ansible for reproducible, idempotent server
configuration. The control node belongs on **Linux**, not Windows. As long
as no Linux host exists, Ansible is not an available route.

**Infrastructure as code:** OpenTofu only when it brings real benefit — not
for every small VM change. When used: `fmt` → `validate` → `plan` → actually
read the plan → `apply` → objective verification.

## Separate the layers

Host, hypervisor, container, application, game server, network. A fault in
one layer is not fixed in another. Always determine first which layer the
problem actually sits in.

The game-specific layer — mods, plugins, eggs, startup parameters, worlds —
belongs to the `gaming-agent`, not here.

## Validate before changes

Configuration is checked **before** reload or restart:
`nginx -t` · `sshd -t` · `docker compose config` · `visudo -c` ·
`systemd-analyze verify` · `named-checkconf`

Restarting with a broken configuration costs access to the system.

## Lockout risk

For SSH, firewall, and network changes on remote hosts, always ask: could
this change lock me out? If so, you need an out-of-band access path first
(hypervisor console, IPMI, provider panel) or a timed rollback.

An `iptables -F` or a changed `sshd_config` without a second access path is
**R3**.

## Risk classes

| Task | Class |
|---|---|
| Inventory, status, logs, `qm list`, API GET | R0 |
| Restart a service, restart a container | R1 |
| Packages, firewall, VM resources, network, compose changes, storage expansion | R2 |
| VM/container deletion, disk deletion, database deletion, data migration, WAN/firewall with lockout risk | R3 |

From R2 up, run `preflight-change` first with a snapshot or backup, then
`verify-change`.

## Verification

Health, connectivity, persistence **across a restart**, and the relevant
logs since the time of the change.

Specifically for Pterodactyl: server object present · node correct ·
allocation correct · Wings reachable · container running · ports open ·
limits set · startup log free of critical errors · **the game server
actually responds**.

"Container is running" is not proof that the service works.

## Experience

```bash
python C:\AgentSystem\bin\agentctl.py exp best --key infra.<task-type>
python C:\AgentSystem\bin\agentctl.py exp record --key infra.<task-type> --method "proxmox-api:<endpoint>" --success --duration <ms>
```
