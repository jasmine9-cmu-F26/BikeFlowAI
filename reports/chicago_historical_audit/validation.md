# Validation scope

The primary audit is bounded to 50 training-anchor stations in a fixed 17-week 2021 window. Source chunks and matching four trip ZIPs are hashed and stored outside Git. Full trip CSVs are streamed, not unpacked.

The same fixed protocol was also applied to the retained failed 2022 sample. No numerical CityBikes/Bay Wheels results were rewritten. New tests cover exact long IDs, retaining unchanged snapshots, the full grid denominator, broad historical status, current-name/geometry ambiguity, trip observation gaps, and collector success/error/locking behavior.

The City-required disclaimer is retained, source license metadata says See Terms of Use, and temporal assumptions/matching errors remain explicit. A passing small audit does not certify exact continuous-time state, finalized features, trained/calibrated predictions, full replay behavior or 2026 generalization. Local test and artifact verification results are recorded after the checks complete; hosted CI requires commit/push.

## Completed local checks

- **21 offline tests passed**, including streamed trip OD exclusion of held-out and geographically invalid rides. `pip check`: no broken requirements.
- Both bounded samples: every manifest-listed snapshot chunk and trip ZIP verified by SHA-256; snapshot row counts, Parquet row counts, source/downloader provenance and exported manifest contents agree.
- Report cardinalities, selected-station training coverage, label counts/tolerance, 2021 training-only OD output, Python syntax, relative documentation links and absence of raw/processed data in the checkout were verified.
- The scheduled full-GBFS collector was queried read-only: last result 0, two-minute repetition, configured end boundary confirmed. Recent successful polls were present; the computer still needs to remain logged in, awake and online.
- Detailed machine-readable results are in [validation_results.json](validation_results.json). Hosted CI has not run for these local changes. No commit or push was performed.
