# CGEL — Contract-Gated Evidence Loop

A Claude Code plugin implementing the CGEL v1.0 architecture (consensus
design, debate rounds v0.1→v1.0). All four MVP phases are implemented:

- **Phase 0 — Contract & Scope Gate:** no application file changes without
  a sealed task contract; edits only inside the sealed scope; governance
  paths protected; destructive commands guarded.
- **Phase 1 — Evidence:** the seal freezes the governance bundle (the
  measure); checks run through a verification registry and record
  hash-chained evidence bound to contract + bundle + workspace digests;
  `PASS` exists only when that evidence validates.
- **Phase 2 — Loop Control:** explicit iterations with hypotheses, budget
  accounting from the store, the default-same failure guard, BLOCKED
  semantics with user-only unblock, a bounded Stop gate, and a
  SessionStart resume summary.
- **Phase 3 — Semantic Layer:** semantic rules with IDs in
  `docs/standards/`, a verifier trigger frozen at seal, a structurally
  read-only Verifier subagent, blocking findings that stop PASS, and a
  sanitized attestation export.

## What Phase 1 adds

| Invariant | Mechanism | Assurance (Profile A) |
|---|---|---|
| The measure is frozen at seal | seal digests every governance file (`.cgel/**`, `.claude/**`, `docs/standards/**`, `docs/adr/**`, `hooks/**`); any change → task BLOCKED, reseal required | EVIDENCE_GATED, tamper-evident |
| `echo tests passed` is worthless | evidence exists only when `cgel verify <check-id>` runs a registry-defined command and records the result | EVIDENCE_GATED |
| Evidence can't be silently doctored | every record is hash-chained (`chain.prev`/`chain.hash`); `cgel audit` recomputes the chain | tamper-evident (same-principal store — not tamper-proof) |
| Evidence can't be reused across states | records bind contract digest, governance digest, workspace diff digest, and the hook-recorded edit counter; PASS requires exact match | EVIDENCE_GATED |
| No PASS without evidence | `cgel close --as PASS` runs the validator: fresh passing evidence for every `required_checks` entry of every acceptance criterion | EVIDENCE_GATED |
| Edits after evidence are visible | `PostToolUse` recorder appends edit events; stale evidence is rejected at PASS | EVIDENCE_GATED |

## What Phase 2 adds

| Invariant | Mechanism | Assurance (Profile A) |
|---|---|---|
| Every iteration is declared and decided | `cgel iterate open` (hypothesis + intended change) / `cgel iterate decide ADVANCE\|RETRY\|REPLAN\|ROLLBACK_ITERATION`; a second open without a decision is refused | EVIDENCE_GATED |
| A success cannot be claimed by asserting it | `ADVANCE` is refused unless every `--expected-checks` entry of the iteration has fresh passing evidence — so it cannot carry a failed check past the default-same guard | EVIDENCE_GATED |
| Budgets never widen silently | iteration/replan counts come from the chained store, limits from the sealed contract; exhaustion → BLOCKED; only `cgel unblock --add-*` (a USER action) extends | EVIDENCE_GATED |
| Repeating the same failure is stopped by a machine | default-same guard compares recorded failure signatures (check id + kind + diagnostic fingerprint): same signature after RETRY forces REPLAN, after REPLAN forces ESCALATE/ABORT; overrides need `--approved-by` | EVIDENCE_GATED |
| No silent stop mid-iteration | `Stop` hook blocks (exit 2) while an iteration is undecided — bounded to `stop_continuation_limit` (default 2) per task | GUIDANCE+bounded gate |
| Sessions resume, not restart | `SessionStart` hook injects a state summary (lifecycle, budgets, open iteration, last failure) from the store | GUIDANCE_ONLY |

## What Phase 3 adds

