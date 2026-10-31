PYTHON ?= python
DIVVY_ROOT ?= ../../BikeFlowAI-data/divvy
DATA_ROOT ?= $(DIVVY_ROOT)/chicago_historical_2021_sample

.PHONY: help data download audit app-audit audit-base trips collector-once test

help:
	@echo "make data           - bounded download then separate app32 snapshot/trip audit"
	@echo "make download       - at most 50 stations / 18 weeks / one million snapshots"
	@echo "make audit          - rebuild app32 reports/protocol; original 42 results preserved"
	@echo "make audit-base     - reproduce base snapshot audit into separate comparison outputs"
	@echo "make trips          - rebuild app32 trip/OD report after app32 snapshot setup"
	@echo "make collector-once - one full current official GBFS poll"
	@echo "make test           - offline active and legacy synthetic tests"

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
