---
name: attest
description: CGEL closing ceremony — semantic verification via the read-only verifier subagent, recording findings, evidence-gated PASS, and sanitized attestation export. Use when all acceptance criteria appear satisfied and the task should close.
user-invocable: false
---

# CGEL attest & close

## 1. Check what the seal demands

`cgel status` and the sealed contract tell you if semantic verification is
required (frozen at seal: high risk, AI-enabled, `semantic_review: true`,
or blocking rules at medium risk). `cgel rules` lists the semantic rules
in force.

## 2. Run the verifier (if required)

Launch the `cgel:verifier` subagent (it is read-only by construction —
never hand it write tools). Give it: the task goal, the changed files, the
sealed scope, and the rule ids from `cgel rules`. It returns a findings
JSON object.

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

## 3. Fresh evidence for every criterion

Re-run `cgel verify <check-id>` for every required check AFTER the last
edit (evidence staleness is enforced; a single edit invalidates all of
it). `cgel audit` should say `chain=intact bundle=unchanged`.

## 4. Close

```
cgel close --as PASS
```

The validator rejects anything missing/stale/failed and lists why. On
success it exports a sanitized attestation (ids, statuses, digests — no
logs) into the runtime state store; `cgel attest` re-exports on demand.
Attestations are never committed to the repository by default.

If PASS is impossible (a criterion has no registered check, a blocking
finding stands, budgets ran out), the honest closes are
`ESCALATE --reason "..."`, `ROLLED_BACK`, or `ABORT`. A denied PASS is
information, not an obstacle to route around.
