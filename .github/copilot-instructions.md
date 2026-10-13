## Copilot cloud-agent reliability notes

- Do not call `view` on generated image files (`.png`, `.jpg`, `.jpeg`, `.webp`) from `/tmp`.
- For visual/debug analysis, extract numeric or structured results with scripts and inspect only text outputs (`.json`, `.txt`, `.md`).
- If intermediate files are needed across multiple turns, keep them under the repository workspace (for example `./tmp/`) instead of `/tmp`.

## Project documentation guardrails

- Integration branch: `copilot/dev`
- Inspect real code before editing documentation
- One PR = one objective
- Never merge automatically
- Canonical roadmap: `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md`
- Historical reports are evidence snapshots, not current truth
- `None != 0`
- Never fabricate missing metrics
- No fake sleep / HRV / TSS / pace values
- Training is the prescription authority
- Garmin activity is the performed-observation authority
- Deterministic science must remain deterministic
- Every PR report must state exact base, head, and tests
