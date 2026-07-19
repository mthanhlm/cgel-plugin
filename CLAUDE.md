# CLAUDE.md

Guidance for Claude Code working in this repo. Keep it concise — it's read every session.

## What this repo is

The **CGEL plugin** (Contract-Gated Evidence Loop) — a Claude Code plugin that gates
edits behind sealed task contracts, records hash-chained verification evidence, and
closes tasks with an evidence-gated PASS. This repo **develops the plugin and also runs
under it**: a `.cgel/` directory governs work here, so non-trivial changes go through the
sealed-task flow (`/cgel:task`), not free edits.

Pure Python, **stdlib only** — no third-party dependencies, no build step, no package
manager. Target `python3` (3.x).

## Commands

The three registered checks (in `.cgel/registry.json`) are also mirrored by CI
(`.github/workflows/ci.yml`). Run them from the repo root:

```sh
# Tests (unittest discovery — never a hand-written module list). 500+ tests; suite
# must run >= 100 or it's treated as vacuous.
cd tests && python3 -m unittest discover -v

# Byte-compile the CLI and hook scripts
python3 -m compileall -q plugin/scripts plugin/bin/cgel

# JSON sanity — every manifest and schema must parse
python3 -c "import json,glob; [json.load(open(f)) for f in ['plugin/hooks/hooks.json','plugin/.claude-plugin/plugin.json','.claude-plugin/marketplace.json']+sorted(glob.glob('plugin/schemas/*.json'))]"
```

Under a sealed task, produce evidence with `cgel verify <check-id>` (running commands
yourself and pasting output creates **no** evidence).

## Layout

```
plugin/
  bin/cgel                 single-file CLI (~3k lines): contract lifecycle + evidence pipeline
  scripts/                 hook implementations + cgel_common.py (shared store/logic)
  hooks/hooks.json         wires the scripts to Claude Code lifecycle events
  skills/{task,loop,attest}/SKILL.md   the model-facing workflow
  agents/{challenger,explorer,verifier,worker}.md   read-only + worker subagents
  commands/task.md         the /cgel:task slash command
  rules/builtin.md         the built-in review rules (impact, correctness, root-cause, secret, ...)
  schemas/*.json           reference schemas (the shipped validator is hand-rolled, stdlib-only)
  .claude-plugin/plugin.json   name + version (bump on release)
.claude-plugin/marketplace.json   marketplace manifest
tests/                     unittest suite (discovery-based)
ARCHITECT.md               the authoritative architecture + decision log (D-NN)
README.md ROADMAP.md SECURITY.md
```

## Hook wiring (`plugin/hooks/hooks.json`)

- **PreToolUse** `Edit|Write|NotebookEdit` → `contract_gate.py` (scope gate: edits allowed
  only inside a sealed `scope.allowed`; governance paths stay read-only).
- **PreToolUse** `Bash` → `approval_gate.py` (verifies user approvals from the transcript)
  then `command_guard.py` (blocks writes that would bypass the gate).
- **PostToolUse** `Edit|Write|NotebookEdit|Bash` → `evidence_recorder.py` (hash chain).
- **Stop** → `stop_gate.py`; **SessionStart** → `session_start.py`.

## Code conventions

- **Output contract for `cgel`:** the last line of stdout is one machine-parseable
  decision line (e.g. `SEAL OK — ...`, `SUMMARY ... digest=...`); human detail and
  failures go to **stderr**. Exit codes: `0` ok, `1` denied/failed, `3` usage.
- Stdlib only — mirror the existing hand-rolled patterns (the contract validator is
  hand-written, not jsonschema). Don't add dependencies.
- Match the surrounding style: comments explain *why* a constraint exists, not *what* the
  line does. Test discovery is deliberate — add a test file, never edit a module list.
- Architecture decisions are numbered `D-NN` in `ARCHITECT.md`; reference them when a
  change touches settled design.

## Gotchas

- `.cgel/` and `.task/` are **gitignored**. The verification registry is local per clone,
  so a fresh clone starts with **no checks** and must register its own before evidence can
  exist. Registry changes go only through `cgel check add`, and only while no task is open.
- `.claude/skills/cgel-release/` is a repo-local skill, intentionally **not published**
  (gitignored).
- `cgel` is a Profile A tool: it packages logic but is **not a trust boundary**. The human
  anchor for a seal is the user approving the exact digest. Evidence is tamper-*evident*,
  not tamper-proof.
- Because this repo runs under CGEL, editing `plugin/**`, `.cgel/**`, `docs/standards/**`,
  or `docs/adr/**` needs a sealed task (and, for governance paths, a matching protected
  capability). Don't work around the gate with Bash writes — amend the contract and reseal.

## Git & releases

- **No AI attribution, ever.** Commits and PRs are authored solely by the configured git
  user. Do **not** add a `Co-Authored-By: Claude ...` trailer, a "Generated with Claude
  Code" footer, or any mention of Claude/Anthropic/AI in a commit message or PR body. The
  message is just the change: subject + body.
- Default branch is `main`; branch before opening a PR. Commit/push only when asked.
- Release with the `cgel-release` skill (bumps the version in `plugin/.claude-plugin/plugin.json`
  and runs a preflight that mirrors CI). Don't hand-edit the version for a release.
