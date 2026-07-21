"""`cgel roadmap` — the planning store that is never part of the sealed measure.

The invariants that matter here are the two halves of the design: writes go
only through the verb (direct edits stay gated as a governance path), and a
write never moves the governance bundle digest (so recording an idea cannot
BLOCK an open seal).
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

from hookrunner import run_cli, run_hook, decision_line, SCRIPTS_DIR
from test_skill_prose import skill_text

sys.path.insert(0, SCRIPTS_DIR)
import cgel_common as C  # noqa: E402

CONTRACT = {
    "task": {"id": "TASK-R1", "type": "feature", "goal": "Roadmap fixture"},
    "acceptance_criteria": [
        {"id": "AC-1", "description": "works", "required_checks": ["unit-tests"]}
    ],
    "scope": {"allowed": ["src/**"]},
    "risk": {"level": "low", "reasons": ["fixture: exercises the roadmap verb"]},
}


class RoadmapFixture(unittest.TestCase):
    """Fixture only — no tests, so subclasses do not re-run each other's."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="cgel-repo-")
        self.state = tempfile.mkdtemp(prefix="cgel-state-")
        os.makedirs(os.path.join(self.repo, ".cgel"))
        os.makedirs(os.path.join(self.repo, ".task"))
        self.env = {"CGEL_STATE_DIR": self.state}
        with open(
            os.path.join(self.repo, ".cgel", "registry.json"), "w", encoding="utf-8"
        ) as fh:
            json.dump({"checks": {"unit-tests": {"command": "true"}}}, fh)

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)

    def cli(self, *args):
        return run_cli(list(args), cwd=self.repo, env=self.env)

    def roadmap_path(self):
        return os.path.join(self.repo, C.ROADMAP_REL_PATH)

    def seal(self):
        with open(
            os.path.join(self.repo, ".task", "contract.json"), "w", encoding="utf-8"
        ) as fh:
            json.dump(CONTRACT, fh)
        code, out, err = self.cli("summary")
        self.assertEqual(code, 0, err)
        digest = decision_line(out).split("digest=")[1].split()[0]
        code, out, err = self.cli("seal", CONTRACT["task"]["id"], "--digest", digest)
        self.assertEqual(code, 0, out + err)


