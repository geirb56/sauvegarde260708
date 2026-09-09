# RUNINDEX — PR #240 — Documentation Canonical Refresh

- Repository: `geirb56/sauvegarde260708`
- Integration target: `copilot/dev`
- Base SHA: `5b694ea669e5812e90fed138e350dd98712e5404`
- Head before C240 correction: `d2716923fb901af0429b01c9a7c1f2ab1f5dc1ef`
- Final PR head: `TO_FILL_AFTER_C240_CORRECTION_COMMIT`
- Scope: documentation only

## Objective

Refresh the living documentation so it matches the current verified repository state without modifying business code.

## Files changed

- `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md`
- `README.md`
- `DEPLOYMENT.md`
- `.github/copilot-instructions.md`
- `memory/PRD.md`
- `memory/test_credentials.md` (working-tree exposure removed from this branch)
- `PRODUCTION_READINESS_REPORT.md`
- `RUNINDEX_PR239_REPORT.md` (renamed from `RUNINDEX_PR238_REPORT.md`)
- `RUNINDEX_PR236_REPORT.md`
- `RUNINDEX_PR240_DOCUMENTATION_REFRESH_REPORT.md`

## Canonical refresh summary

### Master roadmap
- switched the canonical branch/reference from old `main` assumptions to `copilot/dev`
- updated verified HEAD and merged PR sequence
- separated RunIndex, Readiness, and Training authorities
- corrected the Performance Curve documentation so 90-day qualification benchmark logic is distinguished from the current 730-day contributor pool
- documented the current product/code divergence on personal-k slope-evidence learning window without changing runtime code
- added current runtime gate, roadmap, and future product vision sections

### README
- removed obsolete “AI score / mono-compte GCCLI” wording
- corrected local setup so Docker Compose is documented as backend/infra only
- documented that the frontend runs separately with `npm start` in another terminal
- clarified Docker Compose vs Railway worker topology
- pointed readers to canonical docs instead of stale historical snapshots

### Deployment
- replaced the old release/staging narrative with the current runtime shape
- documented backend/frontend, Mongo, Redis, workers, GCCLI per-user sessions, and Paddle
- kept the final Beta gate explicit instead of claiming full production readiness

### Historical-document handling
- marked `memory/PRD.md` and `PRODUCTION_READINESS_REPORT.md` as historical/superseded
- corrected the nonexistent PR #238 report into the real PR #239 report
- preserved historical evidence files instead of rewriting the whole archive

## P0 SECURITY — VERSIONED SECRET FOUND

path:
`memory/test_credentials.md`

types:
- test account credential
- JWT secret

values:
REDACTED

Assessment:
- the file contains an email pattern, password labeling, `JWT_SECRET_KEY`, and a user UUID
- no obvious placeholder markers were found
- it must be treated as potentially real historical credential material
- no external authentication attempt was made
- no JWT generation or validation was attempted

Working-tree action in this PR:
- working-tree exposure removed from this branch
- historical exposure remains in Git history and is not resolved by this PR alone

SECURITY FOLLOW-UP REQUIRED:
- rotate/revoke affected test account credential
- rotate JWT secret if still/currently used or if provenance cannot prove it obsolete
- assess Git history purge
- verify no other versioned secret copies exist

## Validation performed

Tests / checks for this documentation correction:
- repository fact audit against current code and GitHub PR state
- redacted metadata audit of `memory/test_credentials.md`
- `git diff --check`
- targeted secret scanning on changed documentation files

## Constraints respected

- no business-code changes
- no changes under `backend/frontend/workers/science` implementation files
- no merge performed
- no direct push to `copilot/dev`
