# CGEL built-in review rules

Shipped with the plugin and merged into every project's rule set unless
`.cgel/config.json` sets `{"builtin_rules": "off"}`. A project rule with
the same id in `docs/standards/` replaces the built-in — the host owns its
yardstick. They exist because production work fails the same few ways
everywhere: half-updated call sites, quietly added debt, comment slop,
leaked secrets. The verifier judges them; blocking findings stop PASS.
Honesty: these are EVIDENCE_GATED model judgments, recorded and escalated
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

## CGEL-DEBT-1 — No new technical debt
Blocking: yes
Owner: cgel
Requirement: the change does not duplicate existing logic instead of
reusing it, does not leave dead or commented-out code, does not paper over
a root cause with a workaround, and does not widen a public surface
without need. Debt accepted on purpose is declared in the contract's
`exceptions` list, never silent.
Evidence expected: reused helpers cited by path; any accepted debt named
in the contract.

## CGEL-COMMENT-1 — Comments earn their place
Blocking: yes
Owner: cgel
Requirement: comments explain WHY — constraints, invariants, non-obvious
choices — and never narrate what the code already says. No leftover
TODO/FIXME without an owner, no commented-out code, no debug prints or
temporary logging in the final diff.
Evidence expected: the diff's comments read as constraints, not narration.

## CGEL-SECRET-1 — No hardcoded secrets
Blocking: yes
Owner: cgel
Requirement: no credentials, API keys, tokens, connection strings carrying
passwords, or private endpoints hardcoded anywhere in the diff;
configuration comes from the environment or a secret store.
Evidence expected: a scan of the diff for key/token/password shapes comes
back clean or every hit is a placeholder.
