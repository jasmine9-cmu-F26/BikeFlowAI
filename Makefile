PYTHON ?= python
ARCHIVE_REPO ?= ../baywheels-history
DATA_OUTPUT ?= data/processed/baywheels_history

.PHONY: help data external test

help:
	@echo "make data     - extract and audit a separate archive checkout"
	@echo "make external - download trip files and check weather/source availability"
	@echo "make test     - run offline synthetic tests"

data:
	"$(PYTHON)" scripts/data/extract_baywheels_history.py --repo "$(ARCHIVE_REPO)" --output "$(DATA_OUTPUT)"
	"$(PYTHON)" scripts/data/audit_baywheels_data.py --repo "$(ARCHIVE_REPO)" --input "$(DATA_OUTPUT)"

external:
	"$(PYTHON)" scripts/data/check_external_sources.py

test:
	"$(PYTHON)" -m unittest discover -s tests -v

