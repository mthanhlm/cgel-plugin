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

`cgel check add` works only while no task is open; once sealed, the
registry is frozen inside the governance bundle.

## 2. Intake — and challenge the intent

Classify the request: task type (bug-fix, feature, refactor, ...), primary
domain, risk level, and whether any **protected capability** is involved
(`modify-governance`, `modify-verification-registry`, `modify-hook-policy`,
`modify-evaluation-baseline`, `external-write`, `dependency-change`,
`schema-migration`, `public-api-change`). Inspect the repo read-only as
needed — use the `cgel:explorer` subagent for broad recon instead of
flooding your own context. If the goal or scope is genuinely ambiguous, ask
the user now — the contract must not silently reinterpret their intent.

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
   summary and a digest line. (No separate `cgel validate` roundtrip.)
2. Ask ONE AskUserQuestion. Plain words, at most ~6 short lines — say what
   you'll do, not how CGEL works. No jargon: translate scope to "files
   I'll touch" and checks to "what must pass". Include the digest so the
   approval binds to this exact contract:

   > Goal: fix the login redirect loop
   > Files: src/auth/** (about 3 files)
   > Must pass: unit-tests, lint
   > Risk: low — no API change
   > Seal digest sha256:ab12cd34ef56…

   Options: "Approve" / "Adjust" / "Cancel". First option label must start
   with "Approve" — the approval gate matches it.
3. On Approve, seal and open the first iteration in ONE Bash call —
   Seal with the EXACT digest from the summary:
   `cgel seal <TASK-ID> --digest <sha256:...> && cgel iterate open --hypothesis "H-1: ..." --change "..." --expect <checks>`
   The recorded answer is the approval — the gate verifies it from the
   transcript and lets the seal through with no further prompt. Do NOT also
   ask for a chat "approve" on top: one gate, not two.
   - `seal_mode=human` (protected capabilities present): the question MUST
     name each capability in plain words ("this task may edit the hook
     config") — never smuggle a protected seal past them.
   - If seal is denied for dirty files, STOP and ask (same question form,
     listing the files); only reseal with `--allow-dirty` after their
     explicit confirmation.

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

The production bar is always on: the built-in blocking rules
(`CGEL-IMPACT-1` all impacted code updated, `CGEL-DEBT-1` no new debt,
`CGEL-COMMENT-1` comment quality, `CGEL-SECRET-1` no hardcoded secrets)
make semantic verification mandatory at medium+ risk, and the verifier
will grep, not guess. Write code that survives that review the first time.

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

Progress notes are one line. Explanations are plain language, six lines at
most, no CGEL vocabulary unless the user uses it first. When the work is
done, say what changed and what proved it — not how the loop felt.
