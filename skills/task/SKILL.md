---
name: task
description: CGEL task lifecycle — intake a request, draft a task contract, run the seal ceremony with the user, work inside the sealed scope, close with an honest terminal status. Use when starting any non-trivial change in a CGEL-enabled repo (a `.cgel/` directory exists).
user-invocable: false
---

# CGEL task

You are opening a task under the Contract-Gated Evidence Loop. The edit gate
is closed until a contract is sealed; do not fight the gate — feed it.

## 1. Intake

Classify the request: task type (bug-fix, feature, refactor, ...), primary
domain, risk level, and whether any **protected capability** is involved
(`modify-governance`, `modify-verification-registry`, `modify-hook-policy`,
`modify-evaluation-baseline`, `external-write`, `dependency-change`,
`schema-migration`, `public-api-change`). Inspect the repo read-only as
needed. If the goal or scope is genuinely ambiguous, ask the user now —
the contract must not silently reinterpret their intent.

## 2. Draft the contract

Write `.task/contract.json` (this path is always writable). Follow
`schemas/task-contract.schema.json`. Keep `scope.allowed` as tight as the
smallest safe change; put paths that must never change in `scope.forbidden`.
Every acceptance criterion needs an id and a description; name
`required_checks` even though the check registry only arrives in Phase 1.

## 3. Validate and run the seal ceremony

1. Run `cgel validate` — fix schema errors until `VALIDATE PASS`.
2. Run `cgel summary` — it prints the normalized summary and a digest line.
3. Show the summary to the user verbatim and ask them to approve the seal.
4. Seal with the EXACT digest from the summary:
   `cgel seal <TASK-ID> --digest <sha256:...>`
   - `seal_mode=human` (protected capabilities present): the user must
     approve or type this command themselves — never smuggle it past them.
   - If seal is denied for dirty files, STOP and ask the user; only reseal
     with `--allow-dirty` after their explicit confirmation.

## 4. Work inside the seal

Edit only inside `scope.allowed`. If the gate blocks a path you believe is
needed, do NOT work around it (no Bash writes): tell the user, amend the
contract, and reseal — that is the ESCALATE path. Governance paths
(`.claude/`, `.cgel/`, `docs/standards/`, `docs/adr/`) stay read-only unless
the sealed contract grants the matching capability.

The seal also froze the **governance bundle** (registry, rules, hooks,
guidebook). If any of those files change mid-task the task goes BLOCKED —
reseal (adopting the new measure) or close honestly.

## 5. Loop with evidence

Work proceeds in explicit iterations — follow the `cgel:loop` skill:
`cgel iterate open` → change → `cgel verify <check-id>` → `cgel iterate
decide`. Evidence exists only when `cgel verify` runs a registered check;
running commands yourself and pasting output creates NO evidence, and any
edit makes prior evidence stale. Budgets and the default-same failure
guard are enforced by the store — when they block, the USER decides, not
you.

If a needed check is missing from `.cgel/registry.json`, that is a
governance change: add it before sealing, or via a dedicated
`modify-verification-registry` task — never mid-task.

## 6. Close honestly

Follow the `cgel:attest` skill: if the seal requires semantic
verification, run the read-only `cgel:verifier` subagent and record its
findings (`cgel semantic record`); then `cgel close --as PASS` — it
succeeds only when every criterion has fresh passing evidence and no
blocking finding stands, and it exports a sanitized attestation. If PASS
is impossible, close with `ESCALATE --reason "..."`, `ROLLED_BACK`, or
`ABORT`. Never claim a criterion passed without recorded evidence.
