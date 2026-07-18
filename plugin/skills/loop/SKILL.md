---
name: loop
description: CGEL iteration loop — the cognitive workflow inside a sealed task (INVESTIGATE → PLAN ITERATION → CHANGE → VERIFY → DECIDE), with budgets and the default-same failure guard. Use once a task is sealed and real work starts in a CGEL-enabled repo.
user-invocable: false
---

# CGEL loop

Work inside a sealed task proceeds in small, evidence-checked iterations.
The control layer counts everything; your job is to make each iteration a
real experiment — and to spend roundtrips on work, not ceremony. When more
than one task is open, add `--task <id>` to every command below and only
ever decide the task this session owns.

## The cycle

1. **INVESTIGATE** — read enough to form a hypothesis about what to change
   and why it will meet a criterion. For broad reading in big codebases,
   use the read-only `cgel:explorer` subagent instead of flooding context.
2. **PLAN ITERATION** — open it explicitly:
   `cgel iterate open --hypothesis "H-1: ..." --change "smallest change that tests it" --expect unit-tests`
   (`--change` = `--intended-change`, `--expect` = `--expected-checks`.)
   Always declare `--expect`: an iteration that claims nothing cannot
   ADVANCE. The first open moves the task SEALED → ACTIVE. You cannot open
   a second iteration while one is undecided.
3. **CHANGE** — edit inside `scope.allowed` only. Mechanical bulk edits can
   go to the `cgel:worker` subagent with an exact spec; decisions stay
   here. Build to the production bar, especially in a messy codebase:
   reuse existing helpers instead of duplicating them, fix the root cause
   instead of papering over it (CGEL-ROOT-1 BLOCKS), catch the null-check
   and edge case in your own diff (CGEL-CORRECT-1 BLOCKS), and update every
   caller/test/doc the change touches (CGEL-IMPACT-1 BLOCKS and the verifier
   greps for all three; CGEL-DEBT-1 and CGEL-TEST-1 advise — they still
   reach the user, they just cannot stop PASS on their own). Leave code cleaner than you found it: never write a
   comment that just restates what the code does, and delete any redundant
   or obsolete comment you pass through in a file you're already editing —
   even one you did not write. Comments earn their place by explaining
   *why*, not by narrating *what*.
4. **VERIFY + DECIDE** — one call closes the loop honestly:
   `cgel iterate decide ADVANCE --verify --lesson "..."`
   `--verify` freshly runs the iteration's expected checks and records
   their evidence first; ADVANCE then holds only if they all pass. Manual
   command runs are not evidence. (Running `cgel verify <ids>` or
   `cgel verify --required` separately is fine too — `verify` takes many
   check ids in one call.) Decisions accept unique prefixes: ADV, RET,
   REP, ROLL.
   - `ADVANCE` — the hypothesis held; costs no replan budget.
     Evidence-gated: refused unless every expected check has fresh passing
     evidence. It is not a way past a failing check — a failure decided as
     ADVANCE is a lie the store will catch.
   - `RETRY` — same plan, fix the execution. Forbidden when the failure
     signature repeats (guard below).
   - `REPLAN --lesson "..."` — new hypothesis/plan; consumes replan budget.
   - `ROLLBACK_ITERATION` — this iteration made things worse; revert its
     patch yourself (git), CGEL never touches the checkout.

   Pick the one that is true. RETRY on a success inflates the retry rate
   the project measures itself by; ADVANCE on a failure is refused.

## The default-same guard

The guard compares machine-recorded failure signatures (check id, failure
kind, diagnostic fingerprint) — not your narrative. A failure that a later
pass of the same check superseded no longer counts against you.

- Same signature after a RETRY → RETRY is refused; you must REPLAN.
- Same signature after a REPLAN → RETRY/REPLAN refused; ESCALATE or ABORT.
- Genuinely-different-failure claims need a human:
  `--override-reason "..." --approved-by <user>` — the approval gate
  requires the user's recorded answer approving that exact command.

## Budgets and BLOCKED

Iterations and replans come from the sealed contract. Exhaustion moves the
task to BLOCKED — edits stop working, and only the USER unblocks. Never run
`unblock` on your own initiative: ask ONE AskUserQuestion (e.g. "Iteration
budget is used up (8/8). Extend by 3? — `cgel unblock --add-iterations 3
--task X`"), and run the command only on their recorded Approve — the gate
checks. If you can see the budget running out ahead of a block, the same
question works early: `unblock --add-iterations` also widens a budget
before exhaustion. If the governance bundle changed, only a reseal
unblocks (same digest = no new approval needed).

## Stopping

Do not stop mid-iteration: the Stop gate sends you back (bounded) if an
iteration has no decision. If the user aborts, record one honest decision
and close — skip any further verification runs; the task is over. When
work is done, follow `cgel:attest` for semantic verification and closing.
