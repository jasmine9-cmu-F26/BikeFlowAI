"""LightGBM unavailability forecaster with sigmoid (Platt) calibration and serving fallbacks."""
from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass, field
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import sklearn
from sklearn.linear_model import LogisticRegression

from . import LABEL_COLUMN, TARGETS
from .baselines import b2_historical
from .data import feature_columns, load_schema, to_matrix

SEED = 668
PARAMS = dict(objective='binary', learning_rate=0.05, num_leaves=63, min_data_in_leaf=200,
              feature_fraction=0.9, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0,
              seed=SEED, deterministic=True, force_row_wise=True, num_threads=4, verbose=-1)
MAX_ROUNDS = 2000
EARLY_STOP = 50
EPS = 1e-6


def _logit(p):
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


@dataclass
class Sigmoid:
    a: float = 1.0
    b: float = 0.0

    @classmethod
    def fit(cls, raw_p, y):
        lr = LogisticRegression(C=1e6, solver='lbfgs', max_iter=1000)
        lr.fit(_logit(raw_p).reshape(-1, 1), np.asarray(y, int))
        return cls(float(lr.coef_[0, 0]), float(lr.intercept_[0]))

    def __call__(self, raw_p):
        return 1.0 / (1.0 + np.exp(-(self.a * _logit(raw_p) + self.b)))


@dataclass
class TrainedTarget:
    booster: lgb.Booster
    calibrator: Sigmoid
    best_iteration: int
    inner_valid: dict = field(default_factory=dict)


def fit_target(train_df, valid_df, target, columns, categories, params=None) -> TrainedTarget:
    """Fit on the early part of train, early-stop + Platt-calibrate on the late part of train."""
    params = dict(PARAMS, **(params or {}))
    y_tr, y_va = train_df[LABEL_COLUMN[target]].to_numpy(), valid_df[LABEL_COLUMN[target]].to_numpy()
    dtr = lgb.Dataset(to_matrix(train_df, columns, categories), y_tr, categorical_feature=['station_id'] if 'station_id' in columns else 'auto', free_raw_data=False)
    dva = lgb.Dataset(to_matrix(valid_df, columns, categories), y_va, reference=dtr)
    booster = lgb.train(params, dtr, MAX_ROUNDS, valid_sets=[dva], valid_names=['inner'],
                        callbacks=[lgb.early_stopping(EARLY_STOP, verbose=False)])
    raw = booster.predict(to_matrix(valid_df, columns, categories), num_iteration=booster.best_iteration)
    return TrainedTarget(booster, Sigmoid.fit(raw, y_va), int(booster.best_iteration))


def predict_target(model: TrainedTarget, df, columns, categories, calibrated=True):
    raw = model.booster.predict(to_matrix(df, columns, categories), num_iteration=model.best_iteration)
    return model.calibrator(raw) if calibrated else raw


def sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_bundle(out: Path, models: dict, columns, categories, meta: dict):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    for target, m in models.items():
        path = out / f'{target}_lgbm.txt'
        m.booster.save_model(str(path), num_iteration=m.best_iteration)
        files[target] = dict(model=path.name, sha256=sha256(path), best_iteration=m.best_iteration,
                             calibrator=dict(type='sigmoid_platt', a=m.calibrator.a, b=m.calibrator.b))
    manifest = dict(version='forecaster_v0_m3', feature_columns=list(columns), station_categories=list(categories),
                    params=PARAMS, max_rounds=MAX_ROUNDS, early_stopping_rounds=EARLY_STOP, targets=files,
                    output='probability of UNAVAILABILITY (bikes==0 or dock==0 or not in service) at horizon',
                    library_versions=dict(lightgbm=lgb.__version__, sklearn=sklearn.__version__, numpy=np.__version__,
                                          pandas=pd.__version__, python=platform.python_version()), **meta)
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


class ForecasterService:
    """Runtime wrapper. Never trains. Fallback chain: LightGBM+sigmoid -> B2 -> unavailable.

    Stale inputs (base_age_seconds > max_input_age_seconds) suppress every
    prediction, including B2, matching FR5.
    """

    def __init__(self, model_dir: Path | None, b2_rates: pd.DataFrame | None, max_input_age_seconds: int = 900):
        self.max_age = max_input_age_seconds
        self.b2 = b2_rates
        self.models, self.errors = {}, []
        self.columns, self.categories = feature_columns(load_schema()), []
        if model_dir is not None:
            try:
                manifest = json.loads((Path(model_dir) / 'manifest.json').read_text(encoding='utf-8'))
                if manifest['feature_columns'] != self.columns:
                    raise ValueError('feature schema mismatch between model manifest and committed schema')
                self.categories = manifest['station_categories']
                for target in TARGETS:
                    info = manifest['targets'][target]
                    path = Path(model_dir) / info['model']
                    if sha256(path) != info['sha256']:
                        raise ValueError(f'{target} model hash mismatch')
                    booster = lgb.Booster(model_file=str(path))
                    cal = Sigmoid(info['calibrator']['a'], info['calibrator']['b'])
                    self.models[target] = TrainedTarget(booster, cal, booster.current_iteration())
                self.version = manifest['version']
            except Exception as exc:  # degraded start, reported by status()
                self.models, self.errors = {}, [f'forecaster disabled: {exc}']
        if self.b2 is None:
            self.errors.append('B2 rates missing')

    def status(self) -> dict:
        method = 'lightgbm_sigmoid' if self.models else ('B2_historical' if self.b2 is not None else 'unavailable')
        state = 'ready' if self.models else ('degraded' if self.b2 is not None else 'unavailable')
        return dict(status=state, active_method=method, errors=self.errors)

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        stale = df['base_age_seconds'].to_numpy(float) > self.max_age
        method = np.full(len(df), 'unavailable', dtype=object)
        for target in TARGETS:
            p = np.full(len(df), np.nan)
            if self.b2 is not None:
                p = b2_historical(df, self.b2, target)
                method[~np.isnan(p)] = 'B2_historical'
            known = df['station_id'].isin(self.categories).to_numpy()
            if self.models and known.any():
                try:
                    p[known] = predict_target(self.models[target], df[known], self.columns, self.categories)
                    method[known] = 'lightgbm_sigmoid'
                except Exception as exc:
                    self.errors.append(f'inference failed, using B2: {exc}')
            p[stale] = np.nan
            out[f'p_{target}_available'] = 1.0 - p
        method[stale] = 'suppressed_stale_input'
        out['method'] = method
        return out
