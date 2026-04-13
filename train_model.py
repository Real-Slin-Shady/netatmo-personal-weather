# Copyright (c) 2024 Nils Tinner. All Rights Reserved.
# See LICENSE for terms. Contact: nilswillytinner@gmail.com
"""
Weekly XGBoost bias-correction training pipeline.

Reads:
  docs/observations.json      — actual station measurements
  docs/forecast_history.json  — what the model predicted for past hours

Joins them on timestamp, trains one XGBoost model per target variable,
and saves the results to models/ for generate_forecast.py to use.

Runs automatically every Sunday via .github/workflows/train.yml.
Below MIN_TRAIN_DAYS of data the script exits without writing any models,
so the forecast pipeline continues to pass raw values through unchanged.
"""
import json, pickle
from datetime import datetime
from pathlib import Path

import numpy as np
import xgboost as xgb
from sklearn.preprocessing import StandardScaler

from config import MIN_TRAIN_DAYS, TIMEZONE

OUTPUT_DIR = Path('docs')
MODELS_DIR = Path('models')
MODELS_DIR.mkdir(exist_ok=True)

# Feature builders and obs field paths per target variable.
# The 'log_y' flag causes bias correction to happen in log1p space (keeps rain ≥ 0).
VARIABLES = {
    'temperature': {
        'fc_key':    'temperature',
        'obs_path':  ('outdoor', 'temperature'),
        'features':  lambda r: [r['fc_temp'], r['h_sin'], r['h_cos'], r['m_sin'], r['m_cos']],
    },
    'humidity': {
        'fc_key':    'humidity',
        'obs_path':  ('outdoor', 'humidity'),
        'features':  lambda r: [r['fc_hum'], r['fc_temp'], r['h_sin'], r['h_cos'], r['m_sin'], r['m_cos']],
    },
    'rain': {
        'fc_key':    'rain',
        'obs_path':  ('rain', 'rain_1h'),
        'features':  lambda r: [r['fc_rain'], r['fc_temp'], r['fc_hum'], r['h_sin'], r['h_cos'], r['m_sin'], r['m_cos']],
        'log_y':     True,
    },
    'wind_speed': {
        'fc_key':    'wind_speed',
        'obs_path':  ('wind', 'wind_strength'),
        'features':  lambda r: [r['fc_wind'], r['fc_temp'], r['h_sin'], r['h_cos'], r['m_sin'], r['m_cos']],
    },
    'gust_speed': {
        'fc_key':    'gust_speed',
        'obs_path':  ('wind', 'gust_strength'),
        'features':  lambda r: [r['fc_gust'], r['fc_wind'], r['h_sin'], r['h_cos'], r['m_sin'], r['m_cos']],
    },
}

XGB_PARAMS = dict(
    n_estimators=300, max_depth=4, learning_rate=0.04,
    subsample=0.8, colsample_bytree=0.8,
    random_state=42, verbosity=0,
)


# ── Data loading ──────────────────────────────────────────────────────────────

def load_json(path: Path) -> list:
    if not path.exists():
        return []
    try:
        d = json.loads(path.read_text())
        return d.get('hourly', d.get('observations', []))
    except Exception:
        return []


def _get(obj: dict, path: tuple):
    """Safely retrieve a nested value by key path."""
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


# ── Pair matching ─────────────────────────────────────────────────────────────

def match_pairs(fc_list: list, obs_list: list) -> list:
    """
    Join each forecast-history entry with the nearest observation (within 45 min).
    Returns a list of dicts with both forecast and observed values + cyclic time features.
    """
    # Index observations by (date, rounded-30min-bucket) for fast lookup
    obs_index: dict[tuple, list] = {}
    for o in obs_list:
        try:
            t   = datetime.fromisoformat(o['time'])
            key = (t.date(), round((t.hour * 60 + t.minute) / 30) * 30)
            obs_index.setdefault(key, []).append((t, o))
        except Exception:
            continue

    pairs = []
    for fc in fc_list:
        try:
            t = datetime.fromisoformat(fc['time'].split('+')[0].split('Z')[0])
        except Exception:
            continue

        # Search nearby 30-min buckets (±90 min window)
        best_obs, best_diff = None, float('inf')
        fc_total_min = t.hour * 60 + t.minute
        for delta_min in range(-90, 91, 30):
            bucket = round((fc_total_min + delta_min) / 30) * 30
            key    = (t.date(), bucket)
            for obs_t, o in obs_index.get(key, []):
                diff = abs((obs_t.replace(tzinfo=None) - t).total_seconds())
                if diff < best_diff and diff <= 45 * 60:
                    best_diff = diff
                    best_obs  = o

        if best_obs is None:
            continue

        h_sin = np.sin(2 * np.pi * t.hour  / 24)
        h_cos = np.cos(2 * np.pi * t.hour  / 24)
        m_sin = np.sin(2 * np.pi * t.month / 12)
        m_cos = np.cos(2 * np.pi * t.month / 12)

        pairs.append({
            'fc_temp': fc.get('temperature', 0),
            'fc_hum':  fc.get('humidity',    0),
            'fc_rain': fc.get('rain',        0),
            'fc_wind': fc.get('wind_speed',  0),
            'fc_gust': fc.get('gust_speed',  0),
            'h_sin': h_sin, 'h_cos': h_cos,
            'm_sin': m_sin, 'm_cos': m_cos,
            'obs': best_obs,
        })

    return pairs


