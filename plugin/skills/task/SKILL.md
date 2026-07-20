---
name: task
description: CGEL task lifecycle — intake a request, draft a task contract, get the user's approval with one question, work inside the sealed scope, close with an honest terminal status. Use when starting any non-trivial change in a CGEL-enabled repo (a `.cgel/` directory exists).
user-invocable: false
---

# CGEL task

You are opening a task under the Contract-Gated Evidence Loop. The edit gate
is closed until a contract is sealed; do not fight the gate — feed it.

Run every `cgel` command yourself. The user approves through the
AskUserQuestion tool; they never have to type a command, and you never have
to wait at a permission prompt when an approval is on record.

## 0. Is this even a task?

A question, advice, a review, or any read-only request needs NO contract,
no `cgel init`, and no ceremony — just answer it. Open a task only when
files will change. When in doubt, answer first and offer the task second.

## 1. Repo not initialized yet?

If there is no `.cgel/` directory and the user explicitly invoked
`/cgel:task`, set the project up for them instead of bouncing the request:

0. First check you are not simply rooted above one: if `SessionStart` named
   projects below this directory, the user probably means one of them. Every
   verb takes `cgel -C <dir>` to address a project from outside it. Ask
   before initializing a second project at a parent of an existing one.
1. Run `cgel init` (creates `.cgel/`, `.task/`, a registry stub, and
   gitignores `.task/`).
2. Discover the project's real checks — test/build/lint commands from
   `package.json`, `Makefile`, `pyproject.toml`, CI config — and register
   each one, with `--watch` globs scoping what each check measures:
   `cgel check add unit-tests --command "npm test" --kind test --watch "src/**,tests/**"`
   Registry changes go ONLY through `cgel check add` — never Edit/Write
   on `.cgel/**` (governance path) and never Bash file redirection.
3. Tell the user in one short list what was initialized and which checks
   were registered, then continue with intake below.
4. If the repo has no `CLAUDE.md` yet, write one now — this is the one
   moment it is writable without a sealed scope, because no task governs the
   repo yet (the gate exempts root `CLAUDE.md`/`CLAUDE.local.md` only here;
   the moment you seal the first task it follows normal scope like any
   other file). Read enough of the codebase to write a CONCISE, tailored
   CLAUDE.md at the repo root: the build/test/lint commands a new session
   cannot guess, the code style that departs from the language default, the
   architecture in a few lines, the non-obvious gotchas, and repo etiquette.
   Keep it under ~200 lines and omit anything a competent reader already
   assumes — it is read every session, so bloat costs every session. Tell
   the user you wrote it and that they can refine it or regenerate it with
   `/init`.

`cgel check add` works only while no task is open; once sealed, the
registry is frozen inside the governance bundle.

## 2. Intake — and challenge the intent

Classify the request: task type (bug-fix, feature, refactor, ...), primary
domain, risk level, and whether any **protected capability** is involved
(`modify-governance`, `modify-verification-registry`, `modify-hook-policy`,
`modify-evaluation-baseline`, `external-write`, `dependency-change`,
`schema-migration`, `public-api-change`). Inspect the repo read-only as
needed — use the `cgel:explorer` subagent for broad recon instead of
flooding your own context. If anything about the user's intent is genuinely
unclear — the goal, the scope, the acceptance bar, or which of several
approaches they want — INTERVIEW them before drafting: ask focused questions
through AskUserQuestion and let their answers shape the contract, instead of
guessing and encoding the guess. One good round of questions beats five
rounds of building the wrong thing. Reserve it for real ambiguity — a
request whose intent is already plain does not need an interview, and asking
anyway is its own noise — but when the intent is unclear the contract must
not silently reinterpret their intent.

Then judge the intent itself. Your job is the best change, not obedience:
the user may hand you a design that does not fit this codebase or will not
survive production, and following it blindly is a failure of the task. For
design-shaped work or medium/high risk, run the read-only `cgel:challenger`
subagent with the request, the user's chosen approach, and the repo — it
returns fit, risks, the true impact surface, and a better alternative when
one exists.

- If the user's chosen design is worse than an alternative you can defend,
  say so BEFORE sealing: one AskUserQuestion, both options in plain words,
  the recommended one first. Never implement a design you believe is wrong
  without having said so — and never swap in your own design without their
  answer.
- Record the outcome in the contract's `intent_review` field (concerns +
  `alternative_chosen`); `cgel summary` shows it at the seal and warns
  when it is missing on medium/high risk.
