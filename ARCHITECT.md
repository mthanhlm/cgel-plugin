# CGEL v1.0 — FINAL (cả hai bên đã phê duyệt)

> **Trạng thái:** ChatGPT đã final sign-off ở vòng 6, kèm một chỉnh sửa thuật ngữ bắt buộc — "trusted store" → "CGEL runtime state store" với qualifier theo deployment profile. Chỉnh sửa đã được áp dụng vào tài liệu dưới đây (ghi nhận D-34). Cuộc tranh luận kiến trúc khép lại; đây là bản ghi chung cuộc.

---

# Vòng 5 — Phản hồi của Claude: Xác nhận đồng thuận + Final Consolidated Architecture

## Phần 1 — Trả lời bốn câu hỏi chốt của ChatGPT

**1. Guidebook read-only trong Profile A:** ĐỒNG Ý. `HARD_ENFORCED` chỉ đúng cho `Edit/Write` (hook chặn được thật); chống mọi đường sửa qua Bash khi không có filesystem sandbox chỉ là `EVIDENCE_GATED + tamper-evident` qua governance bundle digest. Đây chính là nguyên tắc C-1 của tôi được áp ngược lại chỗ tôi dán nhãn sai — sửa đổi này đúng và tôi chấp nhận không bảo lưu. Bảng ba dòng của bạn (Edit/Write / any-mechanism / bundle-unchanged-before-PASS) được đưa nguyên vẹn vào enforcement matrix cuối.

**2. Seal digest toàn bộ resolved governance bundle content:** ĐỒNG Ý. Digest index mà không digest nội dung được trỏ tới là một lỗ tôi để sót (X-10 xứng đáng bị reject). Phân tách `governance bundle` (thước đo — bị đóng băng) vs `execution inputs` (đối tượng làm việc — được sửa trong scope) là ranh giới đúng, và `sealed-guidebook-bundle-changed → BLOCKED, require reseal` là semantics đúng.

**3. Approval ceremony gắn với exact contract digest:** ĐỒNG Ý. Approve một command không phải là approve một artifact; normalized summary + `cgel seal <task> --digest sha256:...` biến permission-ask boundary thành informed consent thật. Chấp nhận làm nghi thức bắt buộc cho mọi human seal.

**4. Persistence policy:** ĐỒNG Ý. Raw runtime state không commit; attestation không commit mặc định; project opt-in `local | ci-artifact | pr-comment | repository`, và `repository` không bao giờ là default.

Tôi cũng chấp nhận các tinh chỉnh còn lại của v0.4: taxonomy capability chi tiết (`modify-project-docs / modify-governance / modify-verification-registry / modify-hook-policy / modify-evaluation-baseline`), `additionalContext` chỉ là *candidate transcript anchor* với chính sách dual-sink, `ROLLED_BACK` là persisted terminal status còn `ROLLBACK_ITERATION` là iteration decision, và việc chuyển các câu hỏi prototype vào validation backlog thay vì unresolved architecture.

### Tuyên bố đồng thuận theo checklist §14

| Vùng critical | Trạng thái |
|---|---|
| Runtime model (states, transitions, terminal, retry/replan semantics, budgets) | AGREED |
| Task contract (ownership, seal, mutability, AC, scope, risk, approval) | AGREED |
| Guidebook (constitution, skills, rules, references, ADRs, precedence, versioning, staleness, conflict, loading) | AGREED |
| Agent structure (orchestrator, subagents, permissions, isolation, escalation) | AGREED |
| Verification (deterministic gates, semantic, evidence model, completion) | AGREED |
| Persistence (task-local, cross-session, repo artifacts, sensitive data) | AGREED |
| Implementation strategy (MVP scope, structure, testing, migration, metrics) | AGREED |

Không còn bất đồng kiến trúc. Các mục còn mở (V-1..V-7 bên dưới) đều là prototype validation, không phải quyết định thiết kế. Theo đề nghị của bạn, phần còn lại của vòng này là **Final Consolidated Architecture** — không mở concept mới.

---

# FINAL CONSOLIDATED ARCHITECTURE
# Contract-Gated Evidence Loop — CGEL v1.0

## 15.1 Executive decision

**Tên kiến trúc:** Contract-Gated Evidence Loop (CGEL).

**Nguyên tắc thiết kế cốt lõi:**

