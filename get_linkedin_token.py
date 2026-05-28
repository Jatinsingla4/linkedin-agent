"""
get_linkedin_token.py — One-time script to get your LinkedIn access token.

Run this ONCE locally:
    python get_linkedin_token.py

It will:
  1. Open LinkedIn OAuth in your browser
  2. You log in and authorize
  3. Paste the redirect URL back here
  4. Script prints your access token and person URN
  5. Copy them into your .env file

LinkedIn tokens last 60 days. Re-run this script to refresh.
"""

import json
import os
import sys
import urllib.parse
import webbrowser

import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "").strip()
REDIRECT_URI = "http://localhost:8000/callback"  # Must match your LinkedIn app settings

SCOPES = ["openid", "profile", "w_member_social"]


def main():
    print("\n" + "=" * 60)
    print("  LinkedIn Token Generator")
    print("=" * 60)

    if not CLIENT_ID or not CLIENT_SECRET:
        print("\n❌  LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET must be set in .env")
        sys.exit(1)

    # ── Step 1: Generate auth URL ─────────────────────────────────────────
    auth_params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "state": "linkedin_agent_setup",
    }
    auth_url = "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode(auth_params)

    print("\n📋  STEP 1: Open this URL in your browser:")
    print(f"\n   {auth_url}\n")
    print("   (Attempting to open automatically...)")

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass  # If auto-open fails, user copies the URL manually

    # ── Step 2: Get the code from redirect URL ─────────────────────────────
    print("\n📋  STEP 2: After authorizing, you'll be redirected to a URL like:")
    print("   https://localhost:8000/callback?code=XXXX&state=linkedin_agent_setup")
    print("\n   The page will show an error (that's normal — localhost isn't running)")
    print("   Copy the FULL URL from your browser's address bar and paste it below:\n")

    redirect_url = input("   Paste redirect URL here: ").strip()

    if not redirect_url:
        print("❌  No URL provided")
        sys.exit(1)

    # Extract the code from the URL
    parsed = urllib.parse.urlparse(redirect_url)
    params = urllib.parse.parse_qs(parsed.query)
    code = params.get("code", [None])[0]

    if not code:
        print(f"❌  Could not find 'code' in URL: {redirect_url}")
        sys.exit(1)

    print(f"\n✅  Authorization code received: {code[:20]}...")

    # ── Step 3: Exchange code for access token ────────────────────────────
    print("\n📋  STEP 3: Exchanging code for access token...")

    token_response = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if token_response.status_code != 200:
        print(f"❌  Token exchange failed ({token_response.status_code}):")
        print(token_response.text)
        sys.exit(1)

    token_data = token_response.json()
    access_token = token_data.get("access_token")
    expires_in = token_data.get("expires_in", 0)
    expires_days = expires_in // 86400

    print(f"✅  Access token received (expires in {expires_days} days)")

    # ── Step 4: Get the person URN ────────────────────────────────────────
    print("\n📋  STEP 4: Fetching your LinkedIn person URN...")

    profile_response = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    if profile_response.status_code != 200:
        print(f"❌  Profile fetch failed: {profile_response.text}")
        sys.exit(1)

    profile = profile_response.json()
    person_id = profile.get("sub")
    person_name = profile.get("name", "Unknown")
    person_urn = f"urn:li:person:{person_id}"

    print(f"✅  Found profile: {person_name}")
    print(f"   Person URN: {person_urn}")

    # ── Step 5: Print results ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  ✅  SUCCESS! Copy these into your .env file:")
    print("=" * 60)
    print(f"\nLINKEDIN_ACCESS_TOKEN={access_token}")
    print(f"LINKEDIN_PERSON_URN={person_urn}")
    print(f"\n# Token expires in {expires_days} days")
    print("# Re-run this script when it expires\n")
    print("=" * 60)


if __name__ == "__main__":
    main()
