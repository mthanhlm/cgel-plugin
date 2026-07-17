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
| Seal binds the exact contract the user saw | digest ceremony: `cgel summary` → one AskUserQuestion carrying the digest → user taps Approve → `cgel seal <id> --digest sha256:...` (the approval gate verifies the recorded answer and lets the seal through with no further prompt) | HUMAN_GATED via the harness-recorded question answer (tamper-evident; the permission prompt remains the harder anchor if you keep an `ask` rule and turn the gate off) |
| User's uncommitted work is protected | dirty-tree check at seal (`--allow-dirty` only after explicit user confirmation) | EVIDENCE_GATED |
| No destructive git commands | `PreToolUse` Bash guard (`scripts/command_guard.py`), fail-closed | guardrail on the command string |
| No AI attribution in commits/PRs | `cgel init` sets `attribution.commit`/`pr`/`sessionUrl` to `""` in `.claude/settings.json`, so the harness never authors the trailer at all (covers `$EDITOR` and `--body-file`); the Bash guard additionally blocks a `git commit` / `gh pr create\|edit` whose text carries a `Co-Authored-By: Claude` trailer or generated-with footer typed inline; `SessionStart` injects the standing rule as the belt-and-braces third layer | HARD_ENFORCED (settings) + guardrail on the command string |
| Evidence is bound to the code that produced it | every `cgel verify` record carries a `diff_digest` of the working tree; PASS refuses when it no longer matches | EVIDENCE_GATED — **and only when the workspace binding is live.** With no git the digest is a constant that equals itself forever, so evidence can never go stale. `cgel seal` warns, `cgel audit` prints `workspace=inert`, and the record carries `degraded`. |
| The sealed measure cannot move mid-task | the governance bundle (rules, registry, hook config) is digested at seal; a change moves the task to BLOCKED | EVIDENCE_GATED (tamper-evident) — **with two carve-outs, both deliberate.** `.claude/settings.local.json`'s `permissions` key is not measured (the harness rewrites it every time you approve a tool, so measuring it meant your own approval blocked every open task), and `bundle_exclude` globs drop paths you nominate. Excluded files stay edit-gated; `cgel seal` names them. |
| A blocking semantic finding cannot be erased | `close --as PASS` refuses a blocking→clean transition with no workspace change recorded between the two verifier runs | EVIDENCE_GATED |
| Every terminal status is recorded and explained | `cgel close` requires `--reason`, chains a close record, and exports an attestation for PASS, ESCALATE and ABORT alike | EVIDENCE_GATED |
| The user is told, in words, what a close means | `cgel close` prints one verbatim sentence for the model to relay | **GUIDANCE_ONLY** — the words can be printed; nobody can be made to say them |
| The gate you are told about is the gate that is running | hooks leave a liveness beacon; `cgel status` carries `gate=on\|off\|unobserved` | **DIAGNOSTIC** — `unobserved` means CGEL cannot see a hook, which is *not* proof one did not run. Absence of evidence, reported as absence. |

**Precondition for every row above.** CGEL activates per project, and a project is a directory containing `.cgel/`.

The file-level rows (the edit gate, the recorder) root at the **file being touched**, so they hold for any edit inside a project — including from a session opened above one.

The Bash-level rows (the git guard, the approval gate) root at the **session's working directory**. Open a session above your projects — at a monorepo root, say — and those rows do not hold for that session: nothing is watching the command line. This is a deliberate trade: rooting a Bash hook by scanning for projects underneath would mean a directory walk on every Bash call, and would be ambiguous the moment a monorepo holds two. Instead, `SessionStart` says so on the way in, naming the projects it found and how to address one:

```
cgel -C <project> status
```

`-C` addresses a project from anywhere and is gated exactly as if you were standing inside it.

## Approval by question

Privileged commands — `cgel seal`, `cgel unblock`, failure overrides,
`check add --force/--allow-unproven`, `check remove`, `--allow-dirty`,
**every `git push`** (config `{"push_gate": "off"}` opts out), and the
destructive git commands the guard blocks — run only when the session
transcript carries the user's recorded **AskUserQuestion** answer:

- the model asks one short plain-language question (goal, files, checks,
  risk) whose text contains the binding token — a seal's digest prefix, or
  the exact command in backticks for everything else;
