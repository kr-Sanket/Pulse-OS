# PulseOS — Project Rules

> **Document:** `project-management/10_PROJECT_RULES.md`
> **Status:** Active — the non-negotiable engineering rules of PulseOS
> **Related:** the full project-management set (02–09) · [`docs/CONTRIBUTING.md`](../docs/CONTRIBUTING.md) · [`docs/SECURITY.md`](../docs/SECURITY.md) · [`.claude/DECISIONS.md`](../.claude/DECISIONS.md)

This is the handbook. Documents 02–09 explain *how* we work; this one states *what is never up for debate*. Every rule below has already earned its place — either by preventing a failure mode we've seen, or by protecting an invariant the project's security claims and research contributions depend on. When a rule and your convenience conflict, the rule wins. When a rule and reality conflict, escalate to the Lead — don't improvise.

---

## 1. Ownership Rules

- Every artifact has **exactly one owner** (`02_TEAM_RESPONSIBILITIES.md` §4). Unlisted areas default to the Lead.
- You write code only inside your owned directories. Needing a change elsewhere is a request to its owner, never a self-service edit.
- One feature = one owner, end to end. Features are never co-implemented across ownership lines.
- Ownership transfers only by the Lead's explicit, written reassignment — never by momentum, absence, or helpfulness.

## 2. Branch Rules

- All work happens on short-lived branches cut from **current** `main` (03 §7). Pulling before branching is part of branching.
- `main` is protected: no direct commits, no force pushes, no development on it — PRs are the only entrance (03 §3).
- One feature per branch; branches are deleted at merge; a branch older than a week is a problem, not a project.
- Rebase to sync with `main`; `--force-with-lease` only on your own feature branch, never on shared history.

## 3. Architecture Rules

- The architecture is **decided**: modular monolith, six modules, Clean Architecture per module (router → service → repository), providers behind ports (ADR-001…). You build *within* it.
- Architecture changes travel one road: written proposal → Lead decision → ADR → implementation. Code that arrives with its own architecture is rejected regardless of quality.
- ADRs are append-only: added or superseded by the Lead, never edited, never deleted.
- Module isolation is absolute: no module touches another module's tables; cross-module needs go through service interfaces.
- No speculative abstraction. The boring solution is the house solution; the only sanctioned indirections are the existing provider ports (auth, storage, queue, LLM, chain).
- Phase gates are strict: no next-milestone code before the current gate passes — no "hooks for later."

## 4. Database Rules

- Every schema change is a **Lead-authored, reversible Alembic migration** on a single linear head. No exceptions for "tiny" columns.
- The database is never mutated by hand — not in dev, not in demos, not "just to test."
- UUID primary keys; business identifiers (`PHI-…`, `HID-…`) are unique display keys, never FK targets.
- Append-only tables (audit events, consent decisions) get no UPDATE or DELETE paths — state changes are new rows.
- Naming conventions (`op.f`, the metadata convention in `core/db.py`) apply to every constraint and index.

## 5. Security Rules

- **Consent is the choke point.** No record content is readable without passing the single enforcement layer. It is never bypassed — not for demos, not for debugging, not temporarily.
- Deny-by-default, three ordered layers (ADR-013): role gate → relationship → consent. Roles come from verified claims, never from request payloads.
- SYSTEM_ADMIN never reads medical content. There is no admin break-glass. This is an invariant, not a configuration.
- 404-not-403 wherever existence itself is sensitive.
- No PHI in logs, error reports, or external calls; nothing reaches an external LLM unredacted (ADR-007).
- Files move only via short-lived presigned URLs issued after authorization (ADR-005).
- Secrets live in env vars only; `.env.example` documents them with placeholders. Real patient data never enters this system — synthetic only, clearly marked.

## 6. Documentation Rules

- Behavior or architecture changes ship with their doc updates in the same PR — the doc map in `.claude/CLAUDE.md` says which file.
- Non-obvious decisions become ADRs. If you had to think hard about a choice, the next person shouldn't have to reverse-engineer it.
- `SESSION.md` and `TODO.md` are updated at the end of every working session — the project's memory is written, not oral.
- Comments explain *why* (constraints, domain rules), never *what*. Dead code is deleted, not commented out.
- Docs PRs meet the same review bar as code PRs.

## 7. Code Review Rules

- Every PR is reviewed by the Lead before merge — including the Lead's own, which are opened as PRs and held to the same checklist (07).
- Review order is fixed: scope/isolation violations block first; style is judged last.
- Approval applies to the latest push only; new pushes require re-review.
- Review threads are resolved only by pushed changes or explicit reviewer agreement — never to tidy the PR.
- Findings cite a rule, ADR, or failure scenario. Authors respond with facts, once; the Lead's decision is final.

## 8. Generated Code Rules

