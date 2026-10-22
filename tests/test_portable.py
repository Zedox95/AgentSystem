"""Behavior checks for fresh installs, sessions, imports and provider adapters."""

from __future__ import annotations

import concurrent.futures
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
RUNTIME = tempfile.TemporaryDirectory(prefix="agentsys-portable-")
os.environ["AGENTSYSTEM_ROOT"] = str(Path(RUNTIME.name) / "runtime")
os.environ["AGENTSYSTEM_VAULT"] = str(Path(RUNTIME.name) / "vault")
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

from agentsys import ledger, paths, workflow, knowledge  # noqa: E402
from agentsys.contracts import KnowledgeCandidate, ContractError, ensure_no_secret  # noqa: E402
from agentsys.memory_import import import_file  # noqa: E402
import setup_agent as setup  # noqa: E402

spec = importlib.util.spec_from_file_location("codex_hook", ROOT / "adapters/codex/hook.py")
codex_hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(codex_hook)


class PortableTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="case-")
        self.addCleanup(self.directory.cleanup)
        self.tmp = Path(self.directory.name)

    def fixture(self, name="Different User — Agent System"):
        root = self.tmp / name
        shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(
            ".git", "state", "__pycache__", ".codex", ".agents", ".agentsystem.local.json"))
        return root

    def test_session_isolation_atomic_write_and_legacy(self):
        identifiers = ["one/../../session", "two:opaque?session"]
        ledger.write_checkpoint({"goal": "legacy"})
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda sid: ledger.write_checkpoint({"goal": sid}, sid), identifiers))
        for sid in identifiers:
            self.assertEqual(ledger.read_checkpoint(sid)["goal"], sid)
            ledger.checkpoint_path(sid).relative_to(paths.CHECKPOINTS_DIR)
        self.assertIsNone(ledger.read_checkpoint("third-unrelated-session"))
        self.assertEqual(ledger.read_checkpoint()["goal"], "legacy")
        ledger.checkpoint_path(identifiers[0]).unlink()
        self.assertIsNotNone(ledger.read_checkpoint(identifiers[1]))
        with self.assertRaises(ValueError):
            ledger.write_checkpoint({}, "")

    def test_session_hook_does_not_load_other_tasks(self):
        sid = "hook-own-session"
        ledger.write_checkpoint({"goal": "other-private-goal"}, "other-hook-session")
        result = subprocess.run([sys.executable, str(ROOT / ".claude/hooks/session_start.py")],
                                input=json.dumps({"session_id": sid, "hook_event_name": "SessionStart"}),
                                capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("other-private-goal", result.stdout)
        ledger.write_checkpoint({"goal": "own-goal", "next_step": "continue"}, sid)
        output = codex_hook.handle({"hook_event_name": "SessionStart", "session_id": sid})
        self.assertIn("own-goal", json.dumps(output))
        self.assertNotIn("other-private-goal", json.dumps(output))
        for missing_id in ({}, {"session_id": None}, {"session_id": ""}):
            missing = subprocess.run([sys.executable, str(ROOT / ".claude/hooks/session_start.py")],
                                     input=json.dumps({"hook_event_name": "SessionStart", **missing_id}),
                                     capture_output=True, text=True, encoding="utf-8", timeout=15)
            self.assertEqual(missing.returncode, 0, missing.stderr)
            self.assertEqual(missing.stdout, "")

    def test_checkpoint_redacts_structured_secrets_without_corrupting_json(self):
        ledger.write_checkpoint({"goal": "password=do-not-store", "password": "hidden",
                                 "nested": [{"api-key": "hidden-too"}]}, "redacted-session")
        saved = ledger.read_checkpoint("redacted-session")
        self.assertEqual(saved["password"], "<REDACTED>")
        self.assertNotIn("do-not-store", json.dumps(saved))
        self.assertNotIn("hidden", json.dumps(saved))
        protected = ledger.redact_structured({key: "synthetic-value" for key in (
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_API_KEY", "Authorization", "privateKey", "bearer")})
        self.assertEqual(set(protected.values()), {"<REDACTED>"})
        self.assertEqual(ledger.redact_structured({"token_budget": 2000}), {"token_budget": 2000})
        with self.assertRaises(ContractError):
            ensure_no_secret({"password": "hidden"})
        with self.assertRaises(ValueError):
            ledger.write_checkpoint({"goal": "x" * 70000}, "oversized")

    def test_fresh_install_idempotent_unrelated_settings_and_rollback(self):
        root = self.fixture()
        vault = self.tmp / "Own Vault"
        (root / ".codex").mkdir()
        config = root / ".codex/config.toml"
        config.write_text('model_reasoning_effort = "medium"\n', encoding="utf-8")
        before = (root / ".claude/settings.json").read_bytes()
        installed = setup.install(root, ["claude", "codex", "chatgpt"], vault)
        self.assertEqual(installed["status"], "CONFIGURED")
        self.assertEqual(installed["hooks_active"], "not_verified")
        self.assertTrue((vault / "01 Inbox").is_dir())
        self.assertTrue((root / ".agents/skills/evidence-research/SKILL.md").is_file())
        self.assertIn('model_reasoning_effort = "medium"', config.read_text())
        self.assertNotIn("sandbox_mode", (root / ".codex/agents/verification-agent.toml").read_text())
        self.assertEqual(setup.install(root, ["claude", "codex", "chatgpt"], vault)["status"], "UNCHANGED")
        self.assertEqual(setup.doctor(root)["status"], "PASS")
        verifier = (root / ".claude/agents/verification-agent.md").read_text()
        self.assertNotIn("C:/AgentSystem", verifier)
        self.assertIn(root.as_posix(), verifier)
        setup.rollback(root, Path(installed["backup"]))
        self.assertEqual((root / ".claude/settings.json").read_bytes(), before)
        self.assertEqual(config.read_text(), 'model_reasoning_effort = "medium"\n')
        self.assertFalse((root / ".agentsystem.local.json").exists())

    def test_manual_edit_is_preserved_and_conflicts_are_preflighted(self):
        root = self.fixture()
        vault = self.tmp / "vault"
        first = setup.install(root, ["codex"], vault)
        target = root / ".agents/skills/evidence-research/SKILL.md"
        target.write_text("manual changes", encoding="utf-8")
        original = (root / ".codex/config.toml").read_bytes()
        with self.assertRaisesRegex(ValueError, "manually changed"):
            setup.install(root, ["codex"], vault)
        self.assertEqual(target.read_text(), "manual changes")
        self.assertEqual((root / ".codex/config.toml").read_bytes(), original)
        with self.assertRaisesRegex(ValueError, "changed since setup"):
            setup.rollback(root, Path(first["backup"]))

    def test_two_profiles_use_own_vaults(self):
        one, two = self.fixture("first"), self.fixture("second")
        setup.install(one, ["codex"], self.tmp / "first-vault")
        setup.install(two, ["codex"], self.tmp / "second-vault")
        self.assertNotIn("first-vault", (two / ".codex/config.toml").read_text())
        self.assertNotIn(str(one), (two / ".codex/hooks.json").read_text())
        self.assertIn("second-vault", (two / ".codex/config.toml").read_text())

    def test_reconfigure_vault_preserves_mixed_hook_groups_and_disconnects_all_clients(self):
        root = self.fixture()
        one, two = self.tmp / "vault-A", self.tmp / "vault-B"
        setup.install(root, ["claude", "codex"], one)
        hooks_path = root / ".codex/hooks.json"
        hooks = json.loads(hooks_path.read_text())
        hooks["hooks"]["Stop"][0]["hooks"].append({"type": "command", "command": "echo custom"})
        hooks_path.write_text(json.dumps(hooks), encoding="utf-8")
        setup.install(root, ["claude"], two)
        settings = json.loads((root / ".claude/settings.json").read_text())
        self.assertEqual(settings["env"]["AGENTSYSTEM_VAULT"], str(two))
        self.assertNotIn(str(one), " ".join(settings["permissions"]["allow"]))
        self.assertIn("echo custom", hooks_path.read_text())
        self.assertIn("vault-B", (root / ".codex/config.toml").read_text())
        setup.install(root, ["claude"], None)
        disconnected = json.loads((root / ".claude/settings.json").read_text())
        self.assertNotIn("AGENTSYSTEM_VAULT", disconnected["env"])
        self.assertNotIn("agentsystem_memory", (root / ".codex/config.toml").read_text())
        self.assertNotIn("shared-memory", json.loads((root / ".mcp.json").read_text())["mcpServers"])

    def test_optional_playwright_can_be_added_after_first_setup(self):
        root = self.fixture()
        setup.install(root, ["claude"], None)
        self.assertNotIn("playwright", json.loads((root / ".mcp.json").read_text())["mcpServers"])
        cli = root / "adapters/playwright/node_modules/@playwright/mcp/cli.js"
        cli.parent.mkdir(parents=True)
        cli.write_text("// fixture only", encoding="utf-8")
        setup.install(root, ["claude"], None)
        self.assertIn("playwright", json.loads((root / ".mcp.json").read_text())["mcpServers"])

    def test_custom_optional_mcp_is_preserved(self):
        root = self.fixture()
        mcp_path = root / ".mcp.json"
        config = json.loads(mcp_path.read_text())
        custom = {"command": "npx", "args": ["-y", "@playwright/mcp@custom"]}
        config["mcpServers"]["playwright"] = custom
        mcp_path.write_text(json.dumps(config), encoding="utf-8")
        setup.install(root, ["claude"], None)
        self.assertEqual(json.loads(mcp_path.read_text())["mcpServers"]["playwright"], custom)

    @unittest.skipUnless(os.name == "nt", "Windows setup wrapper")
    def test_windows_powershell_wrapper_and_repeated_cli(self):
        root = self.fixture()
        command = ["powershell", "-NoProfile", "-File", str(root / "setup.ps1"), "-NonInteractive", "-SkipVault"]
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)
        if completed.returncode and "AuthorizationManager" in completed.stderr:
            # Respect host script policy. Exercise the documented Python path
            # instead of bypassing the machine's execution policy.
            self.assertFalse((root / ".agentsystem.local.json").exists())
            completed = subprocess.run([sys.executable, str(root / "bin/setup_agent.py"), "install", "--skip-vault"],
                                       capture_output=True, text=True, encoding="utf-8", timeout=45)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("CONFIGURED", completed.stdout)
        repeated = subprocess.run([sys.executable, str(root / "bin/setup_agent.py"), "install"],
                                  capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(json.loads(repeated.stdout)["status"], "UNCHANGED")

    def test_setup_failure_rolls_back_partial_writes(self):
        root = self.fixture()
        before = (root / ".claude/settings.json").read_bytes()
        original_atomic = setup.atomic
        def fail_one(path, data):
            if path == root / ".mcp.json":
                raise OSError("simulated disk error")
            original_atomic(path, data)
        with mock.patch.object(setup, "atomic", side_effect=fail_one):
            with self.assertRaisesRegex(OSError, "simulated"):
                setup.install(root, ["claude"], self.tmp / "vault")
        self.assertEqual((root / ".claude/settings.json").read_bytes(), before)
        self.assertFalse((root / ".agentsystem.local.json").exists())
        self.assertFalse((root / "state/setup.lock").exists())

    def test_import_preview_pending_dedup_and_no_vault_writes(self):
        source = self.tmp / "memories.json"
        source.write_text(json.dumps({"memories": ["I prefer concise answers", "I prefer concise answers"]}), encoding="utf-8")
        preview = import_file(source)
        self.assertEqual(preview["status"], "PREVIEW")
        self.assertEqual(len(preview["records"]), 1)
        self.assertEqual(preview["duplicates"], 1)
        staged = import_file(source, stage=True)
        candidate = json.loads((paths.KNOWLEDGE_PENDING_DIR / (staged["records"][0]["candidate_id"] + ".json")).read_text())
        self.assertEqual(candidate["status"], "needs_review")
        self.assertEqual(candidate["confidence"], "low")
        self.assertEqual(staged["vault_writes"], 0)
        duplicate_export = self.tmp / "another-export.json"
        duplicate_export.write_text(json.dumps(["I prefer concise answers"]), encoding="utf-8")
        self.assertEqual(import_file(duplicate_export, stage=True)["duplicates"], 1)

    def test_conversation_import_ignores_assistant_and_rejects_recognized_secrets(self):
        source = self.tmp / "conversations.json"
        source.write_text(json.dumps([{"mapping": {
            "a": {"message": {"author": {"role": "assistant"}, "content": {"parts": ["Unverified assistant claim"]}}},
            "u": {"message": {"author": {"role": "user"}, "content": {"parts": ["I am learning networking"]}}},
            "s": {"message": {"author": {"role": "user"}, "content": {"parts": ["password=do-not-store-this"]}}},
        }}]), encoding="utf-8")
        result = import_file(source)
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["rejected"], 1)
        self.assertNotIn("do-not-store", json.dumps(result))

    def test_work_plan_keeps_small_tasks_small_and_preserves_risk(self):
        simple = workflow.plan("Explain what a variable is")
        self.assertEqual(simple["default_extra_agents"], 0)
        self.assertFalse(simple["independent_verifier"])
        current = workflow.plan("Compare current backup software with sources")
        self.assertIn("evidence-research", current["skills"])
        destructive = workflow.plan("Delete the database", risk="R0")
        self.assertEqual(destructive["risk_hint"], "R3")
        self.assertTrue(destructive["requires_explicit_approval"])

    def test_codex_adapter_documented_payloads_and_policy_denials(self):
        denied = codex_hook.handle({"hook_event_name": "PreToolUse", "tool_name": "PowerShell",
                                   "tool_input": {"command": "Format-Volume -DriveLetter D"}})
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        asked = codex_hook.handle({"hook_event_name": "PreToolUse", "tool_name": "PowerShell",
                                  "tool_input": {"command": "Stop-Service -Name Spooler"}})
        self.assertEqual(asked["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertNotIn("ask", asked["hookSpecificOutput"].values())
        patch = codex_hook.handle({"hook_event_name": "PreToolUse", "tool_name": "apply_patch",
                                  "cwd": str(ROOT), "tool_input": {"command": "*** Begin Patch\n*** Update File: AGENTS.md\n*** End Patch"}})
        self.assertEqual(patch["hookSpecificOutput"]["permissionDecision"], "deny")
        for name in (".codex/hooks.json", ".codex/config.toml", ".agentsystem.local.json",
                     "adapters/codex/hook.py", ".agents/skills/evidence-research/SKILL.md"):
            protected = codex_hook.handle({"hook_event_name": "PreToolUse", "tool_name": "apply_patch",
                                          "cwd": str(ROOT), "tool_input": {"command": f"*** Update File: {name}"}})
            self.assertEqual(protected["hookSpecificOutput"]["permissionDecision"], "deny", name)
        prompt = codex_hook.handle({"hook_event_name": "UserPromptSubmit", "prompt": "Compare current software with official sources"})
        self.assertIn("evidence-research", json.dumps(prompt))
        self.assertIsNone(codex_hook.handle({"hook_event_name": "UserPromptSubmit", "prompt": "thanks"}))

    def test_memory_search_uses_managed_facts_not_private_prose_or_source_priority_alone(self):
        vault = self.tmp / "managed-vault"
        vault.mkdir()
        candidate = KnowledgeCandidate(entity="search-fixture", fact_key="server.version", value="26.2",
            status="current", confidence="high", source_type="user_confirmed", source_ref="isolated fixture",
            valid_from="2026-10-22", last_verified="2026-10-22")
        submitted = knowledge.submit(candidate)
        task_id = ledger.create_task("Search fixture", "R1")
        decision = knowledge.approve(submitted["candidate_id"], vault_root=vault, task_id=task_id, expected_sha256="NEW")
        note = vault / decision["target_note"]
        note.write_text(note.read_text() + "\nprivate-unmanaged-prose\n", encoding="utf-8")
        matches = knowledge.search(vault, "26.2")
        self.assertEqual(len(matches), 1)
        self.assertIn("26.2", matches[0]["excerpt"])
        self.assertNotIn("private-unmanaged-prose", matches[0]["excerpt"])
        self.assertEqual(knowledge.search(vault, "private-unmanaged-prose"), [])
        self.assertEqual(knowledge.search(vault, "completely-unrelated-query"), [])

    def test_memory_mcp_handshake_and_guarded_capture_readback(self):
        vault = self.tmp / "isolated-vault"
        vault.mkdir()
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "memory_capture_verified", "arguments": {
                    "entity": "portable-fixture", "fact_key": "test.setting", "value": "own-user-data",
                    "status": "current", "confidence": "high", "source_type": "user_confirmed",
                    "source_ref": "isolated test user statement", "valid_from": "2026-10-22",
                    "last_verified": "2026-10-22", "target_note": "01 Inbox/portable-fixture.md"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
                "name": "memory_search", "arguments": {"entity": "portable-fixture"}}},
        ]
        completed = subprocess.run([sys.executable, str(ROOT / "adapters/memory/memory_mcp.py")],
                                   input="\n".join(json.dumps(message) for message in messages) + "\n",
                                   capture_output=True, text=True, encoding="utf-8", timeout=30,
                                   env={**os.environ, "AGENTSYSTEM_ROOT": str(self.tmp / "mcp-state"), "AGENTSYSTEM_VAULT": str(vault)})
        self.assertEqual(completed.returncode, 0, completed.stderr)
        responses = {message["id"]: message["result"] for message in map(json.loads, completed.stdout.splitlines())}
        names = {tool["name"] for tool in responses[2]["tools"]}
        self.assertIn("memory_capture_verified", names)
        capture = responses[3]
        self.assertFalse(capture.get("isError"), capture)
        self.assertEqual(capture["structuredContent"]["completion"], "COMMITTED")
        self.assertEqual(len(responses[4]["structuredContent"]["matches"]), 1)
        self.assertIn("own-user-data", (vault / "01 Inbox/portable-fixture.md").read_text())


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PortableTests)
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(suite)
    print(json.dumps({"status": "PASS" if result.wasSuccessful() else "FAIL",
                      "tests": result.testsRun,
                      "failures": [text for _, text in result.failures + result.errors]}, ensure_ascii=False, indent=2))
    sys.exit(0 if result.wasSuccessful() else 1)
