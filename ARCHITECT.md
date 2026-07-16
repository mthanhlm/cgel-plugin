# CGEL v1.0 — FINAL (approved by both parties)

> **Status:** ChatGPT gave the final sign-off in Round 6, together with one mandatory terminology correction — "trusted store" → "CGEL runtime state store" with a qualifier per deployment profile. The correction has been applied to the document below (recorded as D-34). The architecture debate is closed; this is the final record.

---

# Round 5 — Claude's response: Consensus confirmation + Final Consolidated Architecture

## Part 1 — Answers to ChatGPT's four closing questions

**1. Guidebook read-only in Profile A:** AGREED. `HARD_ENFORCED` is only correct for `Edit/Write` (where the hook can genuinely block); defending against every modification path via Bash when there is no filesystem sandbox is only `EVIDENCE_GATED + tamper-evident` via the governance bundle digest. This is precisely my own C-1 principle applied back to the place where I mislabelled it — the correction is right and I accept it without reservation. Your three-row table (Edit/Write / any-mechanism / bundle-unchanged-before-PASS) is carried verbatim into the final enforcement matrix.

**2. The seal digests the entire resolved governance bundle content:** AGREED. Digesting the index without digesting the content it points to is a hole I left open (X-10 deserved to be rejected). Separating the `governance bundle` (the yardstick — frozen) from the `execution inputs` (the object being worked on — modifiable within scope) is the right boundary, and `sealed-guidebook-bundle-changed → BLOCKED, require reseal` is the right semantics.

**3. The approval ceremony bound to the exact contract digest:** AGREED. Approving a command is not the same as approving an artifact; a normalized summary + `cgel seal <task> --digest sha256:...` turns the permission-ask boundary into genuine informed consent. Accepted as a mandatory ceremony for every human seal.

**4. Persistence policy:** AGREED. Raw runtime state is not committed; attestations are not committed by default; project opt-in `local | ci-artifact | pr-comment | repository`, and `repository` is never the default.

I also accept the remaining refinements from v0.4: the detailed capability taxonomy (`modify-project-docs / modify-governance / modify-verification-registry / modify-hook-policy / modify-evaluation-baseline`), `additionalContext` being only a *candidate transcript anchor* with a dual-sink policy, `ROLLED_BACK` as a persisted terminal status while `ROLLBACK_ITERATION` is an iteration decision, and moving the prototype questions into the validation backlog rather than treating them as unresolved architecture.

### Consensus declaration against the §14 checklist

| Critical area | Status |
|---|---|
| Runtime model (states, transitions, terminal, retry/replan semantics, budgets) | AGREED |
| Task contract (ownership, seal, mutability, AC, scope, risk, approval) | AGREED |
| Guidebook (constitution, skills, rules, references, ADRs, precedence, versioning, staleness, conflict, loading) | AGREED |
| Agent structure (orchestrator, subagents, permissions, isolation, escalation) | AGREED |
| Verification (deterministic gates, semantic, evidence model, completion) | AGREED |
| Persistence (task-local, cross-session, repo artifacts, sensitive data) | AGREED |
| Implementation strategy (MVP scope, structure, testing, migration, metrics) | AGREED |

There is no architectural disagreement left. The items still open (V-1..V-7 below) are all prototype validation, not design decisions. Per your proposal, the remainder of this round is the **Final Consolidated Architecture** — no new concepts are opened.

---

# FINAL CONSOLIDATED ARCHITECTURE
# Contract-Gated Evidence Loop — CGEL v1.0

## 15.1 Executive decision

**Architecture name:** Contract-Gated Evidence Loop (CGEL).

**Core design principles:**

1. **Enforcement honesty** — every assurance claim is bound to (feature + deployment profile + enforcement primitive); four classes `HARD_ENFORCED / EVIDENCE_GATED / HUMAN_GATED / GUIDANCE_ONLY` + the qualifier `tamper-evident | tamper-proof`. Never use the word "guarantee" for GUIDANCE_ONLY.
2. **Contract-first, sealed measure** — a task only runs once its contract is sealed, and the seal freezes the *yardstick* as well (governance bundle: registry, rules, skills, references, ADRs, constitution, eval specs), not just the *problem statement*.
3. **Evidence over self-report** — PASS exists only when the control layer cross-checks evidence that is hook-recorded, hash-chained, and bound to the contract digest + governance digest + diff digest. The party being evaluated does not keep the scorecard, does not hold the yardstick, and does not hold the scale.
4. **Guidebook first-class** — the agent works from project knowledge (constitution/skills/rules/references/ADRs) resolved per task, loaded on demand, on top of Claude Code's native primitives.
5. **Human gates at real boundaries** — every HUMAN_GATED row is anchored to the permission UI (which the model cannot click) and to exact-digest approval.
6. **A controlled loop** — the smallest iteration sufficient to test a hypothesis; a machine-observed failure guard (default-same) prevents looping; budgets move to `BLOCKED`, never self-extended.
7. **AI is a domain** — AI standards/knowledge/evals go through exactly the same pipeline; there is no separate runtime for AI.

**Why this was chosen over plain PDCA:** PDCA has no runtime semantics — it defines neither scope enforcement, nor evidence, nor budgets, nor terminal outcomes. PDCA is retained as the outer improvement loop: lessons from iteration logs and attestations → update the guidebook (via a `modify-governance` task).