- the user taps an option starting with **Approve** (any other answer,
  including free text, is not an approval);
- the `approval_gate` hook finds that answer in the transcript, consumes it
  (one approval, one command — except a seal approval, which stays valid
  for resealing the *same* digest after a governance-bundle change), and
  auto-allows the call so no second permission prompt fires. One gate, not
  two.

Without a matching approval the command is denied with instructions to ask
first; the user can always run the command themselves instead. Several
tasks may be open at once (see below), and every verb then takes
`--task <id>`.

Trust class, stated plainly: the transcript is written by the Claude Code
harness from a real UI interaction — a model cannot answer its own
question — but on a Profile A host it is a same-principal file like
everything else, so this anchor is **tamper-evident, not tamper-proof**.
If you want the hard prompt back: `.cgel/config.json`
`{"approval_gate": "off"}` and keep `ask` rules for `Bash(cgel seal*)` /
`Bash(cgel unblock*)`.

## Two tasks at once

The store keeps every open task, not one CURRENT pointer. Sealing a second
task while the first is open is allowed (the seal warns when the two
`scope.allowed` overlap), so one session can code while another answers a
question or starts new work in the same repo:

- draft the second contract at `.task/<id>.contract.json` and pass
  `--contract` to `summary`/`seal` — drafts stop fighting over one file;
- pass `--task <id>` on every verb once more than one task is open —
  unaddressed verbs refuse to guess, which is what used to let one session
  decide another session's iteration;
- the edit gate allows a path when ANY open task's sealed scope covers it,
  and says why per task when none does;
- the workspace is still shared: another task's edits stale your evidence
  unless your checks declare `watch` globs (below) — re-verify and move on;
- `cgel close` frees the matching draft, and a fresh seal of a previously
  closed task id archives the old run instead of inheriting its spent
  budgets.

## The production bar (built-in review rules)

Four rules ship with the plugin and merge into every project's rule set
(`cgel rules` lists them as `cgel-builtin`). **Two block and two advise**:

| Rule | Blocks? | What the verifier must actually do |
|---|---|---|
| `CGEL-IMPACT-1` — all impacted code updated | **yes** | grep for stale references and old call shapes of every changed symbol |
| `CGEL-SECRET-1` — no hardcoded secrets | **yes** | scan changed files for credential/token/password shapes |
| `CGEL-DEBT-1` — no new technical debt | advisory | find duplicated logic, dead code, workarounds where the root cause was in reach |
| `CGEL-COMMENT-1` — comments earn their place | advisory | flag narration, ownerless TODOs, commented-out code, debug prints |

The split is about **ground truth, not importance**. IMPACT-1 and SECRET-1
can be checked by searching — a stale call site is there or it is not — so
a finding is checkable and a block is arguable. DEBT-1 and COMMENT-1 are
judgements of taste about duplication and comment quality; blocking on
taste, at close, with an ungated ESCALATE as the only exit, is how a lint
gate earns itself a config flag turning it off. All four still run, are
recorded, and reach the human; only the first two can stop a PASS.

Because blocking rules always exist, **semantic verification is required at
medium+ risk in every CGEL repo**: the opus verifier runs, its findings are
recorded and chained, and a blocking finding stops PASS. But `risk.level`
has no default — the contract must state and argue one (see below), so
"medium+" is a claim the author makes, not a level they drift into.

Honesty: these are EVIDENCE_GATED model judgments — recorded, escalated to
the human on disagreement, not deterministic proofs. A project rule with
the same id replaces its built-in; `.cgel/config.json`
`{"builtin_rules": "off"}` removes them.

### The risk level is a claim, not a default

`risk.level` (`low` | `medium` | `high`) decides whether anything grades the
work: at `low`, no rule judges the change and no finding can stop PASS.
There is **no default** — a contract with no `risk`, no `level`, or no
`reasons` is rejected at `validate`, `summary` and `seal`. `cgel summary`
prints the machine's verdict above the digest you approve, in one of two
shapes:

```text
Semantic verification: REQUIRED (blocking rules present at risk.level=medium)
  the read-only verifier will judge this change against: CGEL-IMPACT-1, CGEL-SECRET-1
  a blocking finding stops PASS.

Semantic verification: NOT REQUIRED at risk.level=low — no rule will judge
this change and no finding can stop PASS. Only the registered checks grade it.
```

