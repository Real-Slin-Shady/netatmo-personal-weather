# Copyright (c) 2024 Nils Tinner. All Rights Reserved.
# See LICENSE for terms.
"""
One-time OAuth2 helper: obtains a Netatmo refresh token.
Run locally ONCE after creating your developer application at developer.netatmo.com.
The printed refresh token goes into the NETATMO_REFRESH_TOKEN GitHub Secret.

Usage:
    python get_netatmo_token.py
"""
import os, sys, webbrowser
import requests

AUTH_URL  = 'https://api.netatmo.com/oauth2/authorize'
TOKEN_URL = 'https://api.netatmo.com/oauth2/token'
SCOPE     = 'read_station'


def main():
    client_id     = os.environ.get('NETATMO_CLIENT_ID')     or input("Client ID:     ").strip()
    client_secret = os.environ.get('NETATMO_CLIENT_SECRET') or input("Client Secret: ").strip()

    redirect_uri = 'http://localhost'
    auth_url = (
        f"{AUTH_URL}?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={SCOPE}"
        f"&response_type=code"
        f"&state=setup"
    )

    print("\n1. Opening the Netatmo authorization page in your browser.")
    print("   If it doesn't open, visit this URL manually:\n")
    print(f"   {auth_url}\n")
    webbrowser.open(auth_url)

    print("2. After authorizing, you will be redirected to a localhost URL that fails to load.")
    print("   Copy the full URL from the address bar and paste it here.")
    redirected = input("\nPaste the redirect URL: ").strip()

    # Extract the authorization code from the URL query string
    from urllib.parse import urlparse, parse_qs
    code = parse_qs(urlparse(redirected).query).get('code', [None])[0]
    if not code:
        print("Error: could not find 'code' in the URL. Make sure you pasted the full URL.")
        sys.exit(1)

    resp = requests.post(TOKEN_URL, data={
        'grant_type':    'authorization_code',
        'client_id':     client_id,
        'client_secret': client_secret,
        'code':          code,
        'redirect_uri':  redirect_uri,
        'scope':         SCOPE,
    }, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    print("\n✓ Success! Add these values as GitHub Secrets:\n")
    print(f"  NETATMO_CLIENT_ID     = {client_id}")
    print(f"  NETATMO_CLIENT_SECRET = {client_secret}")
    print(f"  NETATMO_REFRESH_TOKEN = {data['refresh_token']}")
    print("\nKeep these values secret — treat them like passwords.")


if __name__ == '__main__':
    main()