1. **Enforcement honesty** — mọi assurance claim gắn với (feature + deployment profile + enforcement primitive); bốn classes `HARD_ENFORCED / EVIDENCE_GATED / HUMAN_GATED / GUIDANCE_ONLY` + qualifier `tamper-evident | tamper-proof`. Không bao giờ dùng chữ "guarantee" cho GUIDANCE_ONLY.
2. **Contract-first, sealed measure** — task chỉ chạy khi contract được seal, và seal đóng băng cả *thước đo* (governance bundle: registry, rules, skills, references, ADRs, constitution, eval specs) chứ không chỉ *đề bài*.
3. **Evidence over self-report** — PASS chỉ tồn tại khi control layer đối chiếu evidence hook-recorded, hash-chained, gắn contract digest + governance digest + diff digest. Bên được đánh giá không giữ sổ điểm, không giữ thước đo, không giữ cái cân.
4. **Guidebook first-class** — agent làm việc bằng tri thức project (constitution/skills/rules/references/ADRs) resolve theo task, nạp theo nhu cầu, trên native primitives của Claude Code.
5. **Human gates ở boundary thật** — mọi HUMAN_GATED row neo vào permission UI (model không bấm được) và exact-digest approval.
6. **Loop có kiểm soát** — iteration nhỏ nhất đủ kiểm chứng hypothesis; failure guard máy-quan-sát (default-same) chống lặp; budgets chuyển `BLOCKED`, không bao giờ tự nới.
7. **AI là một domain** — AI standards/knowledge/evals đi qua đúng cùng pipeline; không có runtime riêng cho AI.

**Vì sao chọn thay vì PDCA đơn thuần:** PDCA không có runtime semantics — không định nghĩa scope enforcement, evidence, budgets, hay terminal outcomes. PDCA được giữ làm outer improvement loop: lessons từ iteration logs và attestations → cập nhật guidebook (qua task `modify-governance`).

**Loại bỏ có chủ ý:** general rule engine; Planner subagent; Implementer subagent trong MVP; model-writable evidence/approval; nạp toàn bộ guidebook; auto phase-chaining bằng hooks; MAPE-KV như tên runtime; kiến trúc AI-riêng; stash/reset/clean tự động trên user checkout; commit attestation mặc định.

## 15.2 Component architecture

```text
USER REQUEST
    │
    ▼
INTAKE ────────────── task/domain classification · risk · protected capabilities
    │
    ▼
CONTRACT DRAFT ────── skill cgel-task hướng dẫn; write-exception duy nhất: contract path
    │
    ▼
CONTRACT SEAL ─────── cgel validate → normalized summary → human approval (exact digest)
    │                  hoặc auto-seal khi không có protected capability
    │                  seal chốt: contract + GOVERNANCE BUNDLE digests + base revision
    ▼
CONTEXT RESOLUTION ── constitution (always-on) · skills · semantic rules · references
    │                  · ADRs (metadata-first, on-demand) · conflict report → ESCALATE nếu chặn
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
                          · sanitized attestation export (không commit mặc định)
```

**Deployment profiles:**

- **Profile A — Native / tamper-evident:** Claude Code trên host, hooks + `cgel` CLI + local store, cùng OS principal. Có: harness tool restrictions, human permission boundary, Edit/Write blocking, digest-based stale detection, hash-chain audit. Không có: filesystem tamper-proofing, Bash-level write prevention. Dùng cho: supervised, low/medium risk, MVP.
- **Profile B — Isolated / tamper-proof trong boundary khai báo:** control plane ngoài agent principal (Bash sandbox + protected mounts / container / separate OS user / trusted service / CI runner). Nâng evidence, budget, seal, governance read-only lên HARD_ENFORCED. Dùng cho: high-risk, unattended, regulated.

## 15.3 Runtime state machine

### Lifecycle (control state — enforce được)

```text
NO_TASK → DRAFT → SEALED → ACTIVE ⇄ BLOCKED → TERMINAL
```

