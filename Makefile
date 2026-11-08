PYTHON ?= python
DIVVY_ROOT ?= ../../BikeFlowAI-data/divvy
DATA_ROOT ?= $(DIVVY_ROOT)/chicago_historical_2021_sample

RL_STEPS ?= 300000
RL_MODEL ?= $(DATA_ROOT)/models/rl_dev/ppo.zip

.PHONY: help data download audit app-audit audit-base trips collector-once test features train forward replay-demo rl-train rl-eval rl-eval-final pipeline

help:
	@echo "make data           - bounded download then separate app32 snapshot/trip audit"
	@echo "make download       - at most 50 stations / 18 weeks / one million snapshots"
	@echo "make audit          - rebuild app32 reports/protocol; original 42 results preserved"
	@echo "make audit-base     - reproduce base snapshot audit into separate comparison outputs"
	@echo "make trips          - rebuild app32 trip/OD report after app32 snapshot setup"
	@echo "make collector-once - one full current official GBFS poll"
	@echo "make test           - offline active and legacy synthetic tests"
	@echo "make features       - OD audit then causal feature/label tables (new external version)"
	@echo "make train          - LightGBM + B1/B2 on tune split -> reports/forecaster_m3"
	@echo "make forward        - expanding-week train-pool probabilities for RL"
	@echo "make replay-demo    - print replay forecasts at one historical time"
	@echo "make rl-train       - MaskablePPO on the training-week replay (needs scripts/rl/requirements-ppo.txt)"
	@echo "make rl-eval        - B1/B2/B3 greedy and RL on identical tune requests -> reports/rl_eval/tune"
	@echo "make rl-eval-final  - frozen settings only: same comparison on test, once (needs final test scores)"
	@echo "make pipeline       - train, forward, rl-train, rl-eval in one pass"

data:
	"$(PYTHON)" scripts/data/download_chicago_sample.py --data-root "$(DATA_ROOT)"
	"$(PYTHON)" scripts/data/build_app_cohort.py --data-root "$(DATA_ROOT)"

download:
	"$(PYTHON)" scripts/data/download_chicago_sample.py --data-root "$(DATA_ROOT)"

audit app-audit:
	"$(PYTHON)" scripts/data/build_app_cohort.py --data-root "$(DATA_ROOT)"

audit-base:
	"$(PYTHON)" scripts/data/audit_chicago_historical.py --data-root "$(DATA_ROOT)" --reports reports/chicago_historical_audit/reproduced_base --manifests data/manifests/chicago/reproduced_base

trips:
	"$(PYTHON)" scripts/data/audit_chicago_trips.py --data-root "$(DATA_ROOT)" --reports reports/chicago_historical_audit/app32 --manifests data/manifests/chicago/app32

collector-once:
	"$(PYTHON)" scripts/data/collect_divvy_gbfs.py --data-root "$(DIVVY_ROOT)" --once

test:
	"$(PYTHON)" -m unittest discover -s tests -v

features:
	"$(PYTHON)" scripts/data/audit_final_trip_od.py --data-root "$(DATA_ROOT)"
	"$(PYTHON)" scripts/data/build_audited_features.py --data-root "$(DATA_ROOT)"

train:
	"$(PYTHON)" scripts/model/train_forecaster.py --data-root "$(DATA_ROOT)"

forward:
	"$(PYTHON)" scripts/model/build_forward_predictions.py --data-root "$(DATA_ROOT)"

REPLAY_TIME ?= 2021-07-20 08:00
replay-demo:
	"$(PYTHON)" scripts/model/replay_forecast.py --data-root "$(DATA_ROOT)" --time "$(REPLAY_TIME)" --reveal

rl-train:
	"$(PYTHON)" scripts/rl/train_ppo.py --data-root "$(DATA_ROOT)" --steps $(RL_STEPS)

rl-eval:
	"$(PYTHON)" scripts/rl/evaluate.py --data-root "$(DATA_ROOT)" --rl-model "$(RL_MODEL)"

rl-eval-final:
	"$(PYTHON)" scripts/rl/evaluate.py --data-root "$(DATA_ROOT)" --rl-model "$(RL_MODEL)" --final

# Separate processes on purpose: torch and lightgbm each bundle libomp.
pipeline: train forward rl-train rl-eval
