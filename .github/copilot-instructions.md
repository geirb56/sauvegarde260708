## Copilot cloud-agent reliability notes

- Do not call `view` on generated image files (`.png`, `.jpg`, `.jpeg`, `.webp`) from `/tmp`.
- For visual/debug analysis, extract numeric or structured results with scripts and inspect only text outputs (`.json`, `.txt`, `.md`).
- If intermediate files are needed across multiple turns, keep them under the repository workspace (for example `./tmp/`) instead of `/tmp`.
