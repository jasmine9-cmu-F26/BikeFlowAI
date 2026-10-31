# Final app32 trip / OD audit

**PASS: same fixed 32 stations; training-only estimates, explicit fallback denominators.** No original 42-station number is reused as an app32 result.

| Check | Count / rate |
|---|---:|
| Raw monthly CSV rows streamed | 2,887,990 |
| Trips naming both app32 endpoints, departure inside window | 38,413 |
| Both endpoints historically mapped | 36,007 |
| Mapping rate over named-app32 denominator | 93.7365% |
| Training-only eligible rides (both times in train, 60s..6h) | 18,571 |
| Observed training OD pairs | 806 |
| OD pairs with >=20 training rides | 229 |
| All ordered app32 pairs, including self pairs | 1024 |
| Fallback over all possible ordered pairs | 77.6367% |
| Fallback over observed training pairs | 71.5881% |
| Fallback weighted by all mapped requests | 19.3823% |

[planner_od.csv](planner_od.csv) covers all 1,024 ordered station pairs. Supported pairs use the training median. Others use the proposal's 1.3 × haversine distance / 4 m/s rule. Self pairs are explicitly flagged: geometric zero distance is not a calibrated round-trip duration. For live serving recompute fallback geometry from current GBFS coordinates; do not use old historical coordinates as current location evidence.

[fallback_by_request_split.csv](fallback_by_request_split.csv) separates split-specific request weighting and duration-valid denominators. Test request weighting is a descriptive coverage diagnostic, never a fit input or a reason to alter the final support threshold.

The final planner OD table is for tune/calibration/test after the training cutoff. **Do not attach it to earlier training replay requests.** External `OD/training_expanding_week_od.parquet` supplies ten past-complete-week training versions; first training week uses geometric fallback only. Unsupported training geometry is deliberately null and must be computed from metadata as-of the request, avoiding future training-coordinate summaries. [OD_training_week_fit_manifest.csv](OD_training_week_fit_manifest.csv) records each cutoff and source bound.

Historical names, <=50m geometry and observed identity intervals map trips; unmapped names/coordinates are excluded. Trips outside the 32-site named scope are not mapping failures. Completed rides omit unmet demand. Raw trip/request rows remain external. Recorded snapshot time is an availability assumption, and nearest ±5-minute outcomes are quantized support, not exact pre-checkout inventory.
