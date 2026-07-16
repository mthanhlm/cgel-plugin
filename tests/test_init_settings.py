"""cgel init makes the no-AI-attribution guarantee harness-enforced.

The command guard only sees an inline `git commit -m "..."`. A message composed
in $EDITOR or passed with `--body-file` never appears in the Bash string, so the
guard is blind to it — README documents exactly this hole. `attribution.<k>: ""`
in .claude/settings.json stops the harness itself from ever adding the trailer,
covering the cases the guard cannot. init writes it, but only ever by a
non-destructive merge: settings the user already has must survive untouched.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from hookrunner import CLI, PLUGIN_ROOT


def settings_path(repo):
    return os.path.join(repo, ".claude", "settings.json")


class InitSettingsTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="cgel-initset-")
        self.state = tempfile.mkdtemp(prefix="cgel-initset-state-")
        subprocess.run(
            ["git", "init", "-q"], cwd=self.repo, check=True, capture_output=True
        )
        self.env = {"CGEL_STATE_DIR": self.state}

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)

    def init(self):
        merged = os.environ.copy()
        merged.update(self.env)
        return subprocess.run(
            [sys.executable, CLI, "init"],
            cwd=self.repo,
            env=merged,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def write_settings(self, text):
        os.makedirs(os.path.join(self.repo, ".claude"), exist_ok=True)
        with open(settings_path(self.repo), "w", encoding="utf-8") as fh:
            fh.write(text)

    def settings(self):
        with open(settings_path(self.repo), encoding="utf-8") as fh:
            return json.load(fh)


class FromNothing(InitSettingsTestCase):
    def test_init_creates_settings_with_the_attribution_keys_emptied(self):
        proc = self.init()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        attribution = self.settings()["attribution"]
        for key in ("commit", "pr", "sessionUrl"):
            self.assertEqual(attribution[key], "", "%s not emptied" % key)


class PreservesWhatIsAlreadyThere(InitSettingsTestCase):
    def test_unrelated_keys_survive(self):
        self.write_settings(json.dumps({"model": "opus", "permissions": {"ask": []}}))
        self.init()
        data = self.settings()
        self.assertEqual(data["model"], "opus")
        self.assertEqual(data["permissions"], {"ask": []})
        self.assertEqual(data["attribution"]["commit"], "")

    def test_a_user_set_attribution_value_is_never_overwritten(self):
        # Someone who deliberately wants a trailer keeps it — init only fills
        # keys that are absent, it does not impose a policy over a stated one.
        self.write_settings(
            json.dumps({"attribution": {"commit": "Co-authored-by: me"}})
        )
        self.init()
        self.assertEqual(
            self.settings()["attribution"]["commit"], "Co-authored-by: me"
        )


class DegradesRatherThanClobbers(InitSettingsTestCase):
    def test_malformed_settings_is_left_intact_and_init_still_succeeds(self):
        garbage = "{ this is not valid json "
        self.write_settings(garbage)
        proc = self.init()
        self.assertEqual(proc.returncode, 0, "init failed on a bad settings.json")
        with open(settings_path(self.repo), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), garbage, "clobbered the user's file")


class Idempotent(InitSettingsTestCase):
    def test_second_init_does_not_rewrite_settings(self):
        self.init()
        first = os.path.getmtime(settings_path(self.repo))
        before = self.settings()
        self.init()
        self.assertEqual(self.settings(), before)
        # nothing to add the second time → no write at all
        self.assertEqual(os.path.getmtime(settings_path(self.repo)), first)


class TheClaimIsBackedByCode(unittest.TestCase):
    def test_cli_empties_all_three_attribution_keys(self):
        with open(os.path.join(PLUGIN_ROOT, "bin", "cgel"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(
            'ATTRIBUTION_KEYS = ("commit", "pr", "sessionUrl")', text
        )


if __name__ == "__main__":
    unittest.main()
