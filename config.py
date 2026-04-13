# Copyright (c) 2024 Nils Tinner. All Rights Reserved.
# See LICENSE for terms. Contact: nilswillytinner@gmail.com
#
# ── USER CONFIGURATION ────────────────────────────────────────────────────────
# Edit this file to match your station and preferences.
# All credentials belong in GitHub Secrets, never here.
# ──────────────────────────────────────────────────────────────────────────────

# ── Location ──────────────────────────────────────────────────────────────────
LOCATION_NAME = "My Weather Station"   # shown in the UI header
LAT           = 47.3769               # decimal degrees, positive = North
LON           =  8.5417               # decimal degrees, positive = East
ELEVATION     = 408                   # metres above sea level (used for ET₀ calc)
TIMEZONE      = "Europe/Zurich"       # IANA timezone string

# ── Data retention ────────────────────────────────────────────────────────────
# Longer history = better model, but larger observations.json file.
# At 30-min intervals: 90 days ≈ 4,320 observations ≈ ~2 MB
HISTORY_DAYS  = 90   # days of observations to retain
FORECAST_DAYS =  7   # days ahead to fetch from Open-Meteo

# ── Model training ────────────────────────────────────────────────────────────
# The model will not attempt training until this many days of observations exist.
# Below this threshold, raw forecast values are passed through unchanged.
MIN_TRAIN_DAYS = 14
