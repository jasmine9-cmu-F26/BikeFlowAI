# Final pipeline validation

**49 Python tests and 10 Node service-mock tests passed.** Meaningful regressions include future-observation perturbation, actual-table injected future-base rejection, past-only B2 and within-training OD fitting, manual-vs-scheduled health counting, failed-vs-missing slots, raw cloud export hashes and schedule jitter.

All 260 generated Parquet parts were hashed and row-counted outside Git. A separate SQL oracle matched feature base values and lag deltas back to the actual raw snapshots, recomputed all training-week OD counts/medians from prior eligible requests, and recomputed B2 cell/station fallback rates from only earlier training snapshots. All oracle and lineage violations were zero. Stable request IDs are unique; the original app32 protocol/cohort and original audit numerical outputs remain unchanged.

The first feature-producing source bytes are preserved externally under provenance/feature_build_source.py; later stricter post-build audit source hashes are recorded separately. Features/labels were not rewritten during post-build validation. Model feature allowlist and target separation are explicit; no models, OOF/policy probability table or full replay were created.

Cloud v2 health is confirmed from the user-supplied collectorHealth output for 03:01:27.486–03:07:09.208 UTC on October 31: 2/2 successful scheduled slots, zero failures/missing slots, and no stale-feed polls. This short observed window is not independently checked against cloud raw exports and does not certify full-day or weeks-long uptime. Retired local raw capture integrity/window metrics were audited. No local task was re-enabled or paid resource created.

Source files, generated artifact hashes, row totals and limitations are in [validation_results.json](validation_results.json). Hosted CI has not run remotely; all 49 Python and 10 Node tests were rerun successfully before the grouped local commits. Weather audit was committed first as 6964cf5.
