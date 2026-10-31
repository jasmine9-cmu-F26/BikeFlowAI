# Data handoff: revised sampling design

Status: **initial archive audit complete; revised training dataset not yet validated or frozen**.

The revised Milestone 2 proposal explicitly permits provisional manifests at the initial audit milestone. The checklist below covers the next stage required by baseline, forecasting, and replay development. It is a plan, not a claim that these files or analyses already exist.

## 1. Compare and approve temporal rules

- Declare candidate forecast horizons, matching tolerances, look-back windows, and freshness limits before comparing them. Use training-period evidence to select data rules; reserve the held-out test period for final evaluation.
- Compare retained labels, exclusions, absolute matching error (median/p90/max), temporal coverage, and bike/dock failure event counts by station and horizon.
- Report calendar-grid coverage and actual-snapshot label retention separately. Coarser slots do not recover observations that were never collected; a wider tolerance trades temporal precision for retention.
- Define whether request times are observed timestamps or another predeclared grid. Features must use information available at or before each request time.
- Record the chosen rules, thresholds, rationale, and reviewer in a versioned configuration before freezing the training tables. Do not silently reuse the old 90% gate for a different sampling design.

## 2. Specify valid observations and labels

- Define required counts, installed/renting/returning flags, metadata identity, and maximum feed/station-report age. Document whether a known closure is a negative arrival outcome or an exclusion.
- Search for the **nearest valid snapshot within tolerance**, with a deterministic tie rule. Missing, invalid, and non-reporting observations must remain excluded rather than becoming empty/full events.
- The current initial-audit function chooses the nearest observation first and then checks validity. It must not be reused unchanged as the revised nearest-valid training-label builder.
- For each retained label, save the target time, matched observation time, matching error, validity decision, and source provenance. Keep future label fields separate from request-time features.
- Validate requests and matched targets within their assigned split. Recheck the existing 60-minute purge against the chosen horizons and look-back windows; add explicit boundary tests.

## 3. Reconcile trip and station identities

- Build a time-versioned trip-ID-to-archive-ID mapping from historical station metadata, including short names and external/legacy identifiers where supported by evidence.
- Check ambiguous matches, reused IDs, relocations, capacity changes, and missing metadata. Exclude unresolved cases explicitly.
- Validate the trip timestamp convention, convert Pacific local times to UTC, and handle DST ambiguous/nonexistent times with a documented policy. Do not use a fixed UTC offset or silently guess a fold.
- Count trips with both endpoints mapped and usable station observations at relevant times. File-date overlap alone does not establish replay eligibility.
- Estimate OD ride times from training trips only. Record station pairs with at least the proposal's 20-trip support and the documented fallback for the rest.

## 4. Build and freeze the handoff

- Select the proposal's 20–50 stations using training evidence under the approved revised rule. Keep candidate and approved selections distinguishable.
- Create causal temporal and inventory-change features. Metadata and historical observations used as features must have been available at request time; do not use a later metadata snapshot as an earlier feature.
- Keep weather optional. Add it only after checking historical availability and request-time forecast visibility.
- Freeze station selection, time-versioned mapping, rule configuration, chronological split manifest, and held-out request selection before model tuning.
- Keep feature/label tables in ignored `data/processed/`. Include a schema, row counts, data/code hashes, exclusions, and a reproducible command in the handoff report.

Suggested schema information to document (draft, not an implemented file): request timestamp, station ID and metadata version, request-time features and source timestamps, horizon, target timestamp, matched label timestamp, bike/dock targets, matching error, validity/freshness indicators, split, and source commit/blob provenance.

## Handoff acceptance

| Deliverable | Data owner provides | Receiving owner verifies |
|---|---|---|
| Revised rule comparison | Candidate settings, training-period evidence, chosen rule and rationale | Baseline/forecast/replay owners use the same horizon and validity semantics |
| Mapping and splits | Versioned identities, DST policy, exclusions, frozen split boundaries | No unresolved ID guesses, future-feature leakage, or labels crossing splits |
| Feature/label tables | Local output paths, schema, hashes, per-split/horizon counts and class balance | Sufficient observed samples and failure events for the planned training/calibration/evaluation |
| Replay requests and ride times | Mapped endpoints, timestamps, training-only OD estimates and fallbacks | Requests are reproducible; completed-trip sampling limitations are reported |

Team members should assign the data, forecast, replay, and review roles together. The initial audit alone does not establish model quality, calibration quality, or RL value.
