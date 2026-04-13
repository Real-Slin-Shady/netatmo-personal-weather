# Setup Guide

**Netatmo Personal Weather** — your Netatmo station as a self-hosted, ML-corrected PWA.

---

## What you get

- Live Netatmo observations (temperature, humidity, pressure, rain, wind) updated every 30 minutes
- 7-day Open-Meteo global forecast, automatically bias-corrected to your specific location
- Plant stress indicators, activity planner, rain history, sun times
- Fully automated via GitHub Actions — no server, no maintenance

The bias-correction models train automatically each Sunday from your observation history.
They activate after 2 weeks of data and improve weekly from that point on.

---

## Prerequisites

- A GitHub account (free)
- A Netatmo weather station with an active account
- A Netatmo developer application (free to create at developer.netatmo.com)

---

## Step 1 — Fork this repository

Click **Fork** on GitHub. Keep the repo **public** (GitHub Pages is free for public repos).

> **Privacy note**: your observations are stored in `docs/observations.json`, which is publicly
> readable as part of GitHub Pages. This is standard for a personal weather station — the data
> is weather readings, not personal information. If you prefer privacy, upgrade to GitHub Pro
> ($4/month) and enable GitHub Pages for private repositories.

---

## Step 2 — Edit `config.py`

Open `config.py` in the GitHub editor and set your values:

```python
LOCATION_NAME = "My Garden"        # shown in the UI
LAT           = 47.3769            # your latitude
LON           =  8.5417            # your longitude
ELEVATION     = 408                # metres above sea level
TIMEZONE      = "Europe/Zurich"    # IANA timezone string
```

A list of valid timezone strings: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones

Commit the change directly to `main`.

---

## Step 3 — Get your Netatmo credentials

1. Go to https://dev.netatmo.com and sign in with your Netatmo account
2. Create an application (any name, e.g. "My Weather Dashboard")
3. Note your **Client ID** and **Client Secret**
4. Run the OAuth flow once to get a **Refresh Token**:

```bash
pip install requests
python get_netatmo_token.py
```

Follow the printed instructions (open a URL, paste back the code).
The script will print your refresh token — copy it.

> **Security**: treat the refresh token like a password. Never commit it to the repo.

---

## Step 4 — Add GitHub Secrets

Go to your forked repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.

Add these four secrets:

| Secret name              | Value |
|--------------------------|-------|
| `NETATMO_CLIENT_ID`      | your app's client ID |
| `NETATMO_CLIENT_SECRET`  | your app's client secret |
| `NETATMO_REFRESH_TOKEN`  | the refresh token from Step 3 |
| `GH_PAT`                 | a GitHub Personal Access Token (see below) |

**Creating the `GH_PAT`**:
Go to GitHub → Profile → **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens**.
Create a token scoped to this repo only, with **Read and Write access to Secrets**.
This is needed so the workflow can automatically rotate the Netatmo refresh token after each use.

---

## Step 5 — Enable GitHub Pages

Go to your repo → **Settings** → **Pages**.
Set source to **Deploy from a branch**, branch **`main`**, folder **`/docs`**.
Click Save.

Your site will be live at `https://<your-username>.github.io/<repo-name>/` within a few minutes.

---

## Step 6 — Trigger the first run

Go to **Actions** → **Update Weather Data** → **Run workflow**.
This fetches your first observation and generates the first forecast.
Reload your GitHub Pages URL — you should see live data.

From here, everything runs automatically:
- **Every 30 minutes**: observations fetched, forecast regenerated
- **Every Sunday at 03:00 UTC**: bias-correction models retrained

---

## Frequently asked questions

**The model shows "cold-start mode" — is something broken?**
No. The XGBoost models need at least 14 days of observations to produce reliable corrections.
Come back after two weeks — it will start debiasing automatically.

**The refresh token stopped working.**
The `GH_PAT` secret may have expired (fine-grained tokens default to 30-day expiry).
Regenerate it in GitHub Settings and update the secret.

**My station has no outdoor module.**
The system falls back to indoor temperature and humidity automatically.

**Can I add icons?**
Replace `docs/icon-192.png` and `docs/icon-512.png` with your own images (PNG, 192×192 and 512×512 px).

---

## License

This software is proprietary. See [LICENSE](LICENSE) for full terms.
Contact: nilswillytinner@gmail.com
