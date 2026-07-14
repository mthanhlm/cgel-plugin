# CGEL — Contract-Gated Evidence Loop (Phase 0)

A Claude Code plugin implementing the CGEL v1.0 architecture (consensus
design, debate rounds v0.1→v1.0). Phase 0 ships the **Contract & Scope
Gate**: no application file changes without a sealed task contract, edits
only inside the sealed scope, governance paths protected, destructive
commands guarded.

## What Phase 0 enforces

| Invariant | Mechanism | Assurance (Profile A) |
|---|---|---|
| No Edit/Write before a sealed contract | `PreToolUse` gate (`scripts/contract_gate.py`) | HARD_ENFORCED for Edit/Write/NotebookEdit |
| Edits only inside `scope.allowed`, never `scope.forbidden` | same gate, sealed scope read from the state store (not the editable draft) | HARD_ENFORCED for Edit/Write/NotebookEdit |
| Governance paths (`.claude/**`, `.cgel/**`, `docs/standards/**`, `docs/adr/**`, hook config) read-only unless the sealed contract grants the matching protected capability | same gate | HARD_ENFORCED for Edit/Write/NotebookEdit |
| Seal binds the exact contract the user saw | digest ceremony: `cgel summary` → user approval → `cgel seal <id> --digest sha256:...` | HUMAN_GATED via the Bash permission prompt |
| User's uncommitted work is protected | dirty-tree check at seal (`--allow-dirty` only after explicit user confirmation) | EVIDENCE_GATED |
| No destructive git commands | `PreToolUse` Bash guard (`scripts/command_guard.py`), fail-closed | guardrail on the command string |
| No PASS without evidence | `cgel close --as PASS` is refused until the Phase 1 evidence pipeline exists | EVIDENCE_GATED by construction |

## Explicit limitations (Profile A honesty)

Read this before trusting the gate:

- **Bash writes are not blocked.** On an unsandboxed host the agent's Bash
  tool runs as the same OS user as these hooks. `sed`, `python`, `cp` can
  modify any file, including the state store. Everything here is
  **tamper-evident at best, never tamper-proof**. Hard guarantees require
  Profile B (container, separate OS user, sandboxed filesystem, CI runner).
- **The human seal anchor is the permission prompt.** `cgel seal` enforces
  the digest match, but only the user approving (or typing) the exact seal
  command makes it a human gate. Configure Bash permissions to `ask` for
  `cgel seal*` if you want this prompt guaranteed.
- **`--allow-dirty` is a consent flag, not a boundary.** The skill instructs
  the model to ask first; the CLI cannot verify a human answered.
- **The command guard is a regex guardrail**, evadable by indirection. It
  catches mistakes, not adversaries.
- **Governance-bundle digests arrive in Phase 1.** Until then, a
  mid-task change to rules/registry via Bash is not detected.

## Usage

```bash
# once per project (activates the gate for that repo)
cd your-project && /path/to/cgel-plugin/bin/cgel init

# task flow (the cgel:task skill walks the model through this)
#   1. draft  .task/contract.json
cgel validate                     # VALIDATE PASS — TASK-1 digest sha256:...
cgel summary                      # human summary + SUMMARY ... digest=... seal_mode=auto|human
cgel seal TASK-1 --digest sha256:...   # user approves this exact command
#   ... work happens inside scope.allowed ...
cgel status                       # STATUS SEALED task=TASK-1 ...
cgel close --as ESCALATE --reason "ready for user verification"
```

Kill switches: `CGEL_GATE=off`, `CGEL_GIT_GUARD=off` (env), or
`.cgel/config.json` `{"gate": "off"}` / `{"git_guard": "off"}`. Per-command
destructive-git override typed by the user: `CGEL_GIT=allow git ...`.

State lives in the **CGEL runtime state store**
(`$XDG_STATE_HOME/cgel/<repo-id>/` or `%LOCALAPPDATA%\cgel\...`; override
with `CGEL_STATE_DIR`). Profile A: tamper-evident only. `.task/` in the repo
is a gitignored scratch/mirror area, never the source of truth.

## Tests

```bash
cd tests && python3 -m unittest discover
```

Subprocess-level hook tests (JSON on stdin, assertions on exit code and
stderr), stdlib `unittest` only.

## Roadmap

- **Phase 1 — Evidence:** verification registry (check IDs), PostToolUse /
  PostToolUseFailure evidence recorder, hash chain, diff binding, governance
  bundle digests at seal, `cgel verify` / `cgel audit`, PASS validator.
- **Phase 2 — Loop Control:** iteration records, budgets, default-same
  failure guard, BLOCKED semantics, Stop continuation gate, resume.
- **Phase 3 — Semantic Layer:** read-only Verifier subagent, semantic rule
  IDs, frozen verifier trigger, sanitized attestation export.

Design record: see the CGEL v1.0 consolidated architecture document
(decision log D-1..D-34).
