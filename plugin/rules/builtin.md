# CGEL built-in review rules

Shipped with the plugin and merged into every project's rule set unless
`.cgel/config.json` sets `{"builtin_rules": "off"}`. A project rule with
the same id in `docs/standards/` replaces the built-in — the host owns its
yardstick. They exist because production work fails the same few ways
everywhere: half-updated call sites, quietly added debt, comment slop,
prose nobody can forward, leaked secrets.

Four BLOCK and four ADVISE, and the split is about ground truth, not
importance. CGEL-IMPACT-1, CGEL-SECRET-1 and CGEL-CORRECT-1 are settled by
pointing at a line — a stale call site, a key shape, a null dereference on
an unguarded path is there or it is not — so a finding is checkable and a
block is arguable. CGEL-ROOT-1 is the block taken off that principle by
choice: whether a fix cures the cause or hides the symptom is a judgement,
not a search, but a patchwork fix that quietly accrues debt is the failure
this bar exists to stop — scoped narrowly to that one call, and softenable
by a same-id override in docs/standards or by turning the built-ins off.
CGEL-DEBT-1, CGEL-TEST-1, CGEL-COMMENT-1 and CGEL-CONCISE-1 are judgements
of taste; blocking on taste, at close, with an ungated ESCALATE as the only
exit, is how a lint gate earns itself a config flag turning it off, so they
advise. All eight run, are recorded, and reach the human — the advisory
four just do not stop a PASS on their own.

Honesty: all eight are EVIDENCE_GATED model judgments, recorded and escalated
to the human on disagreement — not deterministic proofs.

## CGEL-IMPACT-1 — All impacted code is updated
Blocking: yes
Owner: cgel
Requirement: a change to a symbol, API, schema, config key, or behavior
updates every caller, implementation, test, and doc that depends on it.
Renames leave no stale references; changed signatures leave no old-shape
call sites; removed features leave no dead wiring. Verify by searching,
not by recalling.
Evidence expected: search results showing the old form is gone (or every
remaining hit justified), and the dependents updated in the same diff.

## CGEL-CORRECT-1 — No defect the change introduces
Blocking: yes
Owner: cgel
Requirement: the change introduces no defect a reader can point at by
line — a null or None dereference on a path nothing guards, an error or
result left unchecked, an off-by-one or wrong boundary, a resource opened
and never closed, an invariant or contract the surrounding code relies on
now broken. Judge the changed lines and what they reach, not the file's
whole history; a defect you cannot anchor to a line is a smell to report,
not a block.
Evidence expected: file and line for each defect, with the input or path
that reaches it — or a clean pass that says the changed lines were read.

## CGEL-ROOT-1 — A fix cures the cause, not the symptom
Blocking: yes
Owner: cgel
Requirement: a change presented as a fix addresses the root cause and does
not paper over it with a workaround that leaves the underlying defect in
place — a swallowed error, a special case that masks the general bug, a
retry wrapped around a race, a type widened to hide a broken contract. A
fix that only quiets the symptom is debt taken on at the one moment it was
still avoidable. A deliberately partial fix is allowed, but it is named as
partial where a human reads it — the iteration's decision or the close
reason — never shipped as if it were whole.
Evidence expected: the cause named, and the change shown to remove it
rather than to hide its effect.

## CGEL-DEBT-1 — No new technical debt
Blocking: no
Owner: cgel
Requirement: the change does not duplicate existing logic instead of
reusing it, does not leave dead or commented-out code, and does not widen a
public surface without need. (Papering over a root cause with a workaround
is CGEL-ROOT-1's charge now, not this rule's.) Debt accepted on purpose is
declared out loud — in the iteration's decision, or in the close reason —
never silent.
Evidence expected: reused helpers cited by path; any accepted debt named
where a human will read it.

## CGEL-TEST-1 — New behavior ships with a test
Blocking: no
Owner: cgel
Requirement: behavior the change adds or alters is exercised by a test that
would fail without the change — a new function, a new branch, a fixed bug
each earn a case that pins them. Coverage deliberately skipped (a spike, a
throwaway, an integration seam with no harness) is named where a human will
read it, not left as a silent gap.
Evidence expected: the test that exercises the new behavior cited by path,
or the skipped coverage named and justified.

## CGEL-COMMENT-1 — Comments earn their place
Blocking: no
Owner: cgel
Requirement: comments explain WHY — constraints, invariants, non-obvious
choices — and never narrate what the code already says. No leftover
TODO/FIXME without an owner, no commented-out code, no debug prints or
temporary logging in the final diff.
Evidence expected: the diff's comments read as constraints, not narration.

## CGEL-CONCISE-1 — Prose for a reader is ready to hand over
Blocking: no
Owner: cgel
Requirement: prose the change writes for a human — documentation, README
sections, reports, summaries, help text, release notes, close reasons —
answers what was asked and stops. Three failures name it: the same point
restated in different words, background or justification the reader did not
ask for, and narration of the work ("first I looked at", "as mentioned
above") where the result belongs. The bar is whether the text could be
handed to a stakeholder unedited. Length is not the charge — an unnecessary
sentence is one at any length, and a long document that earns every line
passes. Code comments belong to CGEL-COMMENT-1, not to this rule.
Evidence expected: the redundant or unrequested passage quoted with path and
line — or a pass stating the prose in the diff was read.

## CGEL-SECRET-1 — No hardcoded secrets
Blocking: yes
Owner: cgel
Requirement: no credentials, API keys, tokens, connection strings carrying
passwords, or private endpoints hardcoded anywhere in the diff;
configuration comes from the environment or a secret store.
Evidence expected: a scan of the diff for key/token/password shapes comes
back clean or every hit is a placeholder.
