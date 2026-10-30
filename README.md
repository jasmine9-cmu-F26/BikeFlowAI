# BikeFlow AI

Project repository: [jasmine9-cmu-F26/BikeFlowAI](https://github.com/jasmine9-cmu-F26/BikeFlowAI).

BikeFlow AI is a planned Bay Wheels trip planner that helps riders choose pickup and return stations, departure times, and backup stations using predicted bike and dock availability.

**Initial archive audit complete. Revised sampling and label rules are pending validation.** Under the revised Milestone 2 proposal, the archive is treated as an irregularly sampled time series, weather is optional for the MVP, and station/mapping/split manifests remain provisional until the revised data rules are validated.

The application, forecasting models, RL policy, and replay evaluator are not implemented in this repository yet.

The initial audit records **FALLBACK for the original seven-minute / 90% coverage gate**: the archive covers 2022-08-07 through 2023-07-19, with 57.56% coverage on that grid. This is a historical finding about the original sampling assumption, not a feasibility verdict on the revised project. No training-ready dataset has been approved or frozen yet.

See the [audit report](reports/data_audit/data_audit.md), [license and overlap checks](reports/data_audit/licensing_and_overlap.md), and [validation record](reports/data_audit/validation.md). The [audit context](reports/data_audit/README.md) explains how to interpret those original results under the revised proposal.

| Deliverable | Current status |
|---|---|
| Archive extraction, initial audit, source checks | Implemented; initial aggregate results recorded |
| Station, historical mapping, split manifests | Provisional; selected station list intentionally empty |
| Revised sampling / freshness / label rules | Pending comparison and validation |
| Trip-to-archive IDs, DST handling, features / labels | Pending implementation |
| Baselines, calibrated forecasting, RL, UI/API, evaluation | Planned |

## Architecture

The proposed system has an offline pipeline and an online application:

```text
Historical GBFS archive + trips + optional archived forecasts
    -> extraction / audit / station mapping
    -> features and labels -> forecaster -> calibration
    -> replay environment / policy training -> held-out evaluation

React / TypeScript / Leaflet UI
    -> FastAPI -> cached station status + calibrated forecaster + planner
```

Station mapping, feature building, training, calibration, replay, and the UI/API remain future work. Missing snapshots must never be treated as empty stations.

## Repository structure

```text
scripts/data/          Implemented extraction, audit, external checks, dependencies
data/manifests/        Candidate stations and provisional station/split manifests
reports/data_audit/   Initial aggregate audit results and interpretation notes
docs/                 Data handoff requirements and acceptance checklist
tests/                Temporal matching and extraction/audit integration tests
tests/fixtures/       Small synthetic station-status fixture
.github/workflows/   CI configuration for offline tests on Linux and Windows
```

Future components will live in `frontend/`, `backend/`, `scripts/train/`, `scripts/evaluation/`, `models/forecaster/`, `models/policy/`, and `reports/evaluation/` when implemented. Docker Compose will be added with the application.

## Setup

Use a separate Python environment for this audit. The validated environment is Python 3.14.7; package versions are pinned in `scripts/data/requirements.txt`. The proposed application environment is separate.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If Windows `python` or `py` aliases do not work, use the actual installed Python executable to create the environment.

## Data setup

Raw datasets are not committed. Clone the source archive separately and use `--repo` to point at that checkout; **do not use this project repository as the source archive**.

Follow [data/README.md](data/README.md) for the frozen source revision and complete PowerShell commands. With GNU Make installed, from the project root:

```text
make data ARCHIVE_REPO=../baywheels-history PYTHON=.venv/Scripts/python.exe
make external PYTHON=.venv/Scripts/python.exe
```

`make data` reproduces extraction and the **original-rule audit** (seven-minute slots, 3.5-minute matching tolerance). It does not implement or certify the revised sampling rule. `make external` separately downloads trip files and probes weather availability. Generated files go to ignored local directories.

## Next data milestone

Follow the [data handoff checklist](docs/data_handoff.md) in this order:

1. Compare documented horizon, tolerance, and freshness candidates using training-period evidence; report retained labels, matching errors, and event counts.
2. Reconcile historical trip/archive station IDs and Pacific timestamps, including DST cases.
3. Build causal features and valid future labels, validate split boundaries, then freeze the station list, mapping, split, and rule configuration.
4. Hand the tables and schema to the baseline, forecaster, and replay owners.

Weather remains optional. The original audit reports are retained as provenance; validation of the revised design must be reported separately before updating the project readiness status.

## Run locally, train, and evaluate

The UI/API, model training, and replay evaluation are not available yet. There are no `make train` or `make eval` targets until those stages are implemented. The current runnable deliverables are the data pipeline and tests.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Or use `make test`. Tests use synthetic fixtures and temporary Git repositories; no archive clone or network access is required.

The [test workflow](.github/workflows/tests.yml) is configured for pushes, pull requests, and manual runs with Python 3.14 on Ubuntu and Windows. It installs the pinned dependencies and runs the same offline tests; it does not download the archive or raw trip data. Hosted CI results become available after the workflow is committed and pushed.

## Team

Feifan Yang, Jasmine Zhang, Liye Fu, Xiaohan Zhou, Zhouheng Tao.

## Data licensing

The community archive has no identified repository license. Official Bay Wheels data has separate terms; raw archive snapshots and trip datasets are not redistributed here. See the [license audit](reports/data_audit/licensing_and_overlap.md).
The project has not selected a code license; this repository does not assign a new license to third-party data.