**Deliberate exclusions:** a general rule engine; a Planner subagent; an Implementer subagent in the MVP; model-writable evidence/approval; loading the entire guidebook; auto phase-chaining via hooks; MAPE-KV as the runtime name; an AI-specific architecture; automatic stash/reset/clean on the user's checkout; committing attestations by default.

## 15.2 Component architecture

```text
USER REQUEST
    │
    ▼
INTAKE ────────────── task/domain classification · risk · protected capabilities
    │
    ▼
CONTRACT DRAFT ────── the cgel-task skill guides; the only write-exception: contract path
    │
    ▼
CONTRACT SEAL ─────── cgel validate → normalized summary → human approval (exact digest)
    │                  or auto-seal when there is no protected capability
    │                  the seal settles: contract + GOVERNANCE BUNDLE digests + base revision
    ▼
CONTEXT RESOLUTION ── constitution (always-on) · skills · semantic rules · references
    │                  · ADRs (metadata-first, on-demand) · conflict report → ESCALATE if blocking
    ▼
ITERATION LOOP ────── cognitive: INVESTIGATE → PLAN ITERATION → CHANGE → VERIFY → DECIDE
    │                  gates: PreToolUse (seal/scope/governance-paths) · command guard
    │                  · verification registry → evidence recorder (hash chain, diff-bound)
    │                  · failure guard (default-same) · budgets · Stop continuation (bounded)
    │                  subagents: Explorer (optional, read-only) · Verifier (conditional,
    │                  read-only, trigger frozen at seal)
    ▼
DECISION ──────────── iteration: RETRY | REPLAN | ROLLBACK_ITERATION
    │                  terminal: PASS | ROLLED_BACK | ESCALATE | ABORT
    ▼
EVIDENCE & PERSISTENCE ─ CGEL runtime state store
                          ├─ Profile A: local, tamper-evident — same-principal,
                          │             not a hard trust boundary
                          ├─ Profile B: protected, tamper-proof within boundary
                          · .task/ mirror debug
                          · sanitized attestation export (not committed by default)
```

**Deployment profiles:**

- **Profile A — Native / tamper-evident:** Claude Code on the host, hooks + the `cgel` CLI + a local store, under the same OS principal. Has: harness tool restrictions, the human permission boundary, Edit/Write blocking, digest-based stale detection, hash-chain audit. Lacks: filesystem tamper-proofing, Bash-level write prevention. Used for: supervised work, low/medium risk, the MVP.
- **Profile B — Isolated / tamper-proof within the declared boundary:** the control plane lives outside the agent principal (Bash sandbox + protected mounts / container / separate OS user / trusted service / CI runner). Raises evidence, budget, seal, and governance read-only to HARD_ENFORCED. Used for: high-risk, unattended, regulated work.

## 15.3 Runtime state machine

### Lifecycle (control state — enforceable)

```text
NO_TASK → DRAFT → SEALED → ACTIVE ⇄ BLOCKED → TERMINAL
```

| Transition | Guard |
|---|---|
| NO_TASK → DRAFT | the user initiates a task |
| DRAFT → SEALED | schema valid + normalized summary displayed + (auto-seal if there is no protected capability, otherwise human approval on the exact digest) |
| SEALED → ACTIVE | the first iteration is opened; base revision + input snapshot recorded |
| ACTIVE → BLOCKED | budget exhausted · missing approval · sealed-guidebook-bundle-changed · a conflict blocks a decision · environment missing · Stop continuation exhausted |
| BLOCKED → ACTIVE | user action: grant approval, raise the budget, reseal, resolve the conflict |
| ACTIVE → TERMINAL | a valid proposePass (PASS) · task rollback completed (ROLLED_BACK) · a human decision is required (ESCALATE) · cannot/should not continue (ABORT) |

### Decision vocabulary

