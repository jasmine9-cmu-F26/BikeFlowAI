# BikeFlow AI

BikeFlow AI is a planned Bay Wheels trip planner that helps riders choose pickup and return stations, departure times, and backup stations using predicted bike and dock availability.

**Current milestone: data extraction and audit.** The application, forecasting models, RL policy, and replay evaluator are not implemented in this repository yet.

The initial audit is **FALLBACK under the proposal's original gate**: the archive covers 2022-08-07 through 2023-07-19, but only 57.56% of fixed seven-minute slots are observed. No station meets the 90% coverage requirement. The team must revise the data plan and repeat acceptance before freezing a training dataset.

See the [audit report](reports/data_audit/data_audit.md), [license and overlap checks](reports/data_audit/licensing_and_overlap.md), and [validation record](reports/data_audit/validation.md).

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
reports/data_audit/   Aggregate audit results and source evidence
tests/                Temporal matching and extraction/audit integration tests
tests/fixtures/       Small synthetic station-status fixture
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

`make data` extracts and audits the archive. `make external` separately downloads trip files and probes weather availability. Generated files go to ignored local directories.

## Run locally, train, and evaluate

The UI/API, model training, and replay evaluation are not available yet. There are no `make train` or `make eval` targets until those stages are implemented. The current runnable deliverables are the data pipeline and tests.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Or use `make test`. Tests use synthetic fixtures and temporary Git repositories; no archive clone or network access is required.

## Team

Feifan Yang, Jasmine Zhang, Liye Fu, Xiaohan Zhou, Zhouheng Tao.

## Data licensing

The community archive has no identified repository license. Official Bay Wheels data has separate terms; raw archive snapshots and trip datasets are not redistributed here. See the [license audit](reports/data_audit/licensing_and_overlap.md).
The project has not selected a code license; this repository does not assign a new license to third-party data.