- `openapi.json` and `web/packages/api-client/src/generated/` are **machine-owned**: changed only by `make api-client`, in the same PR as the endpoint change that motivated them.
- An unintended spec diff means the PR is wrong — the contract is reviewed line by line.
- Frontend code consumes the generated client exclusively. A direct `fetch()` is a review-blocking defect.
- Nobody hand-edits generated files. Ever. Hand edits mask drift and evaporate at the next generation.

## 9. Testing Rules

- Features ship with their tests; bugfixes ship with the regression test that fails without the fix.
- **Every authorization surface has negative tests** — wrong role, wrong owner, unauthenticated. Happy-path-only suites do not prove deny-by-default.
- External services are faked in tests; CI makes no live calls.
- Coverage floors hold (≥80% on `records`/`consent`); tests are deterministic; the full local gate (`make ci`) is green before every push.
- Test code is production code: typed, reviewed, maintained.

## 10. AI Usage Rules

All PulseOS code is AI-assisted by design. That changes nothing about accountability:

- **The committer owns every line.** You must understand it, be able to explain it, and have run it. "The AI wrote it" is never a review answer (CONTRIBUTING rule 4).
- AI-generated code meets the identical bar: typed, tested, scoped, ADR-compliant. There is no AI discount at review.
- AI tools operate within your ownership only. Prompting an AI to build another member's scope — or the backend from a frontend seat — is the same violation as typing it yourself; this exact failure has already cost the project a discarded implementation.
- Claude serves as the project's Senior Engineer: architectural reviews, milestone implementation under the Lead's direction, and session records. Its output enters `main` through the same PR pipeline as everyone else's.
- Never paste secrets, credentials, or real personal data into any AI tool. Synthetic data only — the same rule as the codebase itself.
- AI suggestions that conflict with an ADR are wrong by definition. The ADR wins until the Lead supersedes it.

## 11. Team Communication Rules

- **Blocked means talking.** If you're blocked longer than 30 minutes, say so — to the owner of the blocking area, or to the Lead. Silent stalls cost days; questions cost minutes.
- Scope questions are asked **before** coding (SOP §3), and answers are recorded in the task's Notes — decisions live in writing, not in chat scrollback.
- Escalations (02 §6) — new tables, API changes, dependencies, shared components — happen *before* the work, not as a PR surprise.
- Bad news travels fastest: broken `main`, a security concern, a slipped estimate — report immediately, no framing required.
- Disagree openly, once, with reasons, in the PR or task thread. Then commit to the decision. Relitigating settled ADRs in every review is noise.
- Every merge that affects others (API change, shared types) is announced so open branches rebase promptly.

## 12. Prohibited Actions

The blacklist. These are never acceptable, and none of them has a "just this once":

- **Never commit directly to `main`.**
- **Never bypass review** — no self-merges, no "trivial change" exemptions.
- **Never change ADRs without approval** — they are Lead-owned and append-only.
- **Never modify another member's ownership without approval** — not their portal, not the backend, not shared packages.
- **Never manually edit generated code** (`openapi.json`, `api-client/src/generated/`).
- **Never implement outside assigned scope** — including "helpful" extras and future-milestone hooks.
- **Never commit secrets** — keys, service accounts, tokens, real credentials of any kind.
- **Never disable, skip, or delete tests to pass CI** — a red gate is information, not an obstacle.
- **Never force-push shared history** — `main` or any branch with more than one consumer.
- **Never bypass consent enforcement or authorization layers** — not for the demo, not for debugging.
- **Never put PHI in logs, error trackers, or external AI/LLM calls.**
- **Never mutate the database by hand** — migrations are the only schema path.
- **Never merge failing code** — red CI stops everything downstream, no negotiation.
- **Never start from a stale base** — pull `main` before every branch, every session.

Violations aren't punished with process theater — they're simply undone: the PR is closed, the work is redone properly, and the time is lost. The rules are cheaper.

## 13. Guiding Principles

When no rule covers the situation, these decide:

- **Keep it simple.** The boring solution that obviously works beats the clever one that probably works. Complexity must buy something specific.
- **One owner per feature.** Shared responsibility is deferred blame. Every question has exactly one right person to ask.
- **Small PRs.** Small changes get real reviews, cheap rollbacks, and fast merges. Big changes get skimmed, feared, and reverted whole.
- **Document important decisions.** If it took a discussion, it deserves an ADR or a Notes entry. The project's memory must survive any single person's.
- **Protect the architecture.** The design is the asset — the paper's claims, the security story, and the timeline all rest on it staying coherent. Guard it like the data.
- **Quality over speed.** A demo that works twice in a row beats a feature list that works once. Slow is smooth; smooth is fast — and the milestone gates only accept smooth.
- **`main` is the team's promise to itself.** Everything else in this handbook exists to keep that promise cheap to keep.

---

*Maintained by the Lead Developer. Rules are added when reality teaches us something; they are removed almost never.*