Two structural cases **floor the level to `high`** regardless of the claim,
because they are facts about the scope rather than opinions about the work:
the contract requests `protected_capabilities`, or `scope.allowed` reaches a
governance path (`.cgel/**`, `.claude/**`, `docs/standards/**`, `docs/adr/**`,
`hooks/**`). The summary says so and names the reason. The escape is a
tighter scope, not an argument — note that `docs/**` contains
`docs/standards/**` and therefore floors; `docs/guide/**` does not.

## Challenge the intent (before the seal)

The task skill's intake step now judges the request itself — "the best
change, not obedience". For design-shaped or medium/high-risk work, a
read-only opus **challenger** agent reviews the user's chosen approach
against the actual codebase: fit, production soundness, the true impact
surface (feeding a complete `scope.allowed`), and a better alternative
when one exists. If the user's design loses to an alternative the model
can defend, the user hears it in one question BEFORE sealing — and their
decision is recorded in the contract's `intent_review` field, which
`cgel summary` displays and warns about when missing at medium/high risk.
GUIDANCE + recorded artifact: the plugin cannot force good judgment, it
forces the judgment to happen and to leave a trace.

## Watch globs (path-scoped staleness)

By default any workspace change stales all evidence — honest, but it meant
a README edit re-ran a 35-second suite. A check may declare what it
actually measures:

```bash
cgel check add unit-tests --command "npm test" --watch "src/**,tests/**"
```

Evidence from a watched check goes stale only when a changed path matches
a watch glob (or when HEAD moves — a commit re-bases everything). No
`watch` keeps the old behavior exactly. The watch list is authored with
the check and trusted exactly as far as the command itself (D-37): a wrong
watch is a wrong yardstick, and doctor cannot see it.

## When you are stuck

CGEL is a set of controls, and a control that cannot be satisfied is a wedge.
There is always a legal way out; you never need to reach for the off switch.

| You are stuck because | The way out |
|---|---|
| the same failure keeps coming back, and both RETRY and REPLAN are refused | `cgel close --as ESCALATE --reason "..."` — a third plan against a failure two plans did not move is not a plan |
| the task went BLOCKED with an iteration open | `cgel iterate decide ROLLBACK_ITERATION` is legal while blocked |
| the governance bundle moved and the contract is unchanged | reseal the **same** digest — it needs no new approval |
| the budget is exhausted | only the user widens it: `cgel unblock --add-iterations <n>` |
| a check is registered but wrong, and every task is open | close the tasks, or seal a task with `protected_capabilities: ["modify-verification-registry"]` and `required_checks: []` — it closes ESCALATE by design, because its job is to change the measure, not to be measured by it |
| the scope is wrong | amend the contract and reseal with the user. Do not widen a change silently |
| the work genuinely cannot be finished | `cgel close --as ESCALATE --reason "..."` is a **normal** outcome, not a failure state. Every terminal status is recorded, attested and explained |

The one thing that is never the answer is `CGEL_GATE=off`. That is the user's
switch, not the model's.

## What it costs

CGEL spends tokens to buy evidence. Roughly, per task:

- the **ceremony** (draft, `cgel summary`, one approval question, `cgel seal`)
  is a few thousand tokens, once;
- each **iteration** adds an `iterate open` / `verify` / `iterate decide`
  round trip — small, but it is per iteration;
- the **challenger** (medium/high risk, before the seal) and the **verifier**
  (required at high risk, or `semantic_review: true`) are each a separate
  subagent read of the changed files. These are the expensive part, and they
  are pinned to Opus in the agent frontmatter because a cheap reviewer that
  misses things is worse than no reviewer.

So a `low`-risk task with two iterations is nearly free, and a `high`-risk
task with a wide scope and five iterations is not. That is the intended
shape: the cost tracks the claim. If you want the cheap path, argue `low`
honestly and accept that nothing will grade the work — the summary screen
says so in those words before you approve.

## Explicit limitations (Profile A honesty)

Read this before trusting the gate:

- **Bash writes are not blocked.** On an unsandboxed host the agent's Bash
  tool runs as the same OS user as these hooks. `sed`, `python`, `cp` can
  modify any file, including the state store. Everything here is
  **tamper-evident at best, never tamper-proof**. Hard guarantees require
  Profile B (container, separate OS user, sandboxed filesystem, CI runner).
