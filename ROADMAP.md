# CGEL — ROADMAP

**This is a wish list, not a plan.** Nothing here is built, scheduled, or
committed to. It is kept because the ideas are good and the reasoning is
worth preserving — not because anyone is working on them.

It lives outside ARCHITECT.md deliberately. ARCHITECT.md is the *design
record*: it describes what exists and why it was decided. These two
sections sat inside it describing a system that does not exist — roughly
35 guidebook concepts of which about 5 are implemented, and 0 of 7
evaluation metrics. Every reader who reached them, including three of five
independent reviewers in a design debate, read them as a roadmap and
proposed finishing them. A design record that mixes what-is with
what-might-be teaches its readers to propose the wrong work.

Before building anything below, price it against the alternative of
deleting it. The metrics section in particular cannot be built honestly
until the evidence chain it aggregates has no silent holes.

---

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

---

## 15.10 Evaluation metrics

Measurement sources: attestations + iterations.jsonl + hook logs (everything is already recorded by design).

- **Effectiveness:** first-pass success rate; average iterations/task; retry rate; replan rate; time-to-PASS; token cost/task.
- **Safety:** scope-violation attempts (hook blocks); evidence-gate rejections (proposePass refused); governance-bundle-changed incidents; escaped defect rate (regressions after PASS); rollback count.
- **Guidebook:** retrieval precision (references loaded vs cited in decisions); stale-reference incidents; the verifier's rule-citation rate; skill fresh-agent test pass rate.
- **Human:** human escalation rate (of the right kind — a "good" escalation is the kind that blocks a dangerous action); approval latency.
- **MVP acceptance thresholds (proposed):** 0 PASSes lacking evidence (per audit); 0 scope violations slipping past the Edit/Write gate; the default-same guard triggers correctly ≥ 90% on the demo failure set; verifier output ≤ cap on 95% of runs.

---

## UI

**Read-only local dashboard (`cgel ui`)** — the next candidate. A stdlib
`http.server` bound to `127.0.0.1` on an ephemeral port, hand-written
HTML/CSS in a Linear-style dark theme, rendering what the store already
knows: open tasks, contracts, iterations, evidence chain, check results,
roadmap. Constraints settled in review: it must be a subcommand (bare
`cgel` is a fast usage-error the model itself invokes; a blocking server
there would hang the model's Bash call, so `ui` is a human-typed command
the model must never run); handlers strictly read-only; task/reason text is
model-authored and must be HTML-escaped; and every verdict it renders must
come from the same helpers `cgel status` uses — some of those live in
`bin/cgel` today and would move to `cgel_common` first, because two
implementations of one verdict is the disease D-48 names.

**Browser-driven interaction with the model** — deferred, explicitly. A
plugin's injection points are hooks, all triggered by the model's own
actions; nothing lets a web click wake or drive the model, and a
UI-writes-a-queue-file scheme is typing with extra steps plus an unscoped
write path. Approvals CANNOT move to the browser under the current trust
model either: an approval is real because it is the user's recorded answer
in the transcript, which the gate verifies — a browser click cannot create
that record, and a side channel that fakes it would hollow out the seal.
Revisit only if/when an MCP interface exists (see "After Phase 1" in
§15.8 of ARCHITECT.md).
