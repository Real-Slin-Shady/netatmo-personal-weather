# Netatmo Personal Weather

A self-hosted, ML-corrected weather dashboard for any Netatmo weather station.
Fork it, fill in your coordinates and API credentials, and get a live PWA
showing your station's observations alongside a bias-corrected 7-day forecast —
fully automated via GitHub Actions, hosted free on GitHub Pages.

---

## How it works

```
Netatmo API  ──►  fetch_observations.py  ──►  docs/observations.json
Open-Meteo   ──►  generate_forecast.py   ──►  docs/forecast.json
                          │
                    models/ (XGBoost)          ← trained weekly from your own data
                          │
                  docs/index.html  ──►  GitHub Pages PWA
```

**Every 30 minutes** GitHub Actions fetches your Netatmo readings and regenerates
the forecast. **Every Sunday** it retrains the bias-correction models using your
accumulated observation history — so the forecast gets more accurate over time,
tuned to your exact location and microclimate.

### Cold-start behaviour

| Period | What you see |
|--------|-------------|
| Week 1–2 | Raw Open-Meteo global forecast (no correction) |
| Week 3+ | XGBoost-corrected forecast, retraining weekly |

---

## Features

- **Live observations** — temperature, humidity, pressure (with trend ↑↓→), wind direction, rain
- **7-day forecast** — global Open-Meteo `best_match` model, locally debiased
- **Self-training ML** — XGBoost bias correction for temperature, humidity, rain, wind, gusts
- **Plant stress indicators** — VPD, 30-day water balance, optimal watering time
- **Charts** — temperature + humidity, precipitation + wind, 30-day rain history
- **Activity planner** — best times today for gardening, exercise, staying dry
- **Weather alerts** — frost, heat, heavy rain warnings
- **Sun times** — sunrise and sunset via SunCalc
- **PWA** — installable on phone, works offline, auto-refreshes every 20 min
- **Dark mode** — Lipari colorscale, light/dark theme

---

## Quick start

**→ Full step-by-step instructions: [SETUP.md](SETUP.md)**

Summary:

1. **Fork** this repository on GitHub
2. Edit `config.py` — set your location name, lat/lon, timezone
3. Run `python get_netatmo_token.py` locally to get your OAuth refresh token
4. Add 4 **GitHub Secrets**: `NETATMO_CLIENT_ID`, `NETATMO_CLIENT_SECRET`, `NETATMO_REFRESH_TOKEN`, `GH_PAT`
5. Enable **GitHub Pages** from `docs/` on the `main` branch
6. Trigger the first **Actions** run manually — then everything is automatic

---

## What you need

- A GitHub account (free tier is sufficient)
- A [Netatmo](https://www.netatmo.com) weather station
- A free developer app at [developer.netatmo.com](https://developer.netatmo.com)

No server. No database. No monthly cost.

---

## Security

- All credentials live exclusively in **GitHub Secrets** — never in any committed file
- The Netatmo OAuth refresh token rotates automatically on every run (via PyNaCl + GitHub API)
- `GH_PAT` should be a fine-grained token scoped to this repo only with secrets write access
- `docs/observations.json` is publicly readable as part of GitHub Pages —
  this is weather data, not personal information, but worth knowing

---

## Repository layout

```
config.py               ← edit this (location, timezone, thresholds)
fetch_observations.py   ← Netatmo poller + OAuth token rotation
generate_forecast.py    ← Open-Meteo fetch + XGBoost debiasing
train_model.py          ← weekly self-training pipeline
get_netatmo_token.py    ← one-time OAuth setup helper
requirements.txt
.github/workflows/
    update.yml          ← 30-min cron: observations + forecast
    train.yml           ← weekly cron: retrain models
models/                 ← auto-populated by train.yml
docs/
    index.html          ← PWA (reads STATION_CONFIG from config.js)
    config.js           ← auto-generated: station name, coords, model status
    manifest.json
    sw.js
```

---

## License

Proprietary — © 2024 Nils Tinner. All rights reserved.
See [LICENSE](LICENSE) for full terms.
Contact: [nilswillytinner@gmail.com](mailto:nilswillytinner@gmail.com)
