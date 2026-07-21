---
name: attest
description: CGEL closing ceremony — semantic verification via the read-only verifier subagent, recording findings, evidence-gated PASS, and sanitized attestation export. Use when all acceptance criteria appear satisfied and the task should close.
user-invocable: false
---

# CGEL attest & close

With several tasks open, every command here takes `--task <id>`.

## 1. Check what the seal demands

`cgel status` and the sealed contract tell you if semantic verification is
required (frozen at seal: high risk, AI-enabled, `semantic_review: true`,
or blocking rules at medium risk). `cgel rules` lists the semantic rules
in force. If it is not required, sweep (step 2) and then skip to step 4.

## 2. Sweep the change clean — before any verifier runs

Walk `git diff HEAD` one last time and delete the litter the loop left:
comments that restate the code or no longer match it, helpers nothing
calls anymore, imports nothing uses, files created and then abandoned,
debug leftovers. Two hard bounds keep this pass safe:

- **Only the files this task touched.** The diff IS the boundary — a
  cleanup that wanders into untouched files is scope creep holding a
  broom, and the edit gate will rightly refuse anything outside
  `scope.allowed` anyway.
- **Behavior-preserving deletions only.** If removing it changes what the
  code does, it is not cleanup — leave it, or take it through a normal
  iteration with its own hypothesis.

When there is anything to delete, open the sweep as its own iteration
(`cgel iterate open --hypothesis "H-N: cleanup sweep ..."`) and decide it
on fresh evidence like any change. When the diff is already clean, skip
ahead — a ceremony with nothing to do is noise.

This pass runs BEFORE the verifier on purpose: cleanup edits after
`cgel semantic record` stale the findings and force a second verifier
run, while a sweep done first means the review judges the diff you
actually ship. On a long task this is where the accumulated litter goes —
CGEL-COMMENT-1 and CGEL-DEBT-1 only advise at close, and this pass exists
so they find nothing left to say.

## 3. Run the verifier (if required)

Launch the `cgel:verifier` subagent (it is read-only by construction —
never hand it write tools). Give it: the task goal, the changed files, the
sealed scope, the rule ids from `cgel rules`, and **the diff**:

```
git diff HEAD -- <the changed files>     # plus `git diff --cached`, and the
                                         # body of any new file git does not
                                         # yet track
```

Paste the diff into the prompt. It holds no Bash tool, so it cannot obtain
one for itself — if you do not send it, it does not exist.

This matters more than it looks. Rules like CGEL-IMPACT-1, CGEL-CORRECT-1,
CGEL-ROOT-1 and CGEL-COMMENT-1 are defined over the CHANGE ("every symbol
*this change* renamed", "the defect *this change* introduces", "the comments
*in the change*"). Handed only a file list, the
verifier reviews each file's entire history and reports on that — which
reads exactly like a real review and is not one. If the diff is genuinely
unavailable, say so in the prompt in those words; the verifier fails closed
on a missing input rather than certifying what it could not see.

It returns a findings JSON object.

Write that JSON verbatim to `.task/findings.json` (always writable), then:

```
cgel semantic record
```

The record binds the findings to the current workspace state. Any edit
afterwards makes it stale — re-run the verifier after fixes.

- Blocking findings (`SEMANTIC FAIL`): fix them in a new iteration, or —
  if you believe a finding is wrong — challenge ONCE with concrete
  evidence and re-run the verifier. Still disagreeing? `cgel close --as
  ESCALATE`. Never bury a blocking finding.

## 4. Fresh evidence, then close — two calls

```
cgel verify --required
cgel iterate decide ADVANCE --lesson "..." && cgel close --as PASS
```

`verify --required` re-runs every check the criteria name, in one
roundtrip, AFTER the last edit (staleness is enforced; checks with `watch`
globs survive unrelated edits, everything else does not). The validator
behind `close --as PASS` rejects anything missing/stale/failed and lists
why. On success it exports a sanitized attestation (ids, statuses, digests
— no logs) into the runtime state store; `cgel attest` re-exports on
demand. Attestations are never committed to the repository by default.

Then offer the output a home — one AskUserQuestion covering commit and,
when the user wants it out, push:

- The commit message meets the repo's own bar: read `git log` for the
  house style; imperative subject ≤72 chars; a body only when it explains
  *why*. No debug leftovers in the diff — the verifier's CGEL-COMMENT-1
  advises on exactly that, so do not ship past it. Do not commit without their
  answer; uncommitted task output is what trips the NEXT seal's dirty
  check.
- Pushing is its own approval: the question quotes the exact
  `git push ...` command and says plainly what goes out — commits ahead,
  diffstat, and the task's terminal status. The push gate refuses the
  command without that recorded answer. Never push work whose task did
  not close PASS without saying so in the question.

If PASS is impossible (a criterion has no registered check, a blocking
finding stands, budgets ran out), the honest closes are
`ESCALATE --reason "..."`, `ROLLED_BACK`, or `ABORT`. A denied PASS is
information, not an obstacle to route around.

If the user aborted the task, close now (`ROLLED_BACK`/`ABORT`) — no
farewell verify runs, no attestation theater. `close` deletes the matching
draft from `.task/` so the next task starts clean.

## The closing report

What changed, what proved it, what is left for the user — in that order,
and nothing before it. No recap of the request, no tour of the iterations,
no closing pleasantry. Anything still owed to the user (a commit to
approve, a finding to judge, a follow-up) is the last line and is one
concrete action, numbered if there is more than one.
