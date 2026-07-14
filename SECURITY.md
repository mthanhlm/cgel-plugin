# Security

## What this plugin is, in trust terms

CGEL gates edits behind a sealed contract and records hash-chained evidence
for verification runs. It is worth being blunt about what that does and does
not buy you, because a governance tool that overstates its own enforcement is
worse than no governance tool — it moves risk from "visible" to "assumed
handled".

**Profile A — the only profile this plugin currently ships — is
tamper-evident, same-principal, and not a hard trust boundary.**

The hooks, the `cgel` CLI and the state store all run as the same OS user as
the agent's Bash tool. Anything Bash can write, Bash can rewrite: the state
store, `evidence.jsonl`, the registry. The hash chain and `cgel audit` mean
tampering *leaves marks*; they do not mean tampering is *prevented*. If you
need prevention rather than detection, you need Profile B — the control plane
behind a boundary the agent principal cannot write (container, separate OS
user, sandboxed filesystem, CI runner). Profile B is not implemented yet.

The corollary matters: **CGEL is built to catch mistakes, drift and
convenient shortcuts, not a determined adversary with local shell access.**
Every assurance claim in the README carries its enforcement class
(`HARD_ENFORCED` / `EVIDENCE_GATED` / `HUMAN_GATED` / `GUIDANCE_ONLY`) and a
`tamper-evident | tamper-proof` qualifier for exactly this reason. The
README's "Explicit limitations (Profile A honesty)" section is the
authoritative list; read it before relying on any gate here.

## In scope

Report these:

- A path that lets the model reach a **human gate without the human** — in
  particular sealing a contract that carries a protected capability, or
  `cgel unblock`, without a permission prompt firing.
- **Evidence accepted for work it does not describe**: a `PASS` where a
  criterion's evidence is stale, belongs to another contract/bundle/workspace
  digest, or was never produced by a registered check.
- **The scope gate letting an Edit/Write through** for a path outside
  `scope.allowed`, or a governance path being written without the matching
  protected capability.
- `cgel audit` reporting `chain=intact` over a chain that is not.
- A hook script that can be made to execute attacker-controlled input from
  the analyzed repository.

## Out of scope

These are known and documented, not vulnerabilities:

- **Anything achievable with Bash on the host.** Rewriting the store,
  bypassing the gate with `sed`/`python`/`cp`, re-chaining evidence. This is
  the documented Profile A boundary, not a bug. Profile B is the answer.
- **Evading the command guard by indirection.** It is a regex guardrail
  against mistakes, stated as such.
- **A model ignoring instructions in a skill or agent prompt.** Prompts are
  `GUIDANCE_ONLY` by construction. Only hooks, permissions and the CLI
  validator enforce anything.
- **A vacuous registered check** (`echo tests passed`). The registry is the
  measure and is trusted by design; it is guarded by the `cgel check add`
  permission prompt and, where the registry is committed, by code review.

## Reporting

Use GitHub's private vulnerability reporting on this repository. If that is
unavailable, open an issue titled `security: brief description` **without**
exploit details, and you will be sent a private channel.

Please include what you did, what you expected the gate to do, and what it
did instead. A minimal reproduction beats a full exploit.

Expect an acknowledgement within a few days, and a fix or a documented
limitation within ~30 days. "We will document this as a Profile A limitation"
is a legitimate outcome, and you will be credited either way if you want to
be.
