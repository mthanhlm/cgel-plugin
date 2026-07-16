"""Approval-by-question — subprocess tests for approval_gate.py and the
command_guard approval path.

The fixture transcript imitates what the Claude Code harness records for an
answered AskUserQuestion: a user-type entry whose message carries the
tool_result block and whose toolUseResult carries questions + answers. The
gates must allow exactly the approved action, once, and deny the rest.
"""

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from hookrunner import run_hook

DIGEST = "sha256:" + "ab12cd34ef56" + "0" * 52
DIGEST_PREFIX = DIGEST[: len("sha256:") + 12]
SEAL_COMMAND = "cgel seal TASK-A1 --digest %s" % DIGEST


def transcript_entry(question, answer, when=None, sidechain=False, tool_id="toolu_1"):
    return {
        "type": "user",
        "isSidechain": sidechain,
        "timestamp": (when or datetime.now(timezone.utc)).isoformat(),
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": "Your questions have been answered",
                }
            ],
        },
        "toolUseResult": {
            "questions": [
                {
                    "question": question,
                    "options": [
                        {"label": answer, "description": ""},
                        {"label": "Cancel", "description": ""},
                    ],
                    "multiSelect": False,
                }
            ],
            "answers": {question: answer},
        },
    }


class ApprovalTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="cgel-repo-")
        self.state = tempfile.mkdtemp(prefix="cgel-state-")
        os.makedirs(os.path.join(self.repo, ".cgel"))
        self.transcript = os.path.join(self.state, "transcript.jsonl")
        self.env = {"CGEL_STATE_DIR": self.state}

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)

    def write_transcript(self, *entries):
        with open(self.transcript, "w", encoding="utf-8") as fh:
            for entry in entries:
                fh.write(json.dumps(entry) + "\n")

    def gate(self, command, script="approval_gate.py"):
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": self.repo,
            "transcript_path": self.transcript,
        }
        return run_hook(script, payload, env=self.env)

    # ------------------------------------------------------- approval_gate

    def test_seal_without_approval_denied_with_instructions(self):
        self.write_transcript()
        code, _, err = self.gate(SEAL_COMMAND)
        self.assertEqual(code, 2)
        self.assertIn("AskUserQuestion", err)
        self.assertIn(DIGEST_PREFIX, err)

    def test_seal_with_recorded_approval_allowed_no_prompt(self):
        self.write_transcript(
            transcript_entry("Seal this? digest %s…" % DIGEST_PREFIX, "Approve")
        )
        code, out, err = self.gate(SEAL_COMMAND)
        self.assertEqual(code, 0, err)
        decision = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "allow")

    def test_answer_must_start_with_approve(self):
        self.write_transcript(
            transcript_entry("Seal this? digest %s…" % DIGEST_PREFIX, "Cancel")
        )
        code, _, _ = self.gate(SEAL_COMMAND)
        self.assertEqual(code, 2)

    def test_question_must_carry_the_digest(self):
        self.write_transcript(transcript_entry("Seal something else?", "Approve"))
        code, _, _ = self.gate(SEAL_COMMAND)
        self.assertEqual(code, 2)

    def test_sidechain_answers_do_not_count(self):
        self.write_transcript(
            transcript_entry(
                "Seal this? digest %s…" % DIGEST_PREFIX, "Approve", sidechain=True
            )
        )
        code, _, _ = self.gate(SEAL_COMMAND)
        self.assertEqual(code, 2)

    def test_stale_approval_expires(self):
        old = datetime.now(timezone.utc) - timedelta(hours=25)
        self.write_transcript(
            transcript_entry("Seal this? digest %s…" % DIGEST_PREFIX, "Approve", when=old)
        )
        code, _, _ = self.gate(SEAL_COMMAND)
        self.assertEqual(code, 2)

    def test_seal_approval_reusable_for_reseal_of_same_digest(self):
        self.write_transcript(
            transcript_entry("Seal this? digest %s…" % DIGEST_PREFIX, "Approve")
        )
        code, _, _ = self.gate(SEAL_COMMAND)
        self.assertEqual(code, 0)
        code, out, _ = self.gate(SEAL_COMMAND)  # reseal, same contract digest
        self.assertEqual(code, 0)
        self.assertIn("allow", out)

    def test_unblock_binds_to_the_exact_command(self):
        command = "cgel unblock --add-iterations 3"
        self.write_transcript(
            transcript_entry("Extend budget? `%s`" % command, "Approve")
        )
        code, out, _ = self.gate(command)
        self.assertEqual(code, 0)
        self.assertIn("allow", out)
        # a consumed exact-command approval does not cover a second run
        code, _, _ = self.gate(command)
        self.assertEqual(code, 2)

    def test_unblock_approval_does_not_leak_to_other_amounts(self):
        self.write_transcript(
            transcript_entry(
                "Extend budget? `cgel unblock --add-iterations 1`", "Approve"
            )
        )
        code, _, _ = self.gate("cgel unblock --add-iterations 99")
        self.assertEqual(code, 2)

    def test_ungated_cgel_commands_pass_silently(self):
        self.write_transcript()
        for command in ("cgel status", "cgel verify unit-tests", "cgel summary"):
            code, out, _ = self.gate(command)
            self.assertEqual(code, 0)
            self.assertEqual(out.strip(), "")

    def test_gated_verbs_all_require_approval(self):
        self.write_transcript()
        for command in (
            "cgel iterate decide RETRY --override-reason x --approved-by u",
            "cgel check add t --command 'pytest' --force",
            "cgel check add t --command 'pytest' --allow-unproven",
            "cgel check remove t",
            "cgel seal T-1 --digest %s --allow-dirty" % DIGEST,
        ):
            code, _, _ = self.gate(command)
            self.assertEqual(code, 2, command)

    def test_outside_cgel_repo_stands_aside(self):
        plain = tempfile.mkdtemp(prefix="cgel-plain-")
        try:
            payload = {
                "tool_name": "Bash",
                "tool_input": {"command": SEAL_COMMAND},
                "cwd": plain,
                "transcript_path": self.transcript,
            }
            code, _, _ = run_hook("approval_gate.py", payload, env=self.env)
            self.assertEqual(code, 0)
        finally:
            shutil.rmtree(plain, ignore_errors=True)

    def test_kill_switches(self):
        self.write_transcript()
        code, _, _ = self.gate(SEAL_COMMAND, script="approval_gate.py")
        self.assertEqual(code, 2)
        with open(
            os.path.join(self.repo, ".cgel", "config.json"), "w", encoding="utf-8"
        ) as fh:
            json.dump({"approval_gate": "off"}, fh)
        code, _, _ = self.gate(SEAL_COMMAND)
        self.assertEqual(code, 0)
        os.unlink(os.path.join(self.repo, ".cgel", "config.json"))
        env_payload = {
            "tool_name": "Bash",
            "tool_input": {"command": SEAL_COMMAND},
            "cwd": self.repo,
            "transcript_path": self.transcript,
        }
        merged = dict(self.env)
        merged["CGEL_APPROVAL_GATE"] = "off"
        code, _, _ = run_hook("approval_gate.py", env_payload, env=merged)
        self.assertEqual(code, 0)

    def test_malformed_stdin_fails_open(self):
        code, _, _ = run_hook(
            "approval_gate.py", None, env=self.env, raw_stdin="{not json"
        )
        self.assertEqual(code, 0)

    # ------------------------------------------------- command_guard + git

    def test_destructive_git_with_approval_allowed(self):
        command = "git push --force origin main"
        self.write_transcript(
            transcript_entry("Force push? `%s`" % command, "Approve")
        )
        code, out, err = self.gate(command, script="command_guard.py")
        self.assertEqual(code, 0, err)
        decision = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "allow")

    def test_destructive_git_without_approval_blocked_and_points_at_question(self):
        self.write_transcript()
        code, _, err = self.gate("git reset --hard HEAD~1", script="command_guard.py")
        self.assertEqual(code, 2)
        self.assertIn("AskUserQuestion", err)

    def test_attribution_has_no_approval_path(self):
        command = 'git commit -m "x\n\nCo-Authored-By: Claude <noreply@anthropic.com>"'
        self.write_transcript(
            transcript_entry("Commit? `%s`" % command, "Approve")
        )
        code, _, err = self.gate(command, script="command_guard.py")
        self.assertEqual(code, 2)
        self.assertIn("ai-attribution", err)


if __name__ == "__main__":
    unittest.main()