- **The human seal anchor is the recorded question answer.** `cgel seal`
  enforces the digest match; the approval gate enforces that a matching
  AskUserQuestion answer exists in the transcript. That answer is written
  by the harness, not the model — but the transcript is a same-principal
  file, so the anchor is tamper-evident, not tamper-proof. The permission
  prompt (an `ask` rule on `Bash(cgel seal*)`, gate off) and the user
  typing the command themselves remain the harder anchors.
- **`--allow-dirty` is question-gated consent, not a boundary.** The
  approval gate requires the user's recorded answer approving the exact
  command; the CLI itself still cannot verify a human answered.
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
  authenticate.** The approval gate requires a recorded question answer
  quoting the exact command, consumed on use — same trust class as the
  seal anchor above. Keep `ask` rules (gate off) if you want the raw
  prompt instead.
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

The `cgel` CLI is linked into `~/.local/bin` automatically: on the first
session after install, the SessionStart hook symlinks `~/.local/bin/cgel`
to the plugin's `bin/cgel` (POSIX only; it never overwrites a file it does
not own; opt out with `CGEL_NO_SYMLINK=1`). `~/.local/bin` is **not** on
PATH by default on stock macOS/zsh — if `cgel` is not found after install,
add `export PATH="$HOME/.local/bin:$PATH"` to your shell profile. CGEL
detects an unreachable link at session start and hands the model the
absolute path, so a task runs either way. Manual fallback — same thing by
hand:

```bash
ln -s ~/.claude/plugins/marketplaces/cgel/plugin/bin/cgel ~/.local/bin/cgel
```

Requirements: Claude Code with plugin support, Python 3.8+ (stdlib only),
git. Hooks, skills (`cgel:task`, `cgel:loop`, `cgel:attest`), agents
(`cgel:verifier`, `cgel:explorer`) and the `/cgel:task` command load in new
sessions after install.

