# Frozen first official Chicago audit source

These exact script bytes produced the original 42-station 2021 audit and failed 2022 comparison. Recorded source hashes continue to resolve here after the active scripts were refactored. Their original helper modules are in ../citybikes/scripts/data/. For reproduction, put that directory on PYTHONPATH, run from the project root, and supply explicit input/output paths. Do not overwrite the original reports.

The active scripts import shared utilities from scripts/data/bikeflow_data and support a separately specified app cohort. Original aggregate results remain unchanged.
