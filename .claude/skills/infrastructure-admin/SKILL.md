---
name: infrastructure-admin
description: Wählt für eine Infrastrukturaufgabe den zuverlässigsten Weg - Proxmox-API, qm und pct, SSH und Bash, Docker, Pterodactyl-API, Ansible oder OpenTofu - und kennt den tatsächlichen Ausbaustand dieser Umgebung. Einsetzen für Linux-Server, VMs, Container, Gameserver-Hosting, Netzwerkdienste und Infrastrukturdiagnose.
allowed-tools: Bash(python C:\AgentSystem\bin\agentctl.py *), Read, Grep, Glob
---

# Infrastrukturaufgaben richtig routen

## Tatsächlicher Ausbaustand — Stand 2026-08-21

Gemessen, nicht angenommen:

- **Kein** eigener Proxmox-Host
- **Kein** eigener Linux-Server
- **Kein** SSH-Zugang — weder `~/.ssh` noch Schlüssel noch `known_hosts`
- **Pterodactyl** existiert nur als Web-Panel eines Anbieters, keine eigene
  Installation, kein Wings-Zugriff
- Docker Desktop 29.7.2 installiert, **Engine gestoppt**, WSL-Distro
  `docker-desktop` Stopped

Erfinde keine Hosts, keine IPs und keine Zugangsdaten. Ist ein Ziel nicht
erreichbar oder nicht konfiguriert, melde das — das ist ein Ergebnis, keine
Blockade.

## Methodenwahl

**Proxmox:** API → `qm`/`pct` → SSH → Playwright → Computer Use.
Die API ist strukturiert und verifizierbar; die WebUI ist es nicht.

**Linux allgemein:** SSH mit Bash, `systemctl`, `journalctl`, Paketmanager,
Docker, Git, `curl`, `ss`/`netstat`, direkte Dateiverwaltung. Keine GUI, wenn
die CLI zuverlässiger ist.

**Pterodactyl:** API → SSH/Wings → Dateien und CLI → Playwright → Computer Use.

**Konfigurationsmanagement:** Ansible für reproduzierbare, idempotente
Serverkonfiguration. Der Control Node gehört auf **Linux**, nicht auf Windows.
Solange kein Linux-Host existiert, ist Ansible kein verfügbarer Weg.

**Infrastructure as Code:** OpenTofu nur, wenn es echten Vorteil bringt — nicht
für jede kleine VM-Änderung. Bei Nutzung: `fmt` → `validate` → `plan` → Plan
tatsächlich lesen → `apply` → objektive Verifikation.

## Schichten trennen

Host, Hypervisor, Container, Anwendung, Gameserver, Netzwerk. Ein Fehler in
einer Schicht wird nicht in einer anderen repariert. Bestimme immer zuerst, in
welcher Schicht das Problem tatsächlich sitzt.

Die spielspezifische Ebene — Mods, Plugins, Eggs, Startparameter, Welten —
gehört dem `gaming-agent`, nicht hierher.

## Vor Änderungen validieren

Konfiguration wird **vor** Reload oder Restart geprüft:
`nginx -t` · `sshd -t` · `docker compose config` · `visudo -c` ·
`systemd-analyze verify` · `named-checkconf`

Ein Neustart mit kaputter Konfiguration kostet den Zugang zum System.

## Lockout-Risiko

Bei SSH-, Firewall- und Netzwerkänderungen an entfernten Hosts gilt immer:
Kann diese Änderung mich aussperren? Wenn ja, brauchst du vorher einen
Out-of-Band-Zugang (Konsole des Hypervisors, IPMI, Anbieter-Panel) oder eine
zeitgesteuerte Rücknahme.

Ein `iptables -F` oder eine geänderte `sshd_config` ohne zweiten Zugangsweg ist
**R3**.

## Risikoklassen

| Aufgabe | Klasse |
|---|---|
| Inventar, Status, Logs, `qm list`, API-GET | R0 |
| Dienst neu starten, Container neu starten | R1 |
| Pakete, Firewall, VM-Ressourcen, Netzwerk, Compose-Änderung, Storage-Erweiterung | R2 |
| VM-/Container-Löschung, Datenträger, Datenbank-Löschung, Datenmigration, WAN/Firewall mit Lockout-Risiko | R3 |

Ab R2 zuerst `preflight-change` mit Snapshot oder Backup, danach
`verify-change`.

## Verifikation

Health, Konnektivität, Persistenz **über einen Neustart hinweg**, und die
relevanten Logs seit dem Änderungszeitpunkt.

Für Pterodactyl konkret: Serverobjekt vorhanden · Node korrekt · Allocation
korrekt · Wings erreichbar · Container läuft · Ports offen · Limits gesetzt ·
Startup-Log ohne kritische Fehler · **der Gameserver antwortet tatsächlich**.

„Container läuft" ist kein Nachweis, dass der Dienst funktioniert.

## Erfahrung

```bash
python C:\AgentSystem\bin\agentctl.py exp best --key infra.<aufgabenart>
python C:\AgentSystem\bin\agentctl.py exp record --key infra.<aufgabenart> --method "proxmox-api:<endpunkt>" --success --duration <ms>
```