| Invariant | Mechanism | Assurance (Profile A) |
|---|---|---|
| Semantic rules are first-class | `docs/standards/*.md` blocks (`## SEC-1 — title`, `Blocking: yes`, `Applies-To:`); `cgel rules` lists them | EVIDENCE_GATED (they are in the sealed bundle) |
| The verifier trigger is frozen at seal | high risk / `ai.enabled` / `semantic_review: true` / blocking rules at medium risk → `semantic_verification.required` in the seal artifact | EVIDENCE_GATED |
| The verifier cannot touch the code | `agents/verifier.md` declares `tools: Read, Grep, Glob` only | HARD_ENFORCED (harness tool restriction) |
| Blocking findings stop PASS | `cgel semantic record` validates findings against known rule IDs, binds them to the workspace state, chains them; the PASS validator requires a fresh record with zero blocking findings | EVIDENCE_GATED |
| Disagreement goes to the human | verifier is block-only; the main agent may challenge once with evidence; unresolved → ESCALATE, never silent override | GUIDANCE + gate |
| Attestations are sanitized | export contains ids, statuses, digests — no raw output/logs; written to the state store, never committed by default | EVIDENCE_GATED |

## What Phase 0 enforces

| Invariant | Mechanism | Assurance (Profile A) |
|---|---|---|
| No Edit/Write before a sealed contract | `PreToolUse` gate (`scripts/contract_gate.py`) | HARD_ENFORCED for Edit/Write/NotebookEdit |
| Edits only inside `scope.allowed`, never `scope.forbidden` | same gate, sealed scope read from the state store (not the editable draft) | HARD_ENFORCED for Edit/Write/NotebookEdit |
| Governance paths (`.claude/**`, `.cgel/**`, `docs/standards/**`, `docs/adr/**`, hook config) read-only unless the sealed contract grants the matching protected capability | same gate | HARD_ENFORCED for Edit/Write/NotebookEdit |
| Seal binds the exact contract the user saw | digest ceremony: `cgel summary` → user approval → `cgel seal <id> --digest sha256:...` | HUMAN_GATED via the Bash permission prompt |
| User's uncommitted work is protected | dirty-tree check at seal (`--allow-dirty` only after explicit user confirmation) | EVIDENCE_GATED |
| No destructive git commands | `PreToolUse` Bash guard (`scripts/command_guard.py`), fail-closed | guardrail on the command string |
| No AI attribution in commits/PRs | `cgel init` sets `attribution.commit`/`pr`/`sessionUrl` to `""` in `.claude/settings.json`, so the harness never authors the trailer at all (covers `$EDITOR` and `--body-file`); the Bash guard additionally blocks a `git commit` / `gh pr create\|edit` whose text carries a `Co-Authored-By: Claude` trailer or generated-with footer typed inline; `SessionStart` injects the standing rule as the belt-and-braces third layer | HARD_ENFORCED (settings) + guardrail on the command string |

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
- **Attribution has three layers, and only the outermost is mechanical for
  every path.** `cgel init` empties `attribution.commit`/`pr`/`sessionUrl` in
  `.claude/settings.json`, so the *harness* never appends its own trailer —
  through any path, including a message composed in `$EDITOR` (`git commit`
  with no `-m`) or passed by file (`gh pr create --body-file`, `git commit
  -F`). That closes, for the harness-added trailer, the hole this bullet used
  to describe. What the setting does **not** cover is a model that deliberately
  *writes* `Co-Authored-By: Claude` into the message itself: the Bash guard
  catches that only when it appears inline in the `git commit -m` / `gh pr
  create|edit` command string, and is deliberately **narrow** — it matches the
  mechanical trailer/footer, not the words "Claude"/"Anthropic", so a repo can
  still legitimately commit *about* them (`docs: document Claude Code
  compatibility` is allowed). A trailer a model hand-writes via `$EDITOR` or
  `--body-file` is seen by neither the setting nor the guard; the injected rule
  is what covers that, and it is instruction-only. `.claude/settings.json` is
  meant to be committed, so the setting is the one attribution layer that
  survives a fresh clone.
