# Application verification — November 8, 2026

These checks verify application plumbing. They do not establish the trained team's model quality or full compliance with the proposal's online performance targets.

| Check | Result |
| --- | --- |
| Existing Python suite plus app tests | 117 tests passed / conditionally skipped (6 skips); Python 3.12 on Windows |
| Frontend | TypeScript check and Vite production build passed |
| Data/model integration | Temporary causal feature and outcome Parquet; actual tiny LightGBM booster + manifest/calibrator loaded and served |
| Decision/outcome separation | Planning succeeds with intentionally unreadable outcome files; reveal is separate and final-test access is blocked |
| Local HTTP path | Port 3000 Vite proxy → port 8000 FastAPI → synthetic B3 plan returned primary + two alternatives |
| Windows launch | Hidden-process launcher started both services and verified HTTP readiness; managed stop script tested |
| Live feed | Official discovery + station information + station status retrieved; 31 matching cohort stations present; stale station reports excluded from planning |
| Compose | Configuration validates; image build/start unverified because Docker Desktop engine was not running |
| Browser interaction and visual inspection | Not verified: browser connection unavailable and native browser control approval timed out |
| Team's external historical data / trained weights | Not present locally; not verified |
| Team's PPO weights / real policy quality | Not present locally; bridge observation/action/configuration guards tested, not a real PPO rollout |

`synthetic_smoke.json` records a separate 1,000-request synthetic replay smoke check with no server errors and 500 cached timing samples. This uses real B2 serving on generated Parquet and an in-process TestClient. It excludes a browser, network transport, real model artifact loading and a real PPO worker. Reproduce with `python scripts/benchmark_app.py`; results vary by machine.

See [startup, artifact layout and behavioral limitations](../../docs/app_demo.md).
