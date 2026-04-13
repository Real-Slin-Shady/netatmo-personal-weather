# Copyright (c) 2024 Nils Tinner. All Rights Reserved.
# See LICENSE for terms. Contact: nilswillytinner@gmail.com
"""
Fetch current Netatmo station data and maintain a rolling observation history.
Automatically rotates the Netatmo OAuth2 refresh token and writes the new value
back to GitHub Actions Secrets so subsequent runs continue to authenticate.

Required environment variables (set as GitHub Secrets):
    NETATMO_CLIENT_ID
    NETATMO_CLIENT_SECRET
    NETATMO_REFRESH_TOKEN
    GH_PAT              — personal access token with 'secrets' write scope
    GITHUB_REPOSITORY   — injected automatically by Actions (owner/repo)
"""
import base64, json, os, requests
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from config import TIMEZONE, HISTORY_DAYS

TZ           = ZoneInfo(TIMEZONE)
OUTPUT_FILE  = Path('docs/observations.json')
TOKEN_URL    = 'https://api.netatmo.com/oauth2/token'
STATIONS_URL = 'https://api.netatmo.com/api/getstationsdata'


# ── Authentication ────────────────────────────────────────────────────────────

def get_access_token() -> str:
    """Exchange the refresh token for a short-lived access token.
    If Netatmo issues a new refresh token, rotate it in GitHub Secrets.
    """
    resp = requests.post(TOKEN_URL, data={
        'grant_type':    'refresh_token',
        'client_id':     os.environ['NETATMO_CLIENT_ID'],
        'client_secret': os.environ['NETATMO_CLIENT_SECRET'],
        'refresh_token': os.environ['NETATMO_REFRESH_TOKEN'],
    }, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    new_refresh = data.get('refresh_token')
    if new_refresh and new_refresh != os.environ.get('NETATMO_REFRESH_TOKEN'):
        _rotate_github_secret('NETATMO_REFRESH_TOKEN', new_refresh)

    return data['access_token']


def _rotate_github_secret(name: str, value: str) -> None:
    """Encrypt and push an updated secret to GitHub Actions via the REST API.
    Requires GH_PAT (fine-grained or classic with repo secrets write scope).
    """
    gh_pat = os.environ.get('GH_PAT')
    repo   = os.environ.get('GITHUB_REPOSITORY')
    if not gh_pat or not repo:
        print(f"Warning: skipping {name} rotation — GH_PAT or GITHUB_REPOSITORY missing")
        return

    headers = {
        'Authorization':        f'Bearer {gh_pat}',
        'Accept':               'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }

    # GitHub requires the secret to be encrypted with the repo's libsodium public key
    key_resp = requests.get(
        f'https://api.github.com/repos/{repo}/actions/secrets/public-key',
        headers=headers, timeout=15,
    )
    key_resp.raise_for_status()
    key_data = key_resp.json()

    encrypted = _seal(key_data['key'], value)

    requests.put(
        f'https://api.github.com/repos/{repo}/actions/secrets/{name}',
        headers=headers, timeout=15,
        json={'encrypted_value': encrypted, 'key_id': key_data['key_id']},
    ).raise_for_status()
    print(f"Rotated GitHub secret: {name}")


def _seal(public_key_b64: str, plaintext: str) -> str:
    """Encrypt plaintext using a libsodium sealed box (required by GitHub API)."""
    from nacl import encoding, public as nacl_public
    pk  = nacl_public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder())
    box = nacl_public.SealedBox(pk)
    return base64.b64encode(box.encrypt(plaintext.encode())).decode()


# ── Data fetching ─────────────────────────────────────────────────────────────

def fetch_station_data(access_token: str) -> dict:
    resp = requests.get(
        STATIONS_URL,
        headers={'Authorization': f'Bearer {access_token}'},
        params={'get_favorites': False},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def parse_station(data: dict) -> dict:
    """Parse a Netatmo getstationsdata response into a flat observation dict.
    Auto-discovers modules by type — compatible with any Netatmo station setup.
    """
    devices = data.get('body', {}).get('devices', [])
    if not devices:
        raise ValueError("No Netatmo devices found in API response")

    station = devices[0]
    obs = {
        'time':         datetime.now(TZ).isoformat(),
        'station_name': station.get('station_name', 'Unknown'),
    }

    # Base station — indoor sensors
    d = station.get('dashboard_data', {})
    if d:
        obs['indoor'] = {
            'temperature': d.get('Temperature'),
            'humidity':    d.get('Humidity'),
            'pressure':    d.get('Pressure'),
            'co2':         d.get('CO2'),
            'noise':       d.get('Noise'),
        }

    # Additional modules
    for module in station.get('modules', []):
        mtype = module.get('type', '')
        d     = module.get('dashboard_data', {})
        if not d:
            continue
        if mtype == 'NAModule1':    # outdoor temp + humidity
            obs['outdoor'] = {
                'temperature': d.get('Temperature'),
                'humidity':    d.get('Humidity'),
            }
        elif mtype == 'NAModule3':  # rain gauge
            obs['rain'] = {
                # Prefer hourly sum; fall back to point measurement
                'rain_1h':  d.get('sum_rain_1') if d.get('sum_rain_1') is not None else d.get('Rain', 0),
                'rain_24h': d.get('sum_rain_24', 0),
            }
        elif mtype == 'NAModule2':  # anemometer
            obs['wind'] = {
                'wind_strength': d.get('WindStrength'),
                'wind_angle':    d.get('WindAngle'),
                'gust_strength': d.get('GustStrength'),
                'gust_angle':    d.get('GustAngle'),
            }

    return obs


# ── Persistence ───────────────────────────────────────────────────────────────

def save_history(existing: list, new_obs: dict) -> None:
    """Prune observations older than HISTORY_DAYS and append the new one."""
    cutoff = datetime.now(TZ) - timedelta(days=HISTORY_DAYS)

    recent = []
    for o in existing:
        try:
            t = datetime.fromisoformat(o['time'])
            if t.tzinfo is None:
                t = t.replace(tzinfo=TZ)
            if t > cutoff:
                recent.append(o)
        except Exception:
            continue

    # Skip exact duplicate timestamps
    if not recent or recent[-1].get('time') != new_obs['time']:
        recent.append(new_obs)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps({
        'meta': {
            'station_name':      new_obs.get('station_name'),
            'last_update':       new_obs['time'],
            'history_days':      HISTORY_DAYS,
            'observation_count': len(recent),
        },
        'current':      new_obs,
        'observations': recent,
    }, indent=2))
    print(f"Saved {len(recent)} observations (latest: {new_obs['time']})")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    token = get_access_token()
    raw   = fetch_station_data(token)
    obs   = parse_station(raw)

    existing = []
    if OUTPUT_FILE.exists():
        try:
            existing = json.loads(OUTPUT_FILE.read_text()).get('observations', [])
        except Exception:
            pass

    save_history(existing, obs)


if __name__ == '__main__':
    main()