- **The canary catches mistakes, not adversaries, and does not make the
  registry trustworthy.** `cgel check add` refuses a command that still exits
  0 in an empty directory, because such a check cannot be measuring your
  project (D-37). It raises the floor from "any non-empty string" to
  "something that breaks when the project breaks" — nothing more. A command
  can be built to fail in an empty directory and still verify nothing, and
  `--allow-unproven` registers one anyway (marked `unproven: true`). The
  yardstick is still authored by whoever runs `check add`. `cgel check doctor`
  now tests every registered check from **both** sides — it must fail in an
  empty directory (not vacuous) *and* pass in your working tree (not rotted) —
  so a check whose target was deleted or renamed is reported `cannot pass
  here` instead of the false `ok` the old one-sided canary gave it. Doctor
  cannot tell a rotted check from a genuinely broken project, so it says so
  rather than asserting rot; and `cgel check remove <id>` is the sanctioned way
  to retire one, between tasks only. None of this makes an authored-but-shallow
  check meaningful — it narrows the gap between doctor's verdict and reality,
  it does not close it.
- **The registry is local, never shared.** `cgel init` gitignores `.cgel/`,
  so the verification registry stays out of the project's git history
  (D-35). Two consequences: a fresh clone has no checks, so `cgel verify`
  has nothing to run and PASS is unreachable until someone registers them
  again; and the yardstick is per-machine and unreviewed, so the `echo tests
  passed` case is held off by the canary and the `cgel check add` permission
  prompt alone — not by code review. This is a deliberate trade of principle
  #3 ("the evaluated party does not hold the yardstick") for keeping the
  plugin out of your history.
- **The hash chain is recomputable by the same principal.** A determined
  local process could rewrite `evidence.jsonl` and re-chain it. `cgel
  audit` catches accidents and naive edits; hard integrity needs Profile B
  (store behind a boundary the agent principal cannot write).
- **Committing mid-task staleness:** the workspace digest includes `HEAD`,
  so a commit after `cgel verify` makes that evidence stale — re-run
  `cgel verify` after committing. This is deliberate (cheap, honest).
- **`cgel unblock` and failure overrides are user actions the CLI cannot
  authenticate.** The real anchor is the Bash permission prompt — set
  `cgel unblock*` and `cgel iterate decide *--override*` to `ask` if you
  want the prompt guaranteed.
- **Semantic findings are probabilistic.** The verifier is a model with
  read-only tools; `cgel semantic record` enforces schema, rule existence,
  and freshness — not truth. Critical rules deserve a deterministic
  scanner in the registry or human review.
- **The Stop gate is bounded, not absolute.** After
  `stop_continuation_limit` forced continuations (default 2) the agent may
  stop with an undecided iteration; the state store remembers.

## Installation

```bash
# add this repo as a plugin marketplace, then install the plugin
claude plugin marketplace add mthanhlm/cgel-plugin
claude plugin install cgel@cgel
```

The `cgel` CLI lands on your PATH automatically: on the first session
after install, the SessionStart hook symlinks `~/.local/bin/cgel` to the
plugin's `bin/cgel` (POSIX only; it never overwrites a file it does not
own; opt out with `CGEL_NO_SYMLINK=1`). Manual fallback — same thing by
hand:

```bash
ln -s ~/.claude/plugins/marketplaces/cgel/bin/cgel ~/.local/bin/cgel
```

Requirements: Claude Code with plugin support, Python 3.8+ (stdlib only),
git. Hooks, skills (`cgel:task`, `cgel:loop`, `cgel:attest`), agents
(`cgel:verifier`, `cgel:explorer`) and the `/cgel:task` command load in new
sessions after install.

