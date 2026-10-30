# Initial archive audit: interpretation and provenance

This directory contains the **initial 2026-10-30 audit of the original seven-minute sampling assumption**. The original reports, CSVs, and recorded hashes are preserved.

- The full archive contains 40,960 unique feed timestamps from 2022-08-07 through 2023-07-19.
- Coverage of the original fixed seven-minute grid is 57.56%; the original 90% gate returned `FALLBACK`.
- The revised Milestone 2 proposal accepts irregular sampling, treats weather as optional, and permits provisional station, mapping, and split manifests while the revised rule is validated.
- Consequently, `FALLBACK` in `data_audit.md` and `audit_summary.json` describes the **original gate**. It is not a completed assessment of the revised design, nor proof that the archive is unusable for modeling.

The initial label-retention and class-balance values are diagnostics. They do not certify training readiness: the current code uses the original horizon/tolerance settings, matches the nearest observation before checking validity, and reports freshness separately. The revised builder must implement the approved nearest-valid, freshness, causal-feature, and split-boundary rules.

The data owner's next deliverables are described in [docs/data_handoff.md](../../docs/data_handoff.md). Record sampling-rule comparisons in a separate report directory such as `reports/sampling_revision/`; do not rewrite the old results merely to make them say PASS.

`validation.md` records checks performed during the original extraction/audit run. Its statements about commits or local raw-file locations refer to that run in the source archive checkout. The current project lifecycle and test instructions are in the [project README](../../README.md).

Running the current audit script with its default paths replaces the reports and manifests. Use separate `--reports` and `--manifests` output locations for repeat experiments, and keep the source revision, code hash, rule configuration, and execution environment with each result.