# ── Training ──────────────────────────────────────────────────────────────────

def train_one(var: str, cfg: dict, pairs: list) -> bool:
    """Train and save one XGBoost bias-correction model. Returns True on success."""
    X_rows, y_rows = [], []
    log_y = cfg.get('log_y', False)

    for row in pairs:
        fc_key_map = {
            'temperature': 'fc_temp', 'humidity': 'fc_hum', 'rain': 'fc_rain',
            'wind_speed':  'fc_wind', 'gust_speed': 'fc_gust',
        }
        raw_val = row.get(fc_key_map[var])
        obs_val = _get(row['obs'], cfg['obs_path'])
        if raw_val is None or obs_val is None:
            continue

        bias = (np.log1p(max(0, obs_val)) - np.log1p(max(0, raw_val))) if log_y \
               else (obs_val - raw_val)
        if not np.isfinite(bias):
            continue

        X_rows.append(cfg['features'](row))
        y_rows.append(bias)

    n = len(X_rows)
    if n < 50:
        print(f"  {var}: {n} samples — skipping (need ≥ 50)")
        return False

    X = np.array(X_rows, dtype=np.float32)
    y = np.array(y_rows, dtype=np.float32)

    sx = StandardScaler().fit(X)
    sy = StandardScaler().fit(y.reshape(-1, 1))
    X_sc = sx.transform(X)
    y_sc = sy.transform(y.reshape(-1, 1)).ravel()

    model = xgb.XGBRegressor(**XGB_PARAMS)
    model.fit(X_sc, y_sc)

    # In-sample MAE (optimistic but useful for sanity-checking)
    y_pred = sy.inverse_transform(model.predict(X_sc).reshape(-1, 1)).ravel()
    mae    = float(np.mean(np.abs(y - y_pred)))
    print(f"  {var}: {n} samples, in-sample bias MAE = {mae:.3f}")

    model.save_model(str(MODELS_DIR / f'xgb_{var}.json'))
    with open(MODELS_DIR / f'scaler_X_{var}.pkl', 'wb') as f: pickle.dump(sx, f)
    with open(MODELS_DIR / f'scaler_y_{var}.pkl', 'wb') as f: pickle.dump(sy, f)
    return True


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    obs_list = load_json(OUTPUT_DIR / 'observations.json')
    fc_list  = load_json(OUTPUT_DIR / 'forecast_history.json')

    if not obs_list or not fc_list:
        print("No data — nothing to train on.")
        return

    # Require minimum history before training
    try:
        times = [datetime.fromisoformat(o['time']) for o in obs_list]
        days  = (max(times) - min(times)).days
    except Exception:
        days = 0

    if days < MIN_TRAIN_DAYS:
        print(f"Only {days}/{MIN_TRAIN_DAYS} days of data — skipping training.")
        return

    print(f"Training on {days} days of observations ({len(obs_list)} obs, {len(fc_list)} forecast hours)")

    pairs = match_pairs(fc_list, obs_list)
    print(f"Matched {len(pairs)} forecast-observation pairs")

    if len(pairs) < 50:
        print("Too few matched pairs — skipping.")
        return

    trained = [var for var, cfg in VARIABLES.items() if train_one(var, cfg, pairs)]

    meta = {
        'trained_at':   datetime.utcnow().strftime('%Y-%m-%d'),
        'n_samples':    len(pairs),
        'days_of_data': days,
        'variables':    trained,
    }
    (MODELS_DIR / 'meta.json').write_text(json.dumps(meta, indent=2))
    print(f"Done. Trained: {trained}")


if __name__ == '__main__':
    main()
