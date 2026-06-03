"""
Export Twitter cookies from your browser for use with the GraphQL scraper.

You have two options:

OPTION 1: Browser extension (easiest)
  1. Install "EditThisCookie" (Chrome) or "cookies.txt" (Firefox)
  2. Go to x.com while logged in
  3. Export cookies as JSON
  4. Save as: apps/backend/twitter_cookies.json

OPTION 2: This script (requires selenium-wire)
  pip install selenium-wire
  python export_cookies.py

The cookies file format should be a list of cookie objects:
[
  {"name": "auth_token", "value": "..."},
  {"name": "ct0", "value": "..."},
  ...
]

Or a simple dict format:
{"auth_token": "...", "ct0": "...", ...}
"""
import json
import sys

COOKIES_FILE = "twitter_cookies.json"


def validate_cookies(cookies: dict) -> bool:
    """Check if required cookies are present."""
    required = ["auth_token", "ct0"]
    missing = [c for c in required if c not in cookies]
    if missing:
        print(f"Missing required cookies: {missing}")
        return False
    return True


def convert_to_twikit_format(cookies: list[dict]) -> dict:
    """Convert browser cookie array to twikit-compatible dict format."""
    result = {}
    for cookie in cookies:
        name = cookie.get("name", "")
        value = cookie.get("value", "")
        if name and value:
            result[name] = value
            if name == "auth_token":
                result["token"] = value
    return result


def load_cookies(filepath: str = COOKIES_FILE) -> dict:
    """Load cookies from file in any common format."""
    with open(filepath) as f:
        data = json.load(f)
    
    if isinstance(data, list):
        # Array format (from EditThisCookie)
        return convert_to_twikit_format(data)
    elif isinstance(data, dict):
        # Dict format
        if "auth_token" in data:
            return data
        # Maybe it's a nested format
        for key in data:
            val = data[key]
            if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict):
                return convert_to_twikit_format(val)
            if isinstance(val, dict) and "auth_token" in val:
                return val
    raise ValueError("Unknown cookie format. Expected list of cookie objects or dict with auth_token.")


if __name__ == "__main__":
    try:
        cookies = load_cookies()
        if validate_cookies(cookies):
            print(f"✅ Cookies loaded: auth_token={'...' + cookies['auth_token'][-8:]}, ct0={'...' + cookies['ct0'][-4:]}")
            print(f"   File: {COOKIES_FILE}")
        else:
            sys.exit(1)
    except FileNotFoundError:
        print(f"❌ Cookie file not found: {COOKIES_FILE}")
        print("   Export cookies from your browser (see instructions above).")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