class RoadmapVerbTestCase(RoadmapFixture):

    def test_add_creates_file_and_assigns_ids(self):
        code, out, _ = self.cli("roadmap", "add", "ship the dashboard")
        self.assertEqual(code, 0)
        self.assertEqual(decision_line(out), "ROADMAP ADDED — R-1 (idea)")
        code, out, _ = self.cli(
            "roadmap", "add", "v2 milestone", "--kind", "milestone"
        )
        self.assertEqual(code, 0)
        self.assertEqual(decision_line(out), "ROADMAP ADDED — R-2 (milestone)")
        with open(self.roadmap_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(set(data["entries"]), {"R-1", "R-2"})
        self.assertEqual(data["entries"]["R-1"]["status"], "open")
        self.assertEqual(data["next_id"], 3)

    def test_add_rejects_empty_text_and_unknown_kind(self):
        code, out, _ = self.cli("roadmap", "add", "   ")
        self.assertEqual(code, 1)
        self.assertIn("ROADMAP DENIED", decision_line(out))
        code, out, _ = self.cli("roadmap", "add", "x", "--kind", "sprintlog")
        self.assertEqual(code, 1)
        self.assertIn("kind must be one of", decision_line(out))

    def test_verification_recipe_kind(self):
        code, out, _ = self.cli(
            "roadmap",
            "add",
            "build: make; up: docker compose up; e2e: POST /orders then check the orders table",
            "--kind",
            "verification-recipe",
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            decision_line(out), "ROADMAP ADDED — R-1 (verification-recipe)"
        )

    def test_list_hides_done_unless_all(self):
        self.cli("roadmap", "add", "first")
        self.cli("roadmap", "add", "second")
        self.cli("roadmap", "done", "R-1")
        code, out, err = self.cli("roadmap", "list")
        self.assertEqual(code, 0)
        self.assertEqual(decision_line(out), "ROADMAP LIST — 1 open, 1 done")
        self.assertNotIn("R-1", err)
        self.assertIn("R-2", err)
        code, _, err = self.cli("roadmap", "list", "--all")
        self.assertEqual(code, 0)
        self.assertIn("R-1", err)
        self.assertIn("(done)", err)

    def test_done_unknown_id_denied(self):
        code, out, _ = self.cli("roadmap", "done", "R-9")
        self.assertEqual(code, 1)
        self.assertIn("no entry 'R-9'", decision_line(out))

    def test_done_twice_is_not_an_error(self):
        self.cli("roadmap", "add", "x")
        self.assertEqual(self.cli("roadmap", "done", "R-1")[0], 0)
        code, out, _ = self.cli("roadmap", "done", "R-1")
        self.assertEqual(code, 0)
        self.assertEqual(decision_line(out), "ROADMAP DONE — R-1")

    def test_show_prints_full_text(self):
        self.cli("roadmap", "add", "line one\nline two")
        code, out, err = self.cli("roadmap", "show", "R-1")
        self.assertEqual(code, 0)
        self.assertIn("line one\nline two", err)
        self.assertEqual(decision_line(out), "ROADMAP SHOW — R-1 (idea, open)")

    def test_corrupt_file_refused_and_preserved(self):
        with open(self.roadmap_path(), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        code, out, _ = self.cli("roadmap", "add", "x")
        self.assertEqual(code, 1)
        self.assertIn("ROADMAP DENIED", decision_line(out))
        with open(self.roadmap_path(), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "{not json")

    def test_next_id_recomputed_when_missing(self):
        with open(self.roadmap_path(), "w", encoding="utf-8") as fh:
            json.dump(
                {"entries": {"R-7": {"kind": "idea", "text": "x", "status": "open"}}},
                fh,
            )
        code, out, _ = self.cli("roadmap", "add", "y")
        self.assertEqual(code, 0)
        self.assertEqual(decision_line(out), "ROADMAP ADDED — R-8 (idea)")

    def test_schema_prints_valid_json(self):
        code, out, _ = self.cli("schema", "roadmap")
        self.assertEqual(code, 0)
        body = "\n".join(out.splitlines()[:-1])
        self.assertEqual(json.loads(body)["title"], "CGEL Roadmap")


class RoadmapMeasureTestCase(RoadmapFixture):

    def setUp(self):
        super().setUp()
        # governance_bundle runs in-process here and keys its stat cache off
        # CGEL_STATE_DIR; point it at this test's store and restore after.
        prior = os.environ.get("CGEL_STATE_DIR")
        os.environ["CGEL_STATE_DIR"] = self.state
        if prior is None:
            self.addCleanup(os.environ.pop, "CGEL_STATE_DIR", None)
        else:
            self.addCleanup(os.environ.__setitem__, "CGEL_STATE_DIR", prior)

    def test_bundle_excludes_roadmap_at_every_schema(self):
        self.cli("roadmap", "add", "an idea")
        self.assertTrue(os.path.isfile(self.roadmap_path()))
        for schema in (1, C.BUNDLE_SCHEMA):
            bundle = C.governance_bundle(self.repo, schema=schema)
            self.assertNotIn(
                C.ROADMAP_REL_PATH, [m["path"] for m in bundle["members"]]
            )

    def test_roadmap_write_does_not_move_bundle_digest(self):
        before = C.governance_bundle(self.repo)["digest"]
        self.cli("roadmap", "add", "recorded mid-task")
        after = C.governance_bundle(self.repo)["digest"]
        self.assertEqual(before, after)

    def test_mid_task_add_does_not_block_the_seal(self):
        self.seal()
        code, out, _ = self.cli("roadmap", "add", "an idea during a sealed task")
        self.assertEqual(code, 0, out)
        code, out, err = self.cli(
            "iterate",
            "open",
            "--hypothesis",
            "H-1: fixture",
            "--change",
            "fixture",
            "--expect",
            "unit-tests",
        )
        self.assertEqual(code, 0, out + err)
        self.assertNotIn("BLOCKED", decision_line(out))

    def test_direct_edit_stays_gated(self):
        self.seal()
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": self.roadmap_path()},
            "cwd": self.repo,
        }
        code, _, err = run_hook("contract_gate.py", payload, env=self.env)
        self.assertEqual(code, 2)
        self.assertIn("modify-governance", err)


class RoadmapProseTestCase(unittest.TestCase):
    """The workflow is carried by skill prose; untested prose is a wish."""

    def test_task_skill_teaches_the_roadmap(self):
        text = skill_text("task")
        self.assertIn("cgel roadmap list", text)
        self.assertIn("cgel roadmap add", text)
        self.assertIn("verification-recipe", text)
        self.assertIn("never part of the sealed measure", text)

    def test_task_skill_states_planner_executor_split(self):
        text = skill_text("task")
        self.assertIn("faster, cheaper model", text)
        self.assertIn("never delegated", text)

    def test_loop_skill_consults_and_converts(self):
        text = skill_text("loop")
        self.assertIn("cgel roadmap add", text)
        self.assertIn("verification-recipe", text)
        # The registry is frozen mid-task; the conversion must be told to wait.
        self.assertIn("between tasks turn the recipe into registered checks", text)


if __name__ == "__main__":
    unittest.main()