- Use the challenger's impact surface to draw `scope.allowed` COMPLETE:
  every caller, config, test, and doc the change touches belongs in scope,
  or CGEL-IMPACT-1 will block PASS at the end instead of informing the
  plan at the start.

## 3. Draft the contract

Write `.task/contract.json` (this path is always writable; `cgel schema
task-contract` prints the schema). Keep `scope.allowed` as tight as the
smallest safe change; put paths that must never change in `scope.forbidden`.
Every acceptance criterion needs an id, a description, and `required_checks`
that actually measure it — `cgel summary` warns about criteria whose PASS
would be impossible. For a docs-only task, register a real docs check before
sealing (`test -s docs/roadmap.md` fails without the project — it is
registerable) instead of citing the code suite; a task whose criteria no
check can measure should plan for `close --as ESCALATE` from the start.

## 4. One question seals it

1. Run `cgel summary` — it validates the draft and prints the normalized
   summary, a digest line, and an **approval token** line. (No separate
   `cgel validate` roundtrip.)
2. Ask ONE AskUserQuestion. Plain words, at most ~6 short lines — say what
   you'll do, not how CGEL works. No jargon: translate scope to "files
   I'll touch" and checks to "what must pass". Copy the approval token into
   it so the approval binds to this exact contract:

   > Goal: fix the login redirect loop
   > Files: src/auth/** (about 3 files)
   > Must pass: unit-tests, lint
   > Risk: medium — it is the auth path; a review will judge it
   > Seal digest sha256:ab12cd34ef56

   Paste the token from `cgel summary` VERBATIM. It is matched as a literal
   substring, so shortening it — even by one character — means it does not
   bind and the seal is denied, and the user is then asked to approve the
   very same contract a SECOND time. Trailing text after the whole token is
   harmless; a truncation is not. Copy it, never retype it.

   Read the risk back honestly. `Risk: medium` on an auth fix is the
   claim you should be making; `low` here would be the reflex the old
   default trained, and it would mean no rule judges the change. If you
   DO claim `low`, the summary prints "no rule will judge this change" —
   put that sentence in the question, because it is what the user is
   agreeing to.

   Options: "Approve" / "Adjust" / "Cancel". First option label must start
   with "Approve" — the approval gate matches it.
3. On Approve, seal and open the first iteration in ONE Bash call —
   Seal with the EXACT digest from the summary:
   `cgel seal <TASK-ID> --digest <sha256:...> && cgel iterate open --hypothesis "H-1: ..." --change "..." --expect <checks>`
   The recorded answer is the approval — the gate verifies it from the
   transcript and lets the seal through with no further prompt. Do NOT also
   ask for a chat "approve" on top: one gate, not two.
   - Plain prose only on that line: a backtick or `$(` anywhere in the
     --hypothesis/--change text — even inside quotes — makes the line
     unreadable to the approval gate, which refuses a line it cannot read.
     Spell identifiers without backticks, or seal first and open the
     iteration as a second call.
   - If `Protected capabilities:` is anything but `none`, the question MUST
     name each capability in plain words ("this task may edit the hook
     config") — never smuggle a protected seal past them. Read it off the
     summary; it is your duty, not a flag the CLI enforces.
   - If seal is denied for dirty files, STOP and ask (same question form,
     listing the files); only reseal with `--allow-dirty` after their
     explicit confirmation. Unlike a plain seal, an `--allow-dirty` seal
     binds to the EXACT command string, not the token — so the question
     must quote the whole command in backticks (e.g. `cgel seal <ID>
     --digest <token> --allow-dirty`), or the approval will not bind and
     the user is asked again.

## 5. Work inside the seal

Edit only inside `scope.allowed`. If the gate blocks a path you believe is
needed, do NOT work around it (no Bash writes): tell the user, amend the
contract, and reseal — that is the ESCALATE path. Governance paths
(`.claude/`, `.cgel/`, `docs/standards/`, `docs/adr/`) stay read-only unless
the sealed contract grants the matching capability.

The seal also froze the **governance bundle** (registry, rules, hooks,
guidebook). If any of those files change mid-task the task goes BLOCKED —
resealing the SAME digest needs no new approval; a changed contract does.

For large mechanical changes inside the sealed scope (renames, repetitive
edits), delegate execution to the `cgel:worker` subagent with an exact spec
— you keep the decisions, the loop, and every cgel command.

## 6. Loop with evidence

Work proceeds in explicit iterations — follow the `cgel:loop` skill:
`cgel iterate open` → change → verify → decide. Evidence exists only when
`cgel verify` (or `iterate decide --verify`) runs a registered check;
running commands yourself and pasting output creates NO evidence, and an
edit makes prior evidence stale (path-scoped when the check declares
`watch` globs). Budgets and the default-same failure guard are enforced by
the store — when they block, the USER decides, not you.

If a needed check is missing from `.cgel/registry.json`, that is a
governance change: add it before sealing, or via a dedicated
`modify-verification-registry` task — never mid-task.

The production bar: four built-in rules BLOCK (`CGEL-IMPACT-1` all impacted
code updated, `CGEL-CORRECT-1` no defect the change introduces, `CGEL-ROOT-1`
a fix cures the cause not the symptom, `CGEL-SECRET-1` no hardcoded secrets)
and four ADVISE (`CGEL-DEBT-1` no new debt, `CGEL-TEST-1` new behavior ships
with a test, `CGEL-COMMENT-1` comment quality, `CGEL-CONCISE-1` prose written
for a reader is forwardable as-is). The blocking rules make
semantic verification required at medium+ risk, and the verifier will grep,
not guess. Write code that survives that review the first time — including
the advisory findings, which reach the user even when they cannot stop a
PASS.

Whether ANY of it runs depends on `risk.level`, and there is no default.
State it and argue it in `risk.reasons`:
  - `low` — nothing will judge this change but the registered checks. Claim
    it only when that is genuinely right (a typo, a comment, a test-only
    tweak), and say why.
  - `medium` — the blocking rules run. The honest default for real work.
  - `high` — the verifier runs for the level itself, not only the rules.
`cgel summary` prints the verdict; read it back to the user in the approval
question when it says NOT REQUIRED, because that sentence is the cost of the
claim you made. Two cases floor to `high` whatever you claim: requesting
`protected_capabilities`, or a `scope.allowed` that reaches a governance
path. Do not argue with the floor — tighten the scope.

## 7. Two tasks at once

A second task may be sealed while the first is open — that is how one
session codes while another answers or starts new work:

- Draft it at `.task/<TASK-ID>.contract.json` and pass
  `--contract .task/<TASK-ID>.contract.json` to summary and seal, so the
  drafts never fight over one file.
- From then on pass `--task <TASK-ID>` on EVERY cgel verb — decide the
  task you own, never the other session's.
- Keep the two `scope.allowed` disjoint (seal warns on overlap). The
  workspace is still shared: another task's edits can stale your evidence
  unless your checks declare `watch` globs — re-verify and move on.

## 8. Close honestly

Follow the `cgel:attest` skill: if the seal requires semantic verification,
run the read-only `cgel:verifier` subagent and record its findings
(`cgel semantic record`); then `cgel close --as PASS` — it succeeds only
when every criterion has fresh passing evidence and no blocking finding
stands, and it exports a sanitized attestation. If PASS is impossible,
close with `ESCALATE --reason "..."`, `ROLLED_BACK`, or `ABORT`. Never
claim a criterion passed without recorded evidence.

If the user aborts the task, stop working immediately: record one honest
decision on any open iteration, close (`ROLLED_BACK` or `ABORT`), and ask
what to do with uncommitted files — no farewell verification runs, no
ritual.

## Talking to the user

Everything you write for the user is held to `CGEL-CONCISE-1`, the same bar
the verifier applies to prose in the diff. Progress notes are one line;
explanations are plain language, six lines at most, no CGEL vocabulary
unless the user uses it first. Answer first, evidence second: do not restate
the request before answering it, do not explain background nobody asked for,
and do not narrate the steps you took — when the work is done, say what
changed and what proved it, not how the loop felt. A summary the user has to
edit before forwarding it failed; if a document is the deliverable, write it
to be handed on as-is.

Lead with the action. When the user has something to do, the first line is
the thing to do — the command to run, the file and line to open — and the
reasoning comes after it, if at all. Steps that must happen in order are a
numbered list, not a paragraph the user has to re-parse into one. Cut the
wind-up and cut the sign-off: no "great question", no "let me think about
this", no "hope this helps", no offer to dig deeper that the user can make
themselves. Say what a failure is, flatly and once — name the check and the
error it printed, not a reaction to it.

Two things this does not license. A request to explain, teach, or walk
through something is answered in full; there the explanation IS the action,
and clipping it is the same failure in the other direction. And a
destructive or irreversible step is still confirmed before it runs, however
terse the rest of the exchange.
