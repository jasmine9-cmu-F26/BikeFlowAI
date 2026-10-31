# Weather audit validation

**40 Python tests passed**, including six offline weather tests for missing timestamp denominators, null/NaN/Inf handling, duplicate/unaligned hour rejection, backward-only bounded calendar joins and strict issuance/publication gating. No tests use live APIs.

All 20 bounded weather responses and seven source/terms documents were checked against saved compressed and uncompressed SHA-256/lengths; all requests returned HTTP 200. Each local model Parquet has 2,904 context-inclusive hourly rows, with 2,856 study hours. All report table counts, core/diagnostic missingness, live/historical schema units and source/code/protocol hashes agree. Raw/processed outputs remain external.

The frozen historical protocol, station cohort, splits, Google collector code and local collector code remain unchanged. No model or feature table was trained/certified. Calendar matching was measured, while historical issue/publication availability remains unverified.

The Word review copy has references [1]–[11], updated in-text PPO/calibration citations, and audit-qualified weather wording. It preserves every ZIP part except document.xml and retains the original equation count; the source document is unmodified. No Word/PDF visual rendering check was performed. Relative documentation links resolve. See [validation_results.json](validation_results.json).

The previous cloud migration was committed as dcb7b16 before this weather work. New weather results remain uncommitted for review; hosted CI has not run for them.
