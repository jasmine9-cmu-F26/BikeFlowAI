# Application verification — November 9, 2026

These checks verify application plumbing. They do not establish the trained team's model quality or full compliance with the proposal's online performance targets.

| Check | Result |
| --- | --- |
| Existing Python suite plus app tests | 123 tests: 120 passed, 3 conditionally skipped; Python 3.12 on Windows with the full PPO runtime |
| Frontend | 4 frontend tests, TypeScript check and Vite production build passed |
| Data/model integration | Actual team forecaster_v0_m3 boosters, calibrators and tune Parquet loaded from the Git-tracked 5.7 MB bundle; synthetic provider regressions also pass |
| Decision/outcome separation | Planning succeeds with intentionally unreadable outcome files; reveal is separate and final-test access is blocked |
| Local HTTP path | Port 3000 Vite proxy → port 8000 FastAPI → synthetic B3 plan returned primary + two alternatives |
| Windows launch | Default launcher started both services without BIKEFLOW_DATA_ROOT; reported lightgbm_sigmoid / bundled_m3_tune / PPO ready; managed stop script tested |
| Live feed | Official discovery + station information + station status retrieved; 31 matching cohort stations present; stale station reports excluded from planning |
| Compose | Configuration validates; image build/start unverified because Docker Desktop engine was not running |
| Browser interaction and visual inspection | Not verified: browser connection unavailable and native browser control approval timed out |
| Team's historical data / trained weights | Verified hashes and feature order; 32-station tune-only serving subset included in Git; calibration/final-test data excluded |
| Team's PPO weights / inference | Real serialized policy loaded and executed in an isolated process; actual_method=RL_pickup+B3_return. This is a current-action serving check, not a new quality evaluation |

`synthetic_smoke.json` records a separate 1,000-request synthetic replay smoke check with no server errors and 500 cached timing samples. This uses real B2 serving on generated Parquet and an in-process TestClient. It excludes a browser, network transport, real model artifact loading and a real PPO worker. Reproduce with `python scripts/benchmark_app.py`; results vary by machine.

See [startup, artifact layout and behavioral limitations](../../docs/app_demo.md).

`m3_integration.json` records the November 9 real-artifact HTTP check, including the bundle checksum, readiness, actual methods, reveal and replan. The first request includes forecast cache warm-up; PPO includes a cold worker start (~5 seconds here). Neither timing is a held-out quality result or an end-to-end browser performance claim.
