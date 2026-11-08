"""B1 persistence and B2 historical-rate baselines, as probabilities of unavailability."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import B2_RATE_COLUMN, COUNT_COLUMN


def b1_persistence(df: pd.DataFrame, target: str) -> np.ndarray:
    """Live-map behaviour: assume the current count stays unchanged (hard 0/1 probability).

    Base snapshots are always In Service (feature builder requirement), so
    unavailability is predicted only when the current count is zero.
    """
    return (df[COUNT_COLUMN[target]].to_numpy() <= 0).astype(float)


COUNT_CAP = 20


def fit_b1_calibrated(train_df: pd.DataFrame, target: str) -> pd.DataFrame:
    """Calibrated persistence: training-only P(unavailable | current count, horizon).

    A stronger, still non-learned reference that turns the live-map count into
    a probability. Counts above COUNT_CAP share one cell.
    """
    from . import LABEL_COLUMN
    key = train_df[COUNT_COLUMN[target]].clip(upper=COUNT_CAP).astype(int).rename('count_cell')
    table = (train_df.assign(count_cell=key).groupby(['count_cell', 'horizon_minutes'])[LABEL_COLUMN[target]]
             .agg(rate='mean', n='size').reset_index())
    return table


def b1_calibrated(df: pd.DataFrame, table: pd.DataFrame, target: str) -> np.ndarray:
    keys = pd.DataFrame(dict(count_cell=df[COUNT_COLUMN[target]].clip(upper=COUNT_CAP).astype(int).to_numpy(),
                             horizon_minutes=df['horizon_minutes'].astype(int).to_numpy()))
    merged = keys.merge(table.astype({'horizon_minutes': int}), how='left', on=['count_cell', 'horizon_minutes'], validate='many_to_one')
    p = merged['rate'].to_numpy(dtype=float)
    return np.where(np.isnan(p), b1_persistence(df, target), p)


def b2_historical(df: pd.DataFrame, rates: pd.DataFrame, target: str) -> np.ndarray:
    """Training-only station x weekday x hour availability rate at the *target* time.

    The table already carries the station-overall fallback for sparse cells.
    Stations missing from the table return NaN; callers decide the fallback.
    """
    table = rates[['station_id', 'weekday', 'hour', B2_RATE_COLUMN[target]]].rename(
        columns={'weekday': 'target_weekday', 'hour': 'target_hour'})
    keys = df[['station_id', 'target_weekday', 'target_hour']].astype({'target_weekday': 'int64', 'target_hour': 'int64'})
    table = table.astype({'target_weekday': 'int64', 'target_hour': 'int64'})
    merged = keys.merge(table, how='left', on=['station_id', 'target_weekday', 'target_hour'], validate='many_to_one')
    return 1.0 - merged[B2_RATE_COLUMN[target]].to_numpy(dtype=float)
