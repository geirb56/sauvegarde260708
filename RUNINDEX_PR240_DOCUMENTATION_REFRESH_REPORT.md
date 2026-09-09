# RUNINDEX — PR #240 — Documentation Canonical Refresh

- Repository: `geirb56/sauvegarde260708`
- Integration target: `copilot/dev`
- Audited source HEAD: `5b694ea669e5812e90fed138e350dd98712e5404`
- Scope: documentation only

## Objective

Refresh the living documentation so it matches the current verified repository state without modifying business code.

## Files changed

- `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md`
- `README.md`
- `DEPLOYMENT.md`
- `.github/copilot-instructions.md`
- `memory/PRD.md`
- `PRODUCTION_READINESS_REPORT.md`
- `RUNINDEX_PR239_REPORT.md` (renamed from `RUNINDEX_PR238_REPORT.md`)
- `RUNINDEX_PR236_REPORT.md`
- `RUNINDEX_PR240_DOCUMENTATION_REFRESH_REPORT.md`

## Canonical refresh summary

### Master roadmap
- switched the canonical branch/reference from old `main` assumptions to `copilot/dev`
- updated verified HEAD and merged PR sequence
- separated RunIndex, Readiness, and Training authorities
- refreshed training load, performance curve, training paces, Garmin, workers, and subscription contracts
- added current runtime gate, roadmap, and future product vision sections

### README
- removed obsolete “AI score / mono-compte GCCLI” wording
- documented the current deterministic product split and current runtime architecture
- pointed readers to canonical docs instead of stale historical snapshots

### Deployment
- replaced the old release/staging narrative with the current runtime shape
- documented backend/frontend, Mongo, Redis, workers, GCCLI per-user sessions, and Paddle
- kept the final Beta gate explicit instead of claiming full production readiness

### Historical-document handling
- marked `memory/PRD.md` and `PRODUCTION_READINESS_REPORT.md` as historical/superseded
- corrected the nonexistent PR #238 report into the real PR #239 report
- preserved historical evidence files instead of rewriting the whole archive

## Validation performed

- repository fact audit against current code and GitHub PR state
- documentation secret scan on targeted markdown files: no secrets detected
- `git diff --check`

## Constraints respected

- no business-code changes
- no changes under `backend/frontend/workers/science` implementation files
- no merge performed
- no direct push to `copilot/dev`
