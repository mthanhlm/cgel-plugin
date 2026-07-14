---
name: loop
description: CGEL iteration loop — the cognitive workflow inside a sealed task (INVESTIGATE → PLAN ITERATION → CHANGE → VERIFY → DECIDE), with budgets and the default-same failure guard. Use once a task is sealed and real work starts in a CGEL-enabled repo.
user-invocable: false
---

# CGEL loop

Work inside a sealed task proceeds in small, evidence-checked iterations.
The control layer counts everything; your job is to make each iteration a
real experiment.

## The cycle

1. **INVESTIGATE** — read enough to form a hypothesis about what to change
   and why it will meet a criterion. For broad reading in big codebases,
   use the read-only `cgel:explorer` subagent instead of flooding context.
2. **PLAN ITERATION** — open it explicitly:
   `cgel iterate open --hypothesis "H-1: ..." --intended-change "smallest
   change that tests it" --expected-checks unit-tests`
   The first open moves the task SEALED → ACTIVE. You cannot open a second
   iteration while one is undecided.
3. **CHANGE** — edit inside `scope.allowed` only. Leave code cleaner than
   you found it: never write a comment that just restates what the code
   does, and delete any redundant or obsolete comment you pass through in a
   file you're already editing — even one you did not write. Comments earn
   their place by explaining *why*, not by narrating *what*.
4. **VERIFY** — `cgel verify <check-id>` for the checks this iteration was
   supposed to move. Manual command runs are not evidence.
5. **DECIDE** — close the iteration honestly:
   - `cgel iterate decide RETRY` — same plan, fix the execution.
     Forbidden when the failure signature repeats (see guard below).
   - `cgel iterate decide REPLAN --lesson "..."` — new hypothesis/plan;
     consumes replan budget.
   - `cgel iterate decide ROLLBACK_ITERATION` — this iteration made things
     worse; revert its patch yourself (git), CGEL never touches the
     checkout.

## The default-same guard

The guard compares machine-recorded failure signatures (check id, failure
kind, diagnostic fingerprint) — not your narrative:

- Same signature after a RETRY → RETRY is refused; you must REPLAN.
- Same signature after a REPLAN → RETRY/REPLAN refused; ESCALATE or ABORT.
- Genuinely-different-failure claims need a human:
  `--override-reason "..." --approved-by <user>` — only after the user
  actually approved.

## Budgets and BLOCKED

Iterations and replans come from the sealed contract. Exhaustion moves the
task to BLOCKED — edits stop working, and only the USER unblocks
(`cgel unblock --add-iterations N`). Never run `unblock` on your own
initiative; ask, then let the user decide. If the governance bundle
changed, only a reseal unblocks.

Do not stop mid-iteration: the Stop gate sends you back (bounded) if an
iteration has no decision. When work is done, follow `cgel:attest` for
semantic verification and closing.