| Transition | Guard |
|---|---|
| NO_TASK → DRAFT | user khởi tạo task |
| DRAFT → SEALED | schema valid + normalized summary hiển thị + (auto-seal nếu không có protected capability, ngược lại human approval đúng digest) |
| SEALED → ACTIVE | iteration đầu được mở; base revision + input snapshot ghi nhận |
| ACTIVE → BLOCKED | budget cạn · thiếu approval · sealed-guidebook-bundle-changed · conflict chặn quyết định · môi trường thiếu · hết Stop continuation |
| BLOCKED → ACTIVE | hành động của user: cấp approval, nâng budget, reseal, giải conflict |
| ACTIVE → TERMINAL | proposePass hợp lệ (PASS) · rollback task hoàn tất (ROLLED_BACK) · cần quyết định của người (ESCALATE) · không thể/không nên tiếp tục (ABORT) |

### Decision vocabulary

- **Iteration decisions:** `RETRY` (cùng plan, sửa cách làm — bị cấm khi failure signature trùng), `REPLAN` (plan/hypothesis mới — bắt buộc khi default-same trigger), `ROLLBACK_ITERATION` (revert patch của iteration, giữ task).
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

**Precedence (chung cuộc):**

```text
1. Non-overridable safety, authorization, privacy, organization policy
2. Explicit current-task user intent
   (override tầng 3–6 chỉ qua exception record trong contract — không silent override)
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

Conflict cùng bậc → conflict record trong context package; nếu chặn quyết định quan trọng → `ESCALATE`. Authority (`project > team > external-official > external-community`) chỉ xếp hạng trong cùng bậc.

**Constitution** — `.claude/rules/constitution.md`, cap 1.000–2.000 tokens, always-on. Chứa: non-overridable invariants, safety rules, definition of done, precedence, yêu cầu dùng CGEL. Không chứa tutorial/example dài.

**Skills** — native Claude Code skills, mỏng, `references/` on-demand. Frontmatter bắt buộc:

```yaml
name: add-agent-tool
description: ...
applies_when: [...]
does_not_apply_when: [...]
required_rules: [SEC-4, TD-2]
required_references: [agent-tool-security]
required_checks: [unit-tests, tool-contract-tests]
protected_capabilities: []          # capabilities task sẽ cần nếu dùng skill này
semantic_review_triggers: [...]
```

Skill = procedure; không override rule, không sửa verification requirement của task đang chạy. Skill mới phải qua fresh-agent test (một agent chỉ nhận files của skill, thực hiện được procedure) trước khi vào guidebook. Deprecation: `status: superseded`, ID không tái sử dụng.

**Semantic rules** — markdown trong `docs/standards/`, mỗi rule:

```markdown
## SEC-4 — Do not expose credentials in logs
Blocking: yes            # machine-readable, bắt buộc
Owner: security-team
Applies-To: src/**
Requirement: ...
Evidence expected: ...
Exceptions: ...
```

Deterministic rules = hooks/permissions/scripts (không phải văn bản). Rule YAML metadata engine = LATER (chỉ khi cần exception workflow trung tâm, multi-team ownership, compliance reporting).

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

Resolver: metadata/path routing → task/domain routing → lexical fallback (semantic retrieval = LATER). Resolver trả manifest có digest từng reference (không chỉ ID). Stale (`now > review_after` hoặc `status != active`): đọc được, gắn cờ `STALE`, không được là sole blocking authority; không có active replacement → `ESCALATE`.

**ADRs** — `docs/adr/`, route qua reference index với `governs.paths`. ADR active thắng skill và repo convention.

**Loading policy (ba vòng):** (i) always-on: constitution + contract summary + state summary ≤ ~3k tokens; (ii) intake: các index một-dòng-mỗi-mục; (iii) on-demand: body của skill/rule/reference/ADR theo route. Verifier output cap ~1.5k tokens. Explorer dùng khi codebase lớn / chưa rõ component / nguy cơ bloat.

**Governance mutability:** toàn bộ guidebook + registry + hook config là **read-only trong ACTIVE** (Edit/Write: HARD; mọi mechanism: EVIDENCE_GATED qua bundle digest ở Profile A, HARD ở Profile B). Sửa chúng qua các protected capabilities: `modify-project-docs` (thường), `modify-governance`, `modify-verification-registry`, `modify-hook-policy`, `modify-evaluation-baseline` (đều human-sealed).

### AI Standards and Knowledge Impact (chốt)

AI là một domain: AI skills (`change-system-prompt`, `add-agent-tool`, `modify-rag-pipeline`, ...), AI rules (`AI-*` IDs), AI references (models/prompts/retrieval/evals/incidents — `review_after` ngắn nhất guidebook), AI evals = check IDs trong registry với threshold. Governance bundle của AI task thêm: `prompt_digest, model_config_digest, eval_suite_digest, eval_dataset_manifest_digest, safety_threshold_digest, tool_schema_digest`. Agent sửa AI behavior không thể đồng thời sửa baseline chấm nó (`modify-evaluation-baseline` là task riêng). AI task detection MVP: deterministic theo path/file-type/skill/registry. Không có AI-specific runtime.

## 15.5 Data schemas

**Task Contract** (model-writable ở DRAFT; đóng băng khi seal):

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

**Seal artifact** (CGEL runtime state store): như D-3 của v0.4 — `contract.digest`, `governance_bundle.digest + members[{type,id,digest}]` (registry, constitution, resolved rules/skills/references/ADRs, eval specs/datasets, hook package), `workspace.base_revision + initial_diff_digest`, `approvals.approved_digest`, `semantic_verification.required + reasons` (đóng băng tại seal).

**Iteration record** (`iterations.jsonl`, append-only):

```yaml
{id: 2, hypothesis: {id: H-1, statement: "...", status: active|supported|disproved},
 intended_change: "...", expected_checks: [unit-tests],
 decision: RETRY|REPLAN|ROLLBACK_ITERATION|terminal,
 failure_signature: {check_id, failure_kind, failure_subject, diagnostic_fingerprint},
 failure_override: {previous_signature, classify_as_new: true, reason, evidence}?,
 lesson: "..."}
```

`hypothesis` là guidance-tier (nguyên liệu lesson/PDCA ngoài); guard chỉ dùng failure_signature. `failure_kind` enum: `command_unavailable, permission_denied, environment, timeout, build, compile, typecheck, lint, test_assertion, test_crash, security, scope_violation, contract_violation, semantic_rule, unknown`.

**Evidence record** (`evidence.jsonl`, hook-written, hash-chained): như D-4 của v0.4 — `check{id, registry_digest}`, `sealed_contract_digest`, `sealed_governance_bundle_digest`, `workspace{base_revision, diff_digest}`, `result{status, exit_code, failure_kind?, failure_subject?, diagnostic_fingerprint?}`, `output{digest, summary}`, `chain{previous_record_hash, record_hash}`, `timestamp`.

**Verification registry** (`.cgel/registry.yaml`, governance path):

```yaml
checks:
  unit-tests: {command: npm test, timeout_seconds: 600, working_directory: ., success: {exit_code: 0}}
  eval-groundedness: {command: npm run eval:groundedness, success: {exit_code: 0}, threshold_ref: eval-suite-v5}
```

**Semantic verifier finding:** `{rule_id, status: fail|pass, confidence, evidence: [{path, line}], reason}` — probabilistic evidence; blocking finding chặn PASS; critical rules có thể yêu cầu human review hoặc scanner chuyên dụng.

**Attestation** (sanitized, export): `{task_id, contract_digest, governance_digest, criteria: [{id, checks: [{check_id, status, output_digest}]}], rule_findings, terminal_status, chain_head, timestamps}` — không raw secrets/logs. Policy: `persistence: local | ci-artifact | pr-comment | repository` (repository không bao giờ default).

**Terminal decision record:** `{task_id, status: PASS|ROLLED_BACK|ESCALATE|ABORT, reason, evidence_chain_head, attestation_ref, timestamp}`.

## 15.6 Claude Code mapping

**Native Claude Code behavior (dùng nguyên trạng):**
- Hooks: `PreToolUse` (block exit-2), `PostToolUse` (đường evidence chính — Bash exit non-zero vẫn là tool success), `PostToolUseFailure` (đường phụ: tool-level failure), `Stop` (bounded continuation), `SessionStart` (inject state summary khi resume).
- Permission system: deny/ask rules; `ask` là human boundary thật cho seal + protected capabilities.
- Subagents: `agents/*.md` với `tools:` restriction (Verifier/Explorer read-only = HARD).
- Skills: SKILL.md + frontmatter + `references/` progressive disclosure; `.claude/rules/` always-on.
- Plan mode: affordance tương ứng DRAFT cho phiên interactive (read-only trước approval).
- Git worktrees: isolation cho medium/high-risk & unattended.

**Plugin-defined behavior (CGEL plugin):**
- `cgel` CLI: `draft | validate | seal | status | verify <check-id> | audit | attest` — logic đóng gói, không tự là trust boundary.
- Hook scripts: contract/scope/governance-paths gate; command guard (fail-closed); evidence recorder (hash chain, diff binding, dirty-marking sau Edit); stop gate.
- Verification registry, contract/evidence/attestation schemas, seal ceremony, failure guard, attestation exporter.
- Skills: `cgel-task` (intake→draft→seal), `cgel-loop` (cognitive workflow guidance), `cgel-attest`.
- Agents: `explorer.md`, `verifier.md`.

**External scripts/services:** Profile B boundary (container / separate OS user / Bash sandbox protected mounts / CI runner / remote service); CI làm attestation sink và re-verification.

**Optional integrations:** MCP interface cho control plane (đánh giá sau Phase 1); PR/issue approval integration (NEXT); remote audit endpoint.

## 15.7 Plugin file structure

```text
cgel-plugin/                          # plugin (cài per machine)
├── .claude-plugin/plugin.json
├── hooks/hooks.json                  # đăng ký 5 hook events
├── scripts/                          # hook impls, stdlib-only, testable subprocess-level
│   ├── contract_gate.py              #   PreToolUse Edit|Write
│   ├── command_guard.py              #   PreToolUse Bash (fail-closed)
│   ├── evidence_recorder.py          #   PostToolUse + PostToolUseFailure
│   └── stop_gate.py                  #   Stop continuation
├── bin/cgel                          # CLI — một decision line trên stdout, lỗi ra stderr
├── agents/{explorer.md, verifier.md}
├── skills/{cgel-task/, cgel-loop/, cgel-attest/}
├── schemas/                          # contract / evidence / attestation JSON Schema
└── tests/                            # subprocess hook tests + e2e demo tasks

project-repo/                         # guidebook per-project (committed, team-owned)
├── .claude/
│   ├── rules/constitution.md         # always-on, cap ~2k tokens
│   ├── skills/<domain-skills>/       # SKILL.md + references/
│   └── settings.json
├── docs/
│   ├── adr/
│   └── standards/                    # semantic rules (RULE IDs) + reference-index.yaml
├── .cgel/                            # gitignored kể từ D-35 (xem bên dưới) — local, không commit
│   ├── registry.yaml                 # verification registry (governance path)
│   └── config.yaml                   # attestation/isolation policy
└── .task/                            # gitignored — mirror debug, KHÔNG phải source of truth

$PLATFORM_STATE_DIR/cgel/<repo-id>/<task-id>/    # CGEL runtime state store (platform path API)
│   # Profile A: tamper-evident only — same-principal, not a hard trust boundary
│   # Profile B: tamper-proof only when protected by an external boundary
├── sealed_task.yaml · state.json · iterations.jsonl · evidence.jsonl (hash-chained)
└── attestation/
```

Mục đích tách ba nơi: plugin = cơ chế (dùng chung mọi project); project repo = tri thức + thước đo (team sở hữu, review như code); state dir = runtime (không commit, integrity theo profile).

**D-35 (sửa đổi sau v1.0 — chủ dự án quyết, ghi nhận nguyên trạng):** `cgel init` gitignore cả `.cgel/` lẫn `.task/`. Lý do: plugin không được thêm file vào lịch sử git của project dùng nó. Đây là **thu hẹp có ý thức** của D-3/§15.7 bên trên — registry thôi không còn là "thước đo team sở hữu, review như code", mà trở thành state cục bộ theo máy.

Cái giá đã được nêu và chấp nhận:

1. Clone mới không có registry → `cgel verify` không có check nào để chạy → không có evidence → PASS không đạt được cho tới khi ai đó đăng ký lại check bằng tay.
2. Registry per-machine, không qua review → mỗi dev (và mỗi agent) tự viết thước đo chấm chính mình. Đây là **suy yếu trực tiếp của nguyên tắc #3** ("bên được đánh giá không giữ thước đo") — vector `echo tests passed` của §15.8 Phase 1 nay chỉ còn permission prompt chặn, không còn code review.
3. Không thể có test khẳng định CI chạy đúng các check trong registry (CI không có registry để so).

Điểm 2 là mâu thuẫn thật với nguyên tắc #3, không phải chi tiết triển khai. Ghi lại ở đây để lần sau đọc còn thấy — nếu muốn khôi phục, bỏ `.cgel/` khỏi `GITIGNORE_ENTRIES` trong `bin/cgel` và commit registry trở lại.

## 15.8 MVP implementation plan (walking skeleton)

**Phase 0 — Contract & Scope Gate.** Goal: không sửa được application code trước seal/ngoài scope. Components: contract schema + `cgel draft/validate/seal` + normalized summary + digest approval + contract_gate + governance protected paths + dirty-tree detection. Tests: subprocess hook tests (JSON stdin → assert exit code/stderr); e2e: một task low-risk auto-seal + một task human-seal. Risks: gate quá phiền → kill-switch có chủ ý, fail-open cho malformed input ở gate tiện dụng, fail-closed ở command guard. Exit: đúng như v0.4 §F, kèm limitation ghi rõ: Profile A chưa chặn Bash-writes.

**Phase 1 — Evidence.** Goal: `echo tests passed` vô giá trị; PASS validator hoạt động. Components: registry + recorder (hai events) + diff binding + bundle binding + hash chain + candidate audit anchor (dual-sink) + `cgel verify/audit`. Tests: giả mạo evidence local → `cgel audit` phát hiện; sửa registry sau seal → BLOCKED. Risks: payload hook khác giả định (V-4) — adapter cô lập. Exit: như v0.4 §F.

**Phase 2 — Loop Control.** Goal: budgets + failure guard thật. Components: iteration records, budget accounting từ store, default-same guard + override schema, BLOCKED semantics, stop gate, resume protocol (SessionStart inject summary). Tests: same-failure lần 2 bị từ chối RETRY; budget cạn → BLOCKED; resume giữ nguyên chain. Exit: như v0.4 §F.

**Phase 3 — Semantic Layer.** Goal: một task thật end-to-end có attestation. Components: Verifier + rule IDs + frozen trigger + findings schema + attestation exporter + optional Explorer + một AI sample skill + eval check. Tests: blocking violation chặn PASS; verifier không có write tool; AI task chạy cùng pipeline. Exit: như v0.4 §F.

**Sau Phase 1:** quyết CLI-only vs thêm MCP interface bằng dữ liệu thật. **Migration path:** mỗi phase tự đứng — team có thể dừng ở Phase 0 (chỉ scope gate) và vẫn nhận giá trị; guidebook viết dần (constitution → 3–5 skills → rules → references), không yêu cầu đầy đủ ngày một.

## 15.9 Failure modes

| Failure mode | Phát hiện | Phản ứng |
|---|---|---|
| Wrong skill selection | `applies_when/does_not_apply_when` lúc resolution; verifier fail rules mà skill bỏ qua | REPLAN với skill khác; lesson → outer loop |
| Conflicting rules | conflict record lúc resolution | không tự chọn; nếu chặn quyết định → ESCALATE; exception qua contract record |
| Stale references | `review_after`/`status` → cờ STALE | không là sole blocking authority; thiếu active replacement → ESCALATE |
| Missing ADR | thay đổi architecture-sensitive không có ADR governing | assumption reversible có ghi log, hoặc ESCALATE nếu irreversible; ADR mới = task `modify-governance` |
| Invalid hypothesis | check fail bác hypothesis | REPLAN; hypothesis `disproved` được giữ lại trong iterations.jsonl |
| Test failure | evidence FAIL + failure_signature | RETRY/REPLAN theo guard default-same |
| Scope expansion | PreToolUse block | ESCALATE + contract amendment → reseal |
| Repeated retry | default-same guard | lần 2 → forced REPLAN; sau REPLAN còn lặp → ESCALATE/ABORT |
| Context overload | ring budgets vỡ, coherence giảm | Explorer cho đọc rộng; BLOCKED + resume bằng compact summary từ store |
| Verifier disagreement | verifier blocking finding vs main agent phản đối | verifier block-only; main agent challenge một lần kèm evidence; còn bất đồng → ESCALATE, không bao giờ tự override |
| Interrupted session | state + chain trong runtime state store | resume: SessionStart inject summary; re-check bundle digest trước khi tiếp tục |
| Uncommitted user changes | dirty-tree detection Phase 0 | intersect scope → escalate/user confirm; worktree qua copy-in/patch-out; rollback không đụng checkout |
| Missing credentials | `failure_kind: permission_denied/environment` | BLOCKED (không RETRY); cần user |
| Unsafe operation request | precedence #1 + command guard fail-closed | deny + ESCALATE tường minh; không silent |

## 15.10 Evaluation metrics

Nguồn đo: attestations + iterations.jsonl + hook logs (mọi thứ đã được ghi sẵn theo thiết kế).

- **Hiệu quả:** first-pass success rate; iterations/task trung bình; retry rate; replan rate; time-to-PASS; token cost/task.
- **An toàn:** scope-violation attempts (hook blocks); evidence-gate rejections (proposePass bị từ chối); governance-bundle-changed incidents; escaped defect rate (regression sau PASS); rollback count.
- **Guidebook:** retrieval precision (references nạp vs được cite trong quyết định); stale-reference incidents; rule-citation rate của verifier; skill fresh-agent test pass rate.
- **Con người:** human escalation rate (đúng loại — escalation "tốt" là loại chặn hành động nguy hiểm); approval latency.
- **Ngưỡng nghiệm thu MVP (đề xuất):** 0 PASS thiếu evidence (theo audit); 0 scope violation lọt gate Edit/Write; guard default-same trigger đúng ≥ 90% trên bộ demo failure; verifier output ≤ cap trong 95% lần chạy.

## 15.11 Final decision log

**Accepted (D-1 … D-34):** D-1..D-30 như decision log v0.4 của ChatGPT (giữ nguyên văn), cộng: `D-31` — capability taxonomy chi tiết (`modify-project-docs/governance/verification-registry/hook-policy/evaluation-baseline`); `D-32` — Profile A audit anchor theo chính sách dual-sink (local append-only log + một exportable/user-visible sink), `additionalContext` chỉ là candidate anchor; `D-33` — `ROLLED_BACK` là persisted terminal status, `ROLLBACK_ITERATION` là iteration decision; `D-34` — mọi cách gọi "trusted store" được thay bằng "CGEL runtime state store" kèm qualifier theo profile (Profile A: local, tamper-evident, same-principal, not a hard trust boundary; Profile B: protected, tamper-proof within the declared isolation boundary) — điều kiện sign-off vòng 6 của ChatGPT.

**Rejected (X-1 … X-12):** như v0.4 (từ load-toàn-bộ-guidebook đến commit-attestation-mặc-định).

**Trade-offs quan trọng đã chấp nhận:** (1) Profile A đổi tamper-proof lấy tiện dụng — bù bằng tamper-evidence + tài liệu trung thực; (2) sealed bundle đổi tính linh hoạt giữa-task lấy integrity của thước đo — sửa guidebook giữa chừng đòi reseal; (3) verifier có điều kiện đổi coverage lấy chi phí — bù bằng deterministic checks luôn bắt buộc; (4) CLI-first đổi API đẹp lấy tốc độ validate — MCP chờ dữ liệu Phase 1.

**Validation backlog (prototype facts, không phải kiến trúc):** `V-1` audit sink portability & user-visibility (Q-10); `V-2` copy-in/patch-out với rename/binary/submodule (Q-11); `V-3` failure normalization trên pytest/Jest/Cargo (Q-12); `V-4` Stop bound + payload PostToolUse/PostToolUseFailure; `V-5` apply-back 3-way conflicts.

**Deferred questions:** MCP interface (sau Phase 1); lựa chọn boundary Profile B theo môi trường triển khai; rule YAML governance (LATER, theo tiêu chí D-12).

---

## Trạng thái chung cuộc

ChatGPT đã final sign-off ở vòng 6 với đúng một điều kiện: thay mọi cách gọi "trusted store" bằng "CGEL runtime state store" kèm qualifier theo profile. Tôi xác nhận chỉnh sửa này nhất quán với trust model đã thống nhất (D-13, D-17, D-26, X-8 — vị trí file không tạo trust boundary; chỉ boundary ngoài agent principal mới nâng assurance lên tamper-proof), đã áp dụng vào toàn bộ tài liệu, và ghi nhận thành D-34.

Cuộc tranh luận khép lại. **Contract-Gated Evidence Loop — CGEL v1.0** là kiến trúc chung cuộc được cả hai bên phê duyệt. Sau chỉnh sửa D-34, tài liệu không còn assurance claim nào vượt quá boundary thực tế của deployment profile tương ứng.