CGEL is **opt-in per project**: nothing is gated until a repo contains a
`.cgel/` directory. Typing `/cgel:task <goal>` in an uninitialized repo
auto-initializes it (the skill runs `cgel init` and registers the
project's real checks via `cgel check add`).

No permission setup is required: the approval gate carries the human
anchor by default (see *Approval by question*). If you prefer raw prompts,
turn the gate off and keep:

```json
{"permissions": {"ask": ["Bash(cgel seal*)", "Bash(cgel unblock*)"]}}
```

## Command reference

Every task-addressed verb takes `--task <id>` (required only when several
tasks are open). `validate`/`summary`/`seal` take `--contract <path>` for
parallel drafts.

Every verb also takes a top-level `cgel -C <dir>` (`--directory`), which
addresses the project at `<dir>` instead of the current directory — useful
from a monorepo root, where the Bash-level guards are not active (see
[the precondition](#what-phase-0-enforces)). It names a directory, never a
file, and the approval gate treats `cgel -C <dir> seal ...` exactly as it
treats `cgel seal ...` from inside.

| Command | What it does |
|---|---|
| `cgel init` | activate CGEL for the project (`.cgel/`, `.task/`, registry stub; empties `attribution.*` in `.claude/settings.json`) |
| `cgel check add/list/doctor/remove` | register (refused if the command passes with no project present; `--watch` globs scope staleness) / list / re-test every check from both sides — must fail empty *and* pass in-tree / remove a check (between tasks only) |
| `cgel validate` | schema-check the contract draft |
| `cgel summary` | validate + normalized contract summary + digest (put the digest in the approval question) |
| `cgel seal <id> --digest <d>` | freeze contract + governance bundle; opens the edit gate; resealing the same digest reuses its approval |
| `cgel iterate open/decide` | declare an iteration (`--change`, `--expect`) / record ADVANCE, RETRY, REPLAN, ROLLBACK_ITERATION — prefixes work (ADV, RET…); `decide --verify` freshly runs the expected checks first |
| `cgel verify <id>... [--required]` | run registered check(s) in one call, record hash-chained evidence per check; `--required` covers every check the criteria name |
| `cgel audit` | verify chains, seal bindings, governance bundle |
| `cgel rules` | list semantic rules from `docs/standards/` |
| `cgel semantic record` | validate + chain verifier findings from `.task/findings.json` |
| `cgel status` | lifecycle status — all open tasks, or one with `--task` |
| `cgel unblock` | USER action: lift a budget block, or widen a budget before it runs out |
| `cgel attest` | export a sanitized attestation |
| `cgel schema <name>` | print a shipped schema (task-contract, evidence, findings, attestation) |
| `cgel close --as PASS\|ESCALATE\|ROLLED_BACK\|ABORT` | terminal status (PASS is validated); frees the matching draft |

## Usage

```bash
# once per project (activates the gate for that repo)
cd your-project && cgel init
#   then register the project's checks in .cgel/registry.json:
#   {"checks": {"unit-tests": {"command": "npm test", "timeout_seconds": 600,
#               "success": {"exit_code": 0}, "kind": "test"}}}

# task flow (the cgel:task skill walks the model through this)
#   1. draft  .task/contract.json
cgel summary                      # validates + prints summary + SUMMARY ... digest=... semantic=required|none
#   2. ONE AskUserQuestion carrying the digest; the user taps Approve
cgel seal TASK-1 --digest sha256:... \
  && cgel iterate open --hypothesis "H-1: ..." --change "..." --expect unit-tests
#   ... work happens inside scope.allowed (cgel:loop skill) ...
cgel iterate decide ADVANCE --verify   # runs the expected checks fresh, then decides — one call
#   or RETRY / REPLAN / ROLLBACK_ITERATION — guard + budgets enforced
cgel verify unit-tests lint --required # any number of checks in one roundtrip
cgel audit                        # AUDIT OK — evidence=N events=M chain=intact bundle=unchanged
cgel status                       # STATUS ACTIVE task=TASK-1 ... evidence=N

#   ... closing (cgel:attest skill) ...
cgel rules                        # semantic rules parsed from docs/standards/
#   run the read-only cgel:verifier subagent, save its JSON to .task/findings.json
cgel semantic record              # SEMANTIC OK — N finding(s), 0 blocking
cgel close --as PASS              # evidence + semantic validators; exports attestation; frees the draft
cgel close --as ESCALATE --reason "needs user verification"   # the honest fallback

# user-approved interventions (the model asks, the gate verifies the answer)
cgel unblock --add-iterations 2   # lift a budget block, or widen one early

# parallel second task in the same repo
cgel summary --contract .task/TASK-2.contract.json
cgel seal TASK-2 --digest sha256:... --contract .task/TASK-2.contract.json
cgel verify unit-tests --task TASK-2   # --task on every verb while two are open
```

Kill switches: `CGEL_GATE=off`, `CGEL_GIT_GUARD=off`,
`CGEL_APPROVAL_GATE=off` (env), or `.cgel/config.json` `{"gate": "off"}` /
`{"git_guard": "off"}` / `{"approval_gate": "off"}`. Per-command
destructive-git override: `CGEL_GIT=allow git ...` — which also permits an
attributed commit, if you genuinely want one. It exempts only the one command
it prefixes, not the rest of the line. Honesty: this is a **string, not an
identity**. It is meant for you to type, but nothing distinguishes you typing
it from the model typing it — which is why no block message mentions it. It
is a convenience for the user, not a boundary against the model.

Governance-bundle churn: file digests are cached in the state store by a
stat key — `(mtime_ns, size)` for a seal made before v0.13, and
`(schema, mtime_ns, size, ctime_ns, inode)` for one made since. At either
schema a member touched within the last couple of seconds is rehashed
rather than trusted, because filesystem timestamp granularity is coarser
than a write: two same-size rewrites inside one tick are indistinguishable
by stat, and a cache that believed them served the old digest for a file
that had changed.

`.cgel/config.json` `{"bundle_exclude": ["glob", ...]}` drops churn-prone
paths (a gitignored repo-local skill, say) from the sealed measure — they
stay edit-gated, but changing them no longer voids open seals. The config
file itself is always digested, so an exclusion cannot arrive invisibly
mid-task, and both `cgel seal` and `cgel audit` name the excluded files (the
first few, with a count of the rest).

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
consolidated architecture, plus the post-v1.0 amendments D-35..D-47 that
record every change since. [ROADMAP.md](ROADMAP.md) holds the parts that
were designed and never built — it is a wish list, kept apart from the
design record on purpose.
