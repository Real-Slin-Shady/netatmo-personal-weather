# Copyright (c) 2024 Nils Tinner. All Rights Reserved.
# See LICENSE for terms. Contact: nilswillytinner@gmail.com
"""
Fetch an Open-Meteo global forecast, apply XGBoost bias correction if trained
models are available, and write:
  docs/forecast.json          — hourly raw + debiased values
  docs/forecast_history.json  — rolling 14-day store of past predictions
  docs/config.js              — frontend config injected into the UI
"""
import json, pickle
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import requests

from config import LAT, LON, ELEVATION, TIMEZONE, LOCATION_NAME, FORECAST_DAYS

OUTPUT_DIR   = Path('docs')
MODELS_DIR   = Path('models')
HISTORY_DAYS = 14   # rolling window for forecast accuracy comparison

HOURLY_VARS = [
    'temperature_2m', 'apparent_temperature', 'relative_humidity_2m',
    'precipitation', 'precipitation_probability',
    'wind_speed_10m', 'wind_gusts_10m', 'wind_direction_10m',
    'cloud_cover', 'surface_pressure', 'weather_code',
    'vapour_pressure_deficit', 'et0_fao_evapotranspiration', 'is_day',
]


# ── Open-Meteo ────────────────────────────────────────────────────────────────

