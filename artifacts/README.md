# Versioned M3 application bundle

`m3-demo-v2.zip` is a small serving subset of the team's supplied `bikeflow_m3_artifacts.zip`. It is intentionally tracked in Git so another team member can clone the repository and run **real Replay forecasts** without a separate private download or machine-specific path.

It contains 72 files, approximately 5.9 MB compressed:

- LightGBM bike/dock boosters and their manifest, embedded sigmoid calibrators, feature order and checksums.
- The training-only held-out B2 rate table.
- Causal feature files and separate outcome-label files for **32 stations in the tune split only**, July 12–25, 2021.
- The preference-conditioned PPO policy (`models/rl_conditioned/`, seed 2, chosen by mean tune reward; serves 5/10/15-minute walking limits) and the original fixed 10-minute PPO (`models/rl_dev/`). The app prefers the conditioned policy. See [reports/rl_eval/conditioned](../reports/rl_eval/conditioned/README.md).

**v2 (2026-11-18)** = v1 (`m3-demo.zip`, sha256 `ce5c81da…`, still in Git history) plus the conditioned policy. Rebuilt with:

```bash
python scripts/package_demo_artifacts.py --source <v1 m3-demo.zip> \
  --conditioned-policy $DATA_ROOT/models/rl_conditioned/seed2/ppo.zip \
  --version m3-demo-v2 --output artifacts/m3-demo-v2.zip
```

No raw trips, GBFS capture archive, forward-training predictions, calibration block or final-test block is included. The full team package remains separate. The schema, station registry, training-only OD table and source notices are already tracked elsewhere in the repository.

On first API startup, `backend/artifacts.py` verifies SHA-256 against `m3-demo-v2.json`, validates paths and extracts a versioned cache under ignored `.local/data/`. Later starts reuse that cache. No network or training is needed. An explicit `BIKEFLOW_DATA_ROOT` takes precedence; Compose can also use a valid external package mounted at `/data`.

Rebuild a **new version** from an updated team ZIP using:

```powershell
python scripts/package_demo_artifacts.py --source path/to/team-artifacts.zip --output artifacts/m3-demo-v2.zip
```

Update the bundle paths/manifest deliberately when adopting a new version. Do not overwrite a deployed bundle or include final-test data to choose demo scenarios.

Source: City of Chicago historical Divvy station data and official Divvy trip-derived training statistics. These are derived application inputs, not a raw dataset mirror. Retain [NOTICE_CHICAGO.md](../NOTICE_CHICAGO.md) and [DATA_SOURCES.md](../DATA_SOURCES.md). Existing source terms and the project's absence of a code-license grant are unchanged. PPO loading uses the team's serialized policy; replace model files only with trusted team artifacts.