CGEL is **opt-in per project**: nothing is gated until a repo contains a
`.cgel/` directory. Typing `/cgel:task <goal>` in an uninitialized repo
auto-initializes it (the skill runs `cgel init` and registers the
project's real checks via `cgel check add`).

Recommended permission setup (makes the human gates real prompts):

```json
{"permissions": {"ask": ["Bash(cgel seal*)", "Bash(cgel unblock*)"]}}
```

## Command reference

| Command | What it does |
|---|---|
| `cgel init` | activate CGEL for the project (`.cgel/`, `.task/`, registry stub; empties `attribution.*` in `.claude/settings.json`) |
| `cgel check add/list/doctor/remove` | register (refused if the command passes with no project present) / list / re-test every check from both sides — must fail empty *and* pass in-tree / remove a check (between tasks only) |
| `cgel validate` | schema-check `.task/contract.json` |
| `cgel summary` | normalized contract summary + digest (show this to the user) |
| `cgel seal <id> --digest <d>` | freeze contract + governance bundle; opens the edit gate |
| `cgel iterate open/decide` | declare an iteration / record ADVANCE, RETRY, REPLAN, ROLLBACK_ITERATION |
| `cgel verify <check-id>` | run a registered check, record hash-chained evidence |
| `cgel audit` | verify chains, seal bindings, governance bundle |
| `cgel rules` | list semantic rules from `docs/standards/` |
| `cgel semantic record` | validate + chain verifier findings from `.task/findings.json` |
| `cgel status` | one-line lifecycle status |
| `cgel unblock` | USER action: lift a budget block |
| `cgel attest` | export a sanitized attestation |
| `cgel close --as PASS\|ESCALATE\|ROLLED_BACK\|ABORT` | terminal status (PASS is validated) |

## Usage

```bash
# once per project (activates the gate for that repo)
cd your-project && cgel init
#   then register the project's checks in .cgel/registry.json:
#   {"checks": {"unit-tests": {"command": "npm test", "timeout_seconds": 600,
#               "success": {"exit_code": 0}, "kind": "test"}}}

# task flow (the cgel:task skill walks the model through this)
#   1. draft  .task/contract.json
cgel validate                     # VALIDATE PASS — TASK-1 digest sha256:...
cgel summary                      # human summary + SUMMARY ... digest=... seal_mode=auto|human
cgel seal TASK-1 --digest sha256:...   # user approves; freezes contract + governance bundle
#   ... work happens inside scope.allowed ...
#   ... the loop (cgel:loop skill) ...
cgel iterate open --hypothesis "H-1: ..." --intended-change "..." --expected-checks unit-tests
cgel verify unit-tests            # runs the registered command, records chained evidence
cgel iterate decide ADVANCE       # hypothesis held — needs fresh passing evidence for --expected-checks
#   or RETRY / REPLAN / ROLLBACK_ITERATION — guard + budgets enforced
cgel audit                        # AUDIT OK — evidence=N events=M chain=intact bundle=unchanged
cgel status                       # STATUS ACTIVE task=TASK-1 ... evidence=N

#   ... closing (cgel:attest skill) ...
cgel rules                        # semantic rules parsed from docs/standards/
#   run the read-only cgel:verifier subagent, save its JSON to .task/findings.json
cgel semantic record              # SEMANTIC OK — N finding(s), 0 blocking
cgel close --as PASS              # evidence + semantic validators; exports attestation
cgel close --as ESCALATE --reason "needs user verification"   # the honest fallback

# user-only interventions
cgel unblock --add-iterations 2   # lift a budget block (USER decision)
```

Kill switches: `CGEL_GATE=off`, `CGEL_GIT_GUARD=off` (env), or
`.cgel/config.json` `{"gate": "off"}` / `{"git_guard": "off"}`. Per-command
destructive-git override typed by the user: `CGEL_GIT=allow git ...` — which
also permits an attributed commit, if the user genuinely wants one.

The no-AI-attribution rule (injected instruction + commit/PR block) is on by
default in every CGEL project, task or not. Turn off just that rule with
`.cgel/config.json` `{"ai_attribution_guard": "off"}`; it leaves the
destructive-command rules intact. That switch governs only the two runtime
layers — it does **not** touch the `attribution.*` keys `cgel init` wrote to
`.claude/settings.json`, which suppress the harness trailer independently;
restore them by hand if you want the trailer back.

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

## Status & validation backlog

All four MVP phases (0–3) are implemented and tested. Remaining items are
prototype validation, not design (architecture doc §V-1..V-5): audit sink
portability/user-visibility, copy-in/patch-out with renames/binaries,
failure normalization across pytest/Jest/Cargo, PostToolUse payload
variance (isolated in the recorder adapter), and 3-way apply-back
conflicts. MCP interface for the control plane: decide with Phase 1 usage
data.

Design record: [ARCHITECT.md](ARCHITECT.md) — the signed-off CGEL v1.0
consolidated architecture (decision log D-1..D-34).
