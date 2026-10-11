# Contributing

## Ground Rules

1. `main` is always demoable. Squash-merge only, via PR, CI green. No direct pushes to `main`.
2. One logical change per PR. Big features land as a sequence of small PRs behind the milestone.
3. Every PR passes `.claude/CHECKLIST.md` (DoD + PR checklist; security checklist when applicable).
4. AI-generated code (Claude/Cursor/Copilot) is held to the same standard — the committer owns
   it, must understand it, and must have run it. "The AI wrote it" is never a review answer.
5. Phase gates (`.claude/ROADMAP.md`) are strict: no next-phase code before the gate passes.

## Branch & Commit Conventions

- Branches: `feat/<module>-<slug>` · `fix/…` · `docs/…` · `chore/…` · `refactor/…`
- Conventional Commits: `feat(consent): add per-category revocation`,
  `fix(records): reject uploads over size limit`. Scope = module or package name.

## Code Style

**Python (backend):** ruff (format + lint), mypy strict; full type hints; Pydantic models at
boundaries; domain exceptions, not HTTPException, inside services; no business logic in routers;
docstrings on public services explaining domain intent, not mechanics.

**TypeScript (web):** eslint + prettier, `strict: true`, no `any` (justify exceptions inline);
components in `packages/ui` when used by ≥2 apps; API access only through the generated
`api-client` (never hand-written fetch calls); zod at runtime boundaries the client owns.

**Solidity (contracts, when authorized):** no contract exists yet and the toolchain (Hardhat or
Foundry) is undecided. When built: minimal surface, NatSpec comments, a test for every function,
the pinned commitment vectors reproduced byte for byte, no business logic beyond anchoring
(BLOCKCHAIN_ARCHITECTURE.md, ADR-027).

**General:** comments explain *why* (constraints, domain rules), not *what*; match surrounding
style; delete dead code instead of commenting it out.

## Review Expectations

Reviewer checks, in order: (1) does it violate a module-isolation or consent-enforcement rule
(SYSTEM_ARCHITECTURE.md) — instant block; (2) are the negative-authz tests present; (3) is the
change the simplest thing that works; (4) style nits last. Review turnaround target: 24h.

## Documentation Duties

Behavior/architecture changes update the matching doc (map in `.claude/CLAUDE.md`). Non-obvious
decisions → ADR in `.claude/DECISIONS.md`. End of every working session → update
`.claude/SESSION.md` and `.claude/TODO.md`. Docs PRs are real PRs — same review bar.
