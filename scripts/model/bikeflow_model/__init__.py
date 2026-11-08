"""BikeFlow AI forecaster: baselines, LightGBM + sigmoid calibration, metrics and serving fallbacks."""

TARGETS = ('bike', 'dock')
LABEL_COLUMN = {'bike': 'bike_unavailable', 'dock': 'dock_unavailable'}
COUNT_COLUMN = {'bike': 'num_bikes_available', 'dock': 'num_docks_available'}
B2_RATE_COLUMN = {'bike': 'bike_available_rate', 'dock': 'dock_available_rate'}
ZONE = 'America/Chicago'
