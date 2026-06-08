"""One-time LinkedIn OAuth helper — prints your access token + person URN.

    python -m entrypoints.get_linkedin_token

LinkedIn tokens last 60 days; re-run to refresh. Uses only the standard library
(no `requests`) and reads CLIENT_ID/SECRET directly from the environment because
the full Settings cannot load before a token exists.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
import webbrowser

from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "").strip()
REDIRECT_URI = "http://localhost:8000/callback"  # Must match your LinkedIn app settings
SCOPES = ["openid", "profile", "w_member_social"]


def _post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def _get_json(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    print("\n" + "=" * 60)
    print("  LinkedIn Token Generator")
    print("=" * 60)

    if not CLIENT_ID or not CLIENT_SECRET:
        print("\n❌  LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET must be set in .env")
        sys.exit(1)

    auth_url = "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "state": "linkedin_agent_setup",
    })

    print("\n📋  STEP 1: Open this URL and authorize:\n")
    print(f"   {auth_url}\n")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    print("\n📋  STEP 2: After authorizing you'll be redirected to a localhost URL")
    print("   (the page will error — that's fine). Paste the FULL URL below:\n")
    redirect_url = input("   Paste redirect URL here: ").strip()
    if not redirect_url:
        print("❌  No URL provided")
        sys.exit(1)

    code = urllib.parse.parse_qs(urllib.parse.urlparse(redirect_url).query).get("code", [None])[0]
    if not code:
        print(f"❌  Could not find 'code' in URL: {redirect_url}")
        sys.exit(1)
    print(f"\n✅  Authorization code received: {code[:20]}...")

    print("\n📋  STEP 3: Exchanging code for access token...")
    try:
        token_data = _post_form(
            "https://www.linkedin.com/oauth/v2/accessToken",
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
        )
    except Exception as e:
        print(f"❌  Token exchange failed: {e}")
        sys.exit(1)

    access_token = token_data.get("access_token")
    expires_days = token_data.get("expires_in", 0) // 86400
    print(f"✅  Access token received (expires in {expires_days} days)")

    print("\n📋  STEP 4: Fetching your LinkedIn person URN...")
    try:
        profile = _get_json("https://api.linkedin.com/v2/userinfo", access_token)
    except Exception as e:
        print(f"❌  Profile fetch failed: {e}")
        sys.exit(1)

    person_urn = f"urn:li:person:{profile.get('sub')}"
    print(f"✅  Found profile: {profile.get('name', 'Unknown')}")

    print("\n" + "=" * 60)
    print("  ✅  SUCCESS! Copy these into your .env file:")
    print("=" * 60)
    print(f"\nLINKEDIN_ACCESS_TOKEN={access_token}")
    print(f"LINKEDIN_PERSON_URN={person_urn}")
    print(f"\n# Token expires in {expires_days} days\n")
    print("=" * 60)


if __name__ == "__main__":
    main()