def fetch_forecast() -> dict:
    """Fetch hourly forecast for the configured location via Open-Meteo best_match."""
    resp = requests.get('https://api.open-meteo.com/v1/forecast', params={
        'latitude':       LAT,
        'longitude':      LON,
        'elevation':      ELEVATION,
        'hourly':         ','.join(HOURLY_VARS),
        'models':         'best_match',          # highest-res model for any location
        'timezone':       TIMEZONE,
        'forecast_days':  FORECAST_DAYS,
        'wind_speed_unit': 'kmh',
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()


def build_raw(data: dict, i: int) -> dict:
    """Map Open-Meteo response fields to the internal raw schema."""
    h = data['hourly']
    return {
        'temperature':            h['temperature_2m'][i],
        'apparent_temperature':   h['apparent_temperature'][i],
        'humidity':               h['relative_humidity_2m'][i],
        'precipitation':          h['precipitation'][i] or 0.0,
        'precipitation_probability': h['precipitation_probability'][i] or 0,
        'wind_speed':             h['wind_speed_10m'][i],
        'wind_gusts':             h['wind_gusts_10m'][i],
        'wind_direction':         h['wind_direction_10m'][i],
        'cloud_cover':            h['cloud_cover'][i],
        'pressure':               h['surface_pressure'][i],
        'weather_code':           h['weather_code'][i],
        'vpd':                    h['vapour_pressure_deficit'][i] or 0.0,
        'et0':                    h['et0_fao_evapotranspiration'][i] or 0.0,
        'is_day':                 h['is_day'][i],
    }


# ── Model loading ─────────────────────────────────────────────────────────────

def load_models() -> tuple | None:
    """Load all XGBoost models + scalers. Returns (models_dict, meta) or None."""
    meta_file = MODELS_DIR / 'meta.json'
    if not meta_file.exists():
        return None
    try:
        import xgboost as xgb
        meta    = json.loads(meta_file.read_text())
        models  = {}
        for var in ['temperature', 'humidity', 'rain', 'wind_speed', 'gust_speed']:
            mf  = MODELS_DIR / f'xgb_{var}.json'
            sxf = MODELS_DIR / f'scaler_X_{var}.pkl'
            syf = MODELS_DIR / f'scaler_y_{var}.pkl'
            if not all(f.exists() for f in [mf, sxf, syf]):
                continue
            m = xgb.XGBRegressor()
            m.load_model(str(mf))
            with open(sxf, 'rb') as f: sx = pickle.load(f)
            with open(syf, 'rb') as f: sy = pickle.load(f)
            models[var] = (m, sx, sy)
        return (models, meta) if models else None
    except Exception as e:
        print(f"Warning: could not load models ({e}) — running without debiasing")
        return None


# ── Bias correction ───────────────────────────────────────────────────────────

def _features(raw: dict, hour: int, month: int) -> dict:
    """Build feature arrays for each variable (must match train_model.py exactly)."""
    h_sin = np.sin(2 * np.pi * hour  / 24)
    h_cos = np.cos(2 * np.pi * hour  / 24)
    m_sin = np.sin(2 * np.pi * month / 12)
    m_cos = np.cos(2 * np.pi * month / 12)
    return {
        'temperature': [raw['temperature'], h_sin, h_cos, m_sin, m_cos],
        'humidity':    [raw['humidity'],    raw['temperature'], h_sin, h_cos, m_sin, m_cos],
        'rain':        [raw['precipitation'], raw['temperature'], raw['humidity'], h_sin, h_cos, m_sin, m_cos],
        'wind_speed':  [raw['wind_speed'],  raw['temperature'], h_sin, h_cos, m_sin, m_cos],
        'gust_speed':  [raw['wind_gusts'],  raw['wind_speed'],  h_sin, h_cos, m_sin, m_cos],
    }


def debias(raw: dict, hour: int, month: int, models_data: tuple | None) -> dict:
    """Return debiased values. Falls back to raw if no models are loaded."""
    passthrough = {
        'temperature': raw['temperature'],
        'humidity':    raw['humidity'],
        'wind_speed':  raw['wind_speed'],
        'gust_speed':  raw['wind_gusts'],
        'rain':        raw['precipitation'],
    }
    if models_data is None:
        return passthrough

    models, _ = models_data
    feats     = _features(raw, hour, month)
    result    = {}

    raw_map = {
        'temperature': raw['temperature'],
        'humidity':    raw['humidity'],
        'wind_speed':  raw['wind_speed'],
        'gust_speed':  raw['wind_gusts'],
        'rain':        raw['precipitation'],
    }

    for var, (m, sx, sy) in models.items():
        X       = np.array(feats[var], dtype=np.float32).reshape(1, -1)
        X_sc    = sx.transform(X)
        b_sc    = m.predict(X_sc)[0]
        bias    = sy.inverse_transform([[b_sc]])[0][0]

        if var == 'rain':
            # Correction is in log1p space to keep rain non-negative
            corrected = np.expm1(np.log1p(max(0.0, raw['precipitation'])) + bias)
            result[var] = max(0.0, float(corrected))
        else:
            result[var] = float(raw_map[var] + bias)

    # Physical constraints
    result['humidity']   = max(0.0, min(100.0, result.get('humidity',   raw['humidity'])))
    result['wind_speed'] = max(0.0, result.get('wind_speed', raw['wind_speed']))
    result['gust_speed'] = max(0.0, result.get('gust_speed', raw['wind_gusts']))
    result['rain']       = max(0.0, result.get('rain',       raw['precipitation']))

    # Fill any variable whose model is missing
    for var, fallback in passthrough.items():
        result.setdefault(var, fallback)

    return result


# ── Output writers ────────────────────────────────────────────────────────────

def update_forecast_history(hourly: list) -> None:
    """Append future hours to rolling 14-day history (used for accuracy charts)."""
    hist_file = OUTPUT_DIR / 'forecast_history.json'
    now       = datetime.now()

    existing = []
    if hist_file.exists():
        try:
            existing = json.loads(hist_file.read_text()).get('hourly', [])
        except Exception:
            pass

    cutoff        = now - timedelta(days=HISTORY_DAYS)
    existing      = [e for e in existing
                     if datetime.fromisoformat(e['time'].split('+')[0].split('Z')[0]) > cutoff]
    existing_times = {e['time'] for e in existing}
    fc_made        = now.isoformat()

    for h in hourly:
        t = datetime.fromisoformat(h['time'].split('+')[0])
        if t <= now or h['time'] in existing_times:
            continue
        existing.append({
            'time':          h['time'],
            'temperature':   h['debiased']['temperature'],
            'humidity':      h['debiased']['humidity'],
            'rain':          h['debiased']['rain'],
            'wind_speed':    h['debiased']['wind_speed'],
            'gust_speed':    h['debiased']['gust_speed'],
            'forecast_made': fc_made,
        })
        existing_times.add(h['time'])

    existing.sort(key=lambda x: x['time'])
    hist_file.write_text(json.dumps(
        {'meta': {'updated': fc_made}, 'hourly': existing}, indent=2
    ))


def write_config_js(models_data: tuple | None) -> None:
    """Write docs/config.js — read by index.html to configure the UI."""
    meta = models_data[1] if models_data else {}
    cfg  = {
        'name':            LOCATION_NAME,
        'lat':             LAT,
        'lon':             LON,
        'timezone':        TIMEZONE,
        'model_trained':   meta.get('trained_at'),
        'model_n_samples': meta.get('n_samples', 0),
        'model_variables': meta.get('variables', []),
    }
    js = (
        "// Auto-generated by generate_forecast.py — do not edit manually.\n"
        f"window.STATION_CONFIG = {json.dumps(cfg, indent=2)};\n"
    )
    (OUTPUT_DIR / 'config.js').write_text(js)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    data        = fetch_forecast()
    models_data = load_models()
    now         = datetime.now()

    hourly = []
    for i, time_str in enumerate(data['hourly']['time']):
        t   = datetime.fromisoformat(time_str)
        raw = build_raw(data, i)
        hourly.append({
            'time':     time_str,
            'raw':      raw,
            'debiased': debias(raw, t.hour, t.month, models_data),
        })

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / 'forecast.json').write_text(json.dumps({
        'meta': {
            'generated_at': now.isoformat(),
            'location':     LOCATION_NAME,
            'lat':          LAT,
            'lon':          LON,
            'model':        'best_match',
            'debiased':     models_data is not None,
        },
        'hourly': hourly,
    }, indent=2))

    update_forecast_history(hourly)
    write_config_js(models_data)

    status = f"debiased ({models_data[1].get('trained_at', '?')})" if models_data else "raw pass-through"
    print(f"Generated {len(hourly)} forecast hours — {status}")


if __name__ == '__main__':
    main()