- **Iteration decisions:** `ADVANCE` (the hypothesis held — evidence-gated, see D-36), `RETRY` (same plan, change the approach — forbidden when the failure signature repeats), `REPLAN` (new plan/hypothesis — mandatory when default-same triggers), `ROLLBACK_ITERATION` (revert the iteration's patch, keep the task).
- **Terminal statuses:** `PASS`, `ROLLED_BACK`, `ESCALATE`, `ABORT`.

### Pseudocode (control layer — `cgel`)

```pseudo
function openIteration(task):
    require task.lifecycle == ACTIVE or task.lifecycle == SEALED
    require budgets.remaining_iterations > 0        # else → BLOCKED(budget-exhausted)
    require governanceBundleDigest() == task.seal.governance_digest
                                                    # else → BLOCKED(bundle-changed)
    append iterations.jsonl {id, hypothesis?, intended_change, expected_checks}

function decide(task, proposal):
    if proposal == RETRY:
        sig = lastFailureSignature()                 # (check_id, failure_kind, failure_subject)
        if countSame(sig) >= 2 and no approved failure_override:
            reject → force REPLAN
        if sig seen after a REPLAN: reject → force ESCALATE or ABORT
    if proposal == REPLAN:
        require budgets.remaining_replans > 0        # else → BLOCKED
    record decision in iterations.jsonl

function proposePass(task):
    require task.lifecycle == ACTIVE
    require governanceBundleDigest() == task.seal.governance_digest
    d = currentDiffDigest()
    for c in task.contract.acceptance_criteria:
        e = findEvidence(c.required_checks,
                         contract_digest = task.seal.contract_digest,
                         governance_digest = task.seal.governance_digest,
                         diff_digest = d, status = pass)
        if missing(e): return BLOCKED("missing or stale evidence: " + c.id)
    if task.seal.semantic_verification.required:
        require validSemanticAttestation(diff_digest = d)   # verifier: 0 blocking findings
    require no unresolved blocking conflict, no expired approval, no scope violation
    verifyChain(evidence.jsonl)                      # tamper-evident check (Profile A)
    writeTerminal(PASS); export attestation per policy
```

## 15.4 Guidebook architecture

**Precedence (final):**

```text
1. Non-overridable safety, authorization, privacy, organization policy
2. Explicit current-task user intent
   (overriding tiers 3–6 only via an exception record in the contract — no silent override)
3. Sealed Task Contract
4. Project Constitution
5. Active rules (deterministic + semantic)
6. Active ADRs
7. Selected skills
8. Approved project references
9. Official external references
10. Repository conventions
11. General model knowledge
```

A conflict within the same tier → a conflict record in the context package; if it blocks an important decision → `ESCALATE`. Authority (`project > team > external-official > external-community`) only ranks within the same tier.

**Constitution** — `.claude/rules/constitution.md`, capped at 1,000–2,000 tokens, always-on. Contains: non-overridable invariants, safety rules, definition of done, precedence, the requirement to use CGEL. Does not contain long tutorials/examples.

**Skills** — native Claude Code skills, thin, with `references/` on demand. Mandatory frontmatter:

```yaml
name: add-agent-tool
description: ...
applies_when: [...]
does_not_apply_when: [...]
required_rules: [SEC-4, TD-2]
required_references: [agent-tool-security]
required_checks: [unit-tests, tool-contract-tests]
protected_capabilities: []          # capabilities the task will need if this skill is used
semantic_review_triggers: [...]
```

Skill = procedure; it does not override rules, and it does not modify the verification requirements of a running task. A new skill must pass the fresh-agent test (an agent given only the skill's files can carry out the procedure) before it enters the guidebook. Deprecation: `status: superseded`, IDs are never reused.

**Semantic rules** — markdown in `docs/standards/`, each rule:

```markdown
## SEC-4 — Do not expose credentials in logs
Blocking: yes            # machine-readable, mandatory
Owner: security-team
Applies-To: src/**
Requirement: ...
Evidence expected: ...
Exceptions: ...
```

Deterministic rules = hooks/permissions/scripts (not prose). A rule YAML metadata engine = LATER (only when a central exception workflow, multi-team ownership, or compliance reporting is needed).

**References** — `docs/standards/reference-index.yaml`, metadata-first:

```yaml
- id: auth-token-standard
  source: docs/security/auth-tokens.md
  authority: project
  status: active            # active | superseded | draft
  version: 3
  owner: security-team
  last_reviewed: 2026-07-01
  review_after: 2026-10-01
  applies_to: {paths: [src/auth/**], task_types: [feature, bug-fix]}
  supersedes: [auth-token-standard-v2]
```

Resolver: metadata/path routing → task/domain routing → lexical fallback (semantic retrieval = LATER). The resolver returns a manifest carrying a digest for each reference (not just the ID). Stale (`now > review_after` or `status != active`): still readable, flagged `STALE`, must not be the sole blocking authority; if there is no active replacement → `ESCALATE`.

**ADRs** — `docs/adr/`, routed through the reference index with `governs.paths`. An active ADR beats skills and repo conventions.

**Loading policy (three rings):** (i) always-on: constitution + contract summary + state summary ≤ ~3k tokens; (ii) intake: the one-line-per-entry indexes; (iii) on-demand: the body of a skill/rule/reference/ADR according to routing. Verifier output capped at ~1.5k tokens. Explorer is used when the codebase is large / the component is unclear / there is a risk of bloat.

**Governance mutability:** the entire guidebook + registry + hook config is **read-only during ACTIVE** (Edit/Write: HARD; any mechanism: EVIDENCE_GATED via the bundle digest in Profile A, HARD in Profile B). They are modified through the protected capabilities: `modify-project-docs` (ordinary), `modify-governance`, `modify-verification-registry`, `modify-hook-policy`, `modify-evaluation-baseline` (all human-sealed).

### AI Standards and Knowledge Impact (settled)

AI is a domain: AI skills (`change-system-prompt`, `add-agent-tool`, `modify-rag-pipeline`, ...), AI rules (`AI-*` IDs), AI references (models/prompts/retrieval/evals/incidents — the shortest `review_after` in the guidebook), AI evals = check IDs in the registry with thresholds. The governance bundle of an AI task additionally contains: `prompt_digest, model_config_digest, eval_suite_digest, eval_dataset_manifest_digest, safety_threshold_digest, tool_schema_digest`. An agent modifying AI behavior cannot at the same time modify the baseline that grades it (`modify-evaluation-baseline` is a separate task). AI task detection in the MVP: deterministic by path/file-type/skill/registry. There is no AI-specific runtime.

## 15.5 Data schemas

**Task Contract** (model-writable in DRAFT; frozen at seal):

```yaml
task: {id: TASK-123, type: feature, goal: "..."}
domains: {primary: backend, additional: [ai-engineering, security]}
acceptance_criteria:
  - {id: AC-1, description: "...", required_checks: [unit-tests, ai-tool-safety-eval]}
scope:
  allowed: [src/agents/refunds/**, tests/agents/refunds/**]
  forbidden: [database migrations, public API contract changes]
protected_capabilities: [external-write]
budgets: {max_iterations: 5, max_replans: 2}
risk: {level: high, reasons: [...]}
exceptions: []            # {target: RULE-ID, approved_by: human, reason, scope, expires_at}
ai: {enabled: true, affected_components: [...], behavior_invariants: [...]}   # optional
```

**Seal artifact** (CGEL runtime state store): as in D-3 of v0.4 — `contract.digest`, `governance_bundle.digest + members[{type,id,digest}]` (registry, constitution, resolved rules/skills/references/ADRs, eval specs/datasets, hook package), `workspace.base_revision + initial_diff_digest`, `approvals.approved_digest`, `semantic_verification.required + reasons` (frozen at seal).

**Iteration record** (`iterations.jsonl`, append-only):

```yaml
{id: 2, hypothesis: {id: H-1, statement: "...", status: active|supported|disproved},
 intended_change: "...", expected_checks: [unit-tests],
 decision: RETRY|REPLAN|ROLLBACK_ITERATION|terminal,
 failure_signature: {check_id, failure_kind, failure_subject, diagnostic_fingerprint},
 failure_override: {previous_signature, classify_as_new: true, reason, evidence}?,
 lesson: "..."}
```

`hypothesis` is guidance-tier (raw material for lessons / the outer PDCA); the guard only uses failure_signature. `failure_kind` enum: `command_unavailable, permission_denied, environment, timeout, build, compile, typecheck, lint, test_assertion, test_crash, security, scope_violation, contract_violation, semantic_rule, unknown`.

**Evidence record** (`evidence.jsonl`, hook-written, hash-chained): as in D-4 of v0.4 — `check{id, registry_digest}`, `sealed_contract_digest`, `sealed_governance_bundle_digest`, `workspace{base_revision, diff_digest}`, `result{status, exit_code, failure_kind?, failure_subject?, diagnostic_fingerprint?}`, `output{digest, summary}`, `chain{previous_record_hash, record_hash}`, `timestamp`.

**Verification registry** (`.cgel/registry.yaml`, governance path):

```yaml
checks:
  unit-tests: {command: npm test, timeout_seconds: 600, working_directory: ., success: {exit_code: 0}}
  eval-groundedness: {command: npm run eval:groundedness, success: {exit_code: 0}, threshold_ref: eval-suite-v5}
```

**Semantic verifier finding:** `{rule_id, status: fail|pass, confidence, evidence: [{path, line}], reason}` — probabilistic evidence; a blocking finding blocks PASS; critical rules may require human review or a dedicated scanner.

**Attestation** (sanitized, export): `{task_id, contract_digest, governance_digest, criteria: [{id, checks: [{check_id, status, output_digest}]}], rule_findings, terminal_status, chain_head, timestamps}` — no raw secrets/logs. Policy: `persistence: local | ci-artifact | pr-comment | repository` (repository is never the default).

**Terminal decision record:** `{task_id, status: PASS|ROLLED_BACK|ESCALATE|ABORT, reason, evidence_chain_head, attestation_ref, timestamp}`.

## 15.6 Claude Code mapping

**Native Claude Code behavior (used as-is):**
- Hooks: `PreToolUse` (block via exit-2), `PostToolUse` (the primary evidence path — a non-zero Bash exit is still a tool success), `PostToolUseFailure` (the secondary path: tool-level failure), `Stop` (bounded continuation), `SessionStart` (inject the state summary on resume).
- Permission system: deny/ask rules; `ask` is the real human boundary for the seal + protected capabilities.
- Subagents: `agents/*.md` with the `tools:` restriction (Verifier/Explorer read-only = HARD).
- Skills: SKILL.md + frontmatter + `references/` progressive disclosure; `.claude/rules/` always-on.
- Plan mode: the affordance corresponding to DRAFT for interactive sessions (read-only before approval).
- Git worktrees: isolation for medium/high-risk & unattended runs.

**Plugin-defined behavior (CGEL plugin):**
- `cgel` CLI: `draft | validate | seal | status | verify <check-id> | audit | attest` — packaged logic, not itself a trust boundary.
- Hook scripts: contract/scope/governance-paths gate; command guard (fail-closed); evidence recorder (hash chain, diff binding, dirty-marking after Edit); stop gate.
- Verification registry, contract/evidence/attestation schemas, seal ceremony, failure guard, attestation exporter.
- Skills: `cgel-task` (intake→draft→seal), `cgel-loop` (cognitive workflow guidance), `cgel-attest`.
- Agents: `explorer.md`, `verifier.md`.

**External scripts/services:** the Profile B boundary (container / separate OS user / Bash sandbox protected mounts / CI runner / remote service); CI acts as the attestation sink and performs re-verification.

**Optional integrations:** an MCP interface for the control plane (to be evaluated after Phase 1); PR/issue approval integration (NEXT); remote audit endpoint.

## 15.7 Plugin file structure

```text
cgel-plugin/                          # plugin (installed per machine)
├── .claude-plugin/plugin.json
├── hooks/hooks.json                  # registers 5 hook events
├── scripts/                          # hook impls, stdlib-only, testable at subprocess level
│   ├── contract_gate.py              #   PreToolUse Edit|Write
│   ├── command_guard.py              #   PreToolUse Bash (fail-closed)
│   ├── evidence_recorder.py          #   PostToolUse + PostToolUseFailure
│   └── stop_gate.py                  #   Stop continuation
├── bin/cgel                          # CLI — one decision line on stdout, errors to stderr
├── agents/{explorer.md, verifier.md}
├── skills/{cgel-task/, cgel-loop/, cgel-attest/}
├── schemas/                          # contract / evidence / attestation JSON Schema
└── tests/                            # subprocess hook tests + e2e demo tasks

project-repo/                         # per-project guidebook (committed, team-owned)
├── .claude/
│   ├── rules/constitution.md         # always-on, cap ~2k tokens
│   ├── skills/<domain-skills>/       # SKILL.md + references/
│   └── settings.json
├── docs/
│   ├── adr/
│   └── standards/                    # semantic rules (RULE IDs) + reference-index.yaml
├── .cgel/                            # gitignored as of D-35 (see below) — local, not committed
│   ├── registry.yaml                 # verification registry (governance path)
│   └── config.yaml                   # attestation/isolation policy
└── .task/                            # gitignored — debug mirror, NOT the source of truth

$PLATFORM_STATE_DIR/cgel/<repo-id>/<task-id>/    # CGEL runtime state store (platform path API)
│   # Profile A: tamper-evident only — same-principal, not a hard trust boundary
│   # Profile B: tamper-proof only when protected by an external boundary
├── sealed_task.yaml · state.json · iterations.jsonl · evidence.jsonl (hash-chained)
└── attestation/
```

The purpose of splitting these three locations: plugin = mechanism (shared by every project); project repo = knowledge + the yardstick (team-owned, reviewed like code); state dir = runtime (not committed, integrity per profile).

**D-35 (post-v1.0 amendment — decided by the project owner, recorded as-is):** `cgel init` gitignores both `.cgel/` and `.task/`. Reason: a plugin must not add files to the git history of the project that uses it. This is a **conscious narrowing** of D-3/§15.7 above — the registry is no longer "the team-owned yardstick, reviewed like code", but becomes local per-machine state.

The cost has been stated and accepted:

1. A fresh clone has no registry → `cgel verify` has no checks to run → no evidence → PASS is unreachable until someone re-registers the checks by hand.
2. The registry is per-machine and not reviewed → every dev (and every agent) writes for themselves the yardstick that grades them. This is a **direct weakening of principle #3** ("the party being evaluated does not hold the yardstick") — the `echo tests passed` vector from §15.8 Phase 1 is now stopped only by the permission prompt, no longer by code review.
3. There can be no test asserting that CI runs exactly the checks in the registry (CI has no registry to compare against).

Point 2 is a genuine contradiction with principle #3, not an implementation detail. It is recorded here so that a later reader still sees it — if one wishes to restore it, remove `.cgel/` from `GITIGNORE_ENTRIES` in `bin/cgel` and commit the registry again.

**D-36 (post-v1.0 amendment — four gaps found by running CGEL on itself):** the first real dogfooding pass hit four places where the design's own prescribed path did not work, so that the honest move looked like an override. Overrides that are mandatory on the normal path stop being decisions and become noise, which is how a gate quietly dies.

1. **`ADVANCE` joins the iteration decision vocabulary** (§15.3). There was no success-shaped decision, so a passing iteration had to be logged as `RETRY` ("same plan, change the approach") or spend `REPLAN` budget. The retry-rate metric of §15.10 was therefore counting successes as retries and measuring nothing. `ADVANCE` is **evidence-gated**: it is refused unless every `expected_checks` entry of the open iteration has fresh passing evidence bound to the current seal and workspace, and refused when the iteration declared no expected checks. This is not decoration — an ungated `ADVANCE` would be a hole straight through the default-same guard, letting a failed check be carried forward under a success-shaped label.
2. **A task may reseal itself from `SEALED`/`ACTIVE`, not only from `BLOCKED`.** The task skill answers a wrongly-blocked path with "tell the user, amend the contract, and reseal", but the CLI refused to reseal an open task, so the prescribed escape hatch was reachable only by accident — when something else had already forced `BLOCKED`. Sealing a *different* task over an open one is still refused, and the exact-digest match and human `seal_mode` are unchanged: amendment stays a deliberate, re-approved act.
3. **The dirty-tree check now distinguishes the task's own authorised work from the user's.** A reseal happens mid-flight, so the task's in-scope edits are necessarily uncommitted; counting them as "the user's work" made `--allow-dirty` mandatory on the one path the design prescribes. On reseal, paths already inside the *previously sealed* `scope.allowed` no longer block. Paths outside it still do, and a task's first seal is unchanged.
4. **A `modify-governance` task can now finish cleanly.** This follows from (2) and (3); nothing about the guard itself was relaxed. **The `sealed-guidebook-bundle-changed → BLOCKED` rule is deliberately kept**: a task that edits the measure and keeps running would be grading itself against a yardstick it just wrote — principle #3 inverted. The reseal is where a human re-approves the new measure, and that is the point, not an obstacle. The fix was to make the recovery reachable, not to remove the guard.

Also fixed while here: a reseal rewrote `state.json` wholesale and silently dropped `budget_extra_iterations` / `budget_extra_replans`, revoking budget the user had granted with `cgel unblock`. Budgets are the user's to widen (§15.1, principle 6); taking one back without asking is the same violation mirrored.

**D-37 (post-v1.0 amendment — the registry may not accept a check that cannot fail):** `cgel check add` now runs the command in an empty temporary directory before registering it. A check that still exits 0 where the project is absent is not measuring the project, and is refused; `--allow-unproven` overrides and records `unproven: true` on the entry, so the admission travels with the yardstick instead of scrolling out of a terminal. `cgel check doctor` re-runs every canary.

Why this is an addition rather than a correction, stated plainly:

1. **Vacuity at registration already had an answer, and it was §15.7:** the registry is a governance path, team-owned, *reviewed like code*. §15.8 Phase 1's goal ("`echo tests passed` is worthless") rested on a human reading the diff. **D-35 removed the reviewer** — the registry is gitignored, so there is no diff and no reviewer. This half of D-37 compensates for D-35; it is not a gap in the v1.0 design.
2. **Rot had no answer at all, and that is a real gap.** This repo's `compileall -q scripts bin/cgel` was correct when written and went vacuous months later when the payload moved. Review cannot catch that — it happens after review. §15.4 gives *references* a staleness rule (`review_after`); *checks* had no equivalent. `check doctor` is that equivalent, and it belongs in the release preflight, which is exactly where this repo's own rot would have surfaced.

Honest scope, per principle 1: the canary is **EVIDENCE_GATED** and **catches mistakes, not adversaries** — a command can be built to fail in an empty directory and still verify nothing. It does not make the registry trustworthy; it raises the floor from "any non-empty string" to "something that breaks when the project breaks". The yardstick is still authored by whoever runs `check add`, which is why principle #3 still wants a human near it.

One consequence worth recording: the canary refuses commands that no-op on missing input — `compileall -q src` is denied, `test -d src && compileall -q src` is accepted. That looks strict until you notice the bare form cannot distinguish "src compiles" from "src is gone", which is the whole failure. The refusal teaches the fix.

A note on what D-37 makes unreachable: because rot-prone commands are now refused at registration, the "check registered fine, then rotted" path is largely closed at the source. `check doctor` therefore earns its keep mainly on registries written by earlier versions — every existing one — and on `--allow-unproven` entries.

**D-38 (post-v1.0 amendment — approval by question replaces the typed ceremony):** the human anchor for `seal`, `unblock`, failure overrides, `check add --force/--allow-unproven`, `check remove`, `--allow-dirty`, and guarded destructive git moves from "the user approves a Bash permission prompt or types the command" to "the user answers one AskUserQuestion whose text carries the binding token (a seal's digest prefix, otherwise the exact command), recorded by the harness in the session transcript". A PreToolUse gate (`approval_gate.py`) denies the gated command without a matching un-consumed recent answer whose label starts with "Approve", and auto-allows it (suppressing the permission prompt — one gate, not two) with one. Approvals are consumed on use; a seal approval stays valid for resealing the identical digest, because the user approved the artifact, not the keystroke. Why: three days of dogfooding measured the typed ceremony as the single largest wall-clock cost — seals stalled 12, 23 and 77 minutes at prompts, the user typed `cgel seal`/`cgel unblock` by hand five times and asked "why i need to run cgel seal manual ?". Honesty (per principle 1): the transcript is a same-principal file on Profile A, so this anchor is HUMAN_GATED but tamper-evident, not tamper-proof — one notch below the permission prompt, which remains available (`approval_gate: off` + `ask` rules). The model can also word a question misleadingly; the binding token bounds that (the digest names the exact contract, the quoted command names the exact action), it does not eliminate it.

**D-39 (post-v1.0 amendment — several open tasks per repo):** the CURRENT pointer is gone; every task whose `state.json` is SEALED/ACTIVE/BLOCKED is open, `--task <id>` addresses each verb (required exactly when more than one is open), parallel drafts live at `.task/<id>.contract.json` via `--contract`, and the edit gate allows a path when ANY open task's sealed scope covers it. Sealing a second task warns on scope overlap instead of refusing. Why: the single slot made real sessions steal each other's iterations twice in one day (a woken session decided the deck task's iteration; the deck session decided the demo task's, whose owner then got `DECIDE DENIED — no open iteration`), and it turned "amend the contract" into "abort the task". What this does NOT change: the workspace and its diff digest stay repo-wide — parallel tasks stale each other's unwatched evidence, and that is honest, because the checks run against the shared tree. Consequences accepted: tasks left open by older versions become visible (status lists them; `close --task` retires them), and `cgel close` now deletes the matching draft while a fresh seal of a closed id archives the old directory rather than inheriting its spent budgets.

**D-40 (post-v1.0 amendment — the loop costs roundtrips, not just tokens):** `cgel verify` takes many check ids and `--required`; `cgel iterate decide --verify` freshly runs the open iteration's expected checks before judging the decision; decisions accept unique prefixes; `--change`/`--expect` alias the long flags; `iterate open` warns when no expected checks are declared (ADVANCE would be structurally refused later); `summary` subsumes `validate`; `cgel schema` prints shipped schemas so nobody hunts the versioned plugin cache. Why: a one-line version bump measured 27 minutes, 15 cgel calls, 3 denials and 2 `--help` lookups; `iterate`+`verify` were 55% of 432 recorded invocations; the agent that wrote the CLI still ran `--help` 11 times for `decide` alone.

**D-41 (post-v1.0 amendment — the guard must not act on superseded failures):** `latest_failure_signature` now returns the newest failing evidence only if no later pass of the same check superseded it. Twice in real use a stale signature tripped default-same on finished work — once forcing an unwanted ROLLBACK label, once forcing an ESCALATE close of fully verified work plus an entire second contract for a one-line fix. The guard's purpose is repeated *live* failure, not memory of a fixed one.

**D-42 (post-v1.0 amendment — watch-scoped staleness, opt-in per check):** a registry entry may declare `watch` globs; its evidence then goes stale only when a changed path matches (per-path digests ride in workspace snapshots), while a moved HEAD stales everything unconditionally. No `watch` keeps the exact any-change-stales rule. Why: the honest-but-blunt rule re-ran a 35-second suite for README edits, and under D-39 it would make parallel tasks grind each other. Honesty: the watch list is authored with the check and trusted exactly as far as the command itself (D-37) — a wrong watch is a wrong yardstick, and doctor cannot see it.

**D-43 (post-v1.0 amendment — bundle digest caching and excludes):** governance-bundle file digests are cached by (mtime_ns, size) in the runtime state store — same principal, so nothing Profile A had not already conceded — and `.cgel/config.json` `bundle_exclude` globs drop churn-prone paths from the sealed measure while leaving them edit-gated. The config file itself is always digested, so an exclusion cannot arrive invisibly mid-task. Why: a gitignored repo-local skill voided open seals three times in one session, each void costing summary + reseal + a full re-verify; the sealed-guidebook-bundle-changed → BLOCKED rule itself is deliberately kept (D-36 explains why), this only stops files that are not anyone's yardstick from pulling the trigger, and D-38 makes the recovery cheap (same digest, no new approval).

**D-44 (post-v1.0 amendment — model routing and the worker):** the explorer runs on a fast model (`model: sonnet`), the verifier on a strong one (`model: opus`), and a new `worker` agent (sonnet; Read/Grep/Glob/Edit/Write, no Bash) executes precisely-specified mechanical changes inside the sealed scope — contract decisions, the loop, and every cgel command stay with the main model. Why: the user asked for exactly this split ("can we make the opus for plan and the sonnet for coding"), and the hooks make it safe — the worker's edits pass through the same contract gate and recorder as anyone else's.

## 15.8 MVP implementation plan (walking skeleton)

**Phase 0 — Contract & Scope Gate.** Goal: application code cannot be modified before the seal or outside scope. Components: contract schema + `cgel draft/validate/seal` + normalized summary + digest approval + contract_gate + governance protected paths + dirty-tree detection. Tests: subprocess hook tests (JSON stdin → assert exit code/stderr); e2e: one low-risk auto-seal task + one human-seal task. Risks: the gate is too annoying → a deliberate kill-switch, fail-open for malformed input at the convenience gate, fail-closed at the command guard. Exit: exactly as in v0.4 §F, with the limitation spelled out: Profile A does not yet block Bash-writes.

**Phase 1 — Evidence.** Goal: `echo tests passed` is worthless; the PASS validator works. Components: registry + recorder (two events) + diff binding + bundle binding + hash chain + candidate audit anchor (dual-sink) + `cgel verify/audit`. Tests: forging evidence locally → `cgel audit` detects it; modifying the registry after the seal → BLOCKED. Risks: the hook payload differs from assumptions (V-4) — isolated behind an adapter. Exit: as in v0.4 §F.

**Phase 2 — Loop Control.** Goal: real budgets + failure guard. Components: iteration records, budget accounting from the store, default-same guard + override schema, BLOCKED semantics, stop gate, resume protocol (SessionStart injects the summary). Tests: a second same-failure is refused RETRY; budget exhausted → BLOCKED; resume preserves the chain. Exit: as in v0.4 §F.

**Phase 3 — Semantic Layer.** Goal: one real end-to-end task with an attestation. Components: Verifier + rule IDs + frozen trigger + findings schema + attestation exporter + optional Explorer + one sample AI skill + eval check. Tests: a blocking violation blocks PASS; the verifier has no write tool; an AI task runs through the same pipeline. Exit: as in v0.4 §F.

**After Phase 1:** decide CLI-only vs adding an MCP interface, using real data. **Migration path:** each phase stands on its own — a team can stop at Phase 0 (scope gate only) and still get value; the guidebook is written incrementally (constitution → 3–5 skills → rules → references), completeness is not required on day one.

## 15.9 Failure modes

| Failure mode | Detection | Response |
|---|---|---|
| Wrong skill selection | `applies_when/does_not_apply_when` at resolution; the verifier fails rules the skill skipped | REPLAN with a different skill; lesson → outer loop |
| Conflicting rules | conflict record at resolution | do not self-select; if it blocks a decision → ESCALATE; exception via a contract record |
| Stale references | `review_after`/`status` → STALE flag | not the sole blocking authority; no active replacement → ESCALATE |
| Missing ADR | an architecture-sensitive change with no governing ADR | a reversible assumption that is logged, or ESCALATE if irreversible; a new ADR = a `modify-governance` task |
| Invalid hypothesis | a failing check refutes the hypothesis | REPLAN; the `disproved` hypothesis is retained in iterations.jsonl |
| Test failure | evidence FAIL + failure_signature | RETRY/REPLAN per the default-same guard |
| Scope expansion | PreToolUse block | ESCALATE + contract amendment → reseal |
| Repeated retry | default-same guard | 2nd time → forced REPLAN; still repeating after a REPLAN → ESCALATE/ABORT |
| Context overload | ring budgets blown, coherence degrades | Explorer for broad reading; BLOCKED + resume from a compact summary in the store |
| Verifier disagreement | a verifier blocking finding vs the main agent's objection | verifier is block-only; the main agent may challenge once with evidence; if disagreement remains → ESCALATE, never self-override |
| Interrupted session | state + chain in the runtime state store | resume: SessionStart injects the summary; re-check the bundle digest before continuing |
| Uncommitted user changes | dirty-tree detection from Phase 0 | intersects scope → escalate/user confirm; worktree via copy-in/patch-out; rollback never touches the checkout |
| Missing credentials | `failure_kind: permission_denied/environment` | BLOCKED (no RETRY); the user is required |
| Unsafe operation request | precedence #1 + command guard fail-closed | deny + explicit ESCALATE; never silent |

## 15.10 Evaluation metrics

Measurement sources: attestations + iterations.jsonl + hook logs (everything is already recorded by design).

- **Effectiveness:** first-pass success rate; average iterations/task; retry rate; replan rate; time-to-PASS; token cost/task.
- **Safety:** scope-violation attempts (hook blocks); evidence-gate rejections (proposePass refused); governance-bundle-changed incidents; escaped defect rate (regressions after PASS); rollback count.
- **Guidebook:** retrieval precision (references loaded vs cited in decisions); stale-reference incidents; the verifier's rule-citation rate; skill fresh-agent test pass rate.
- **Human:** human escalation rate (of the right kind — a "good" escalation is the kind that blocks a dangerous action); approval latency.
- **MVP acceptance thresholds (proposed):** 0 PASSes lacking evidence (per audit); 0 scope violations slipping past the Edit/Write gate; the default-same guard triggers correctly ≥ 90% on the demo failure set; verifier output ≤ cap on 95% of runs.

## 15.11 Final decision log

**Accepted (D-1 … D-34):** D-1..D-30 as in ChatGPT's v0.4 decision log (kept verbatim), plus: `D-31` — the detailed capability taxonomy (`modify-project-docs/governance/verification-registry/hook-policy/evaluation-baseline`); `D-32` — the Profile A audit anchor follows a dual-sink policy (a local append-only log + one exportable/user-visible sink), `additionalContext` is only a candidate anchor; `D-33` — `ROLLED_BACK` is a persisted terminal status, `ROLLBACK_ITERATION` is an iteration decision; `D-34` — every use of "trusted store" is replaced by "CGEL runtime state store" with a per-profile qualifier (Profile A: local, tamper-evident, same-principal, not a hard trust boundary; Profile B: protected, tamper-proof within the declared isolation boundary) — ChatGPT's Round 6 sign-off condition.

**Rejected (X-1 … X-12):** as in v0.4 (from load-the-entire-guidebook through commit-attestations-by-default).

**Important trade-offs accepted:** (1) Profile A trades tamper-proofing for convenience — compensated by tamper-evidence + honest documentation; (2) the sealed bundle trades mid-task flexibility for the integrity of the yardstick — modifying the guidebook mid-flight demands a reseal; (3) the conditional verifier trades coverage for cost — compensated by deterministic checks always being mandatory; (4) CLI-first trades a beautiful API for validation speed — MCP awaits Phase 1 data.

**Validation backlog (prototype facts, not architecture):** `V-1` audit sink portability & user-visibility (Q-10); `V-2` copy-in/patch-out with rename/binary/submodule (Q-11); `V-3` failure normalization across pytest/Jest/Cargo (Q-12); `V-4` Stop bound + PostToolUse/PostToolUseFailure payload; `V-5` apply-back 3-way conflicts.

**Deferred questions:** MCP interface (after Phase 1); the choice of the Profile B boundary according to the deployment environment; rule YAML governance (LATER, per the D-12 criteria).

---

## Final status

ChatGPT gave the final sign-off in Round 6 with exactly one condition: replace every use of "trusted store" with "CGEL runtime state store" plus a per-profile qualifier. I confirm that this correction is consistent with the agreed trust model (D-13, D-17, D-26, X-8 — a file's location does not create a trust boundary; only a boundary outside the agent principal raises assurance to tamper-proof), that it has been applied throughout the document, and that it is recorded as D-34.

The debate is closed. **Contract-Gated Evidence Loop — CGEL v1.0** is the final architecture approved by both parties. After the D-34 correction, the document contains no assurance claim that exceeds the actual boundary of its corresponding deployment profile.
