"""
Extract Twitter cookies from your browser and save them for Docker.
Run this from the HOST machine (not Docker). The Docker container will
pick up the cookies automatically via the volume mount.

Usage:
    cd apps/backend
    python extract_cookies_host.py
"""
import json
import sys

OUTPUT = "twitter_cookies.json"

try:
    import browser_cookie3
except ImportError:
    print("Installing browser-cookie3...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "browser-cookie3"])
    import browser_cookie3

BROWSERS = [
    ("Chrome", browser_cookie3.chrome),
    ("Firefox", browser_cookie3.firefox),
    ("Edge", browser_cookie3.edge),
    ("Chromium", browser_cookie3.chromium),
    ("Opera", browser_cookie3.opera),
    ("Brave", browser_cookie3.brave),
]


def main():
    print("Extracting Twitter/X cookies from browsers...")

    for name, extractor in BROWSERS:
        try:
            print(f"  {name}...", end=" ")
            cj = extractor(domain_name="x.com")
            cookies = {}
            for cookie in cj:
                if cookie.name in ("auth_token", "ct0", "twid"):
                    cookies[cookie.name] = cookie.value

            if "auth_token" in cookies and "ct0" in cookies:
                with open(OUTPUT, "w") as f:
                    json.dump(cookies, f)
                print(f"OK — {len(cookies)} cookies saved to {OUTPUT}")
                print(f"  auth_token: ...{cookies['auth_token'][-8:]}")
                return 0
            else:
                print("no Twitter session found")
        except Exception as e:
            print(f"failed ({e})")

    print("\nNo Twitter/X cookies found in any browser.")
    print("Make sure you're logged into x.com and try again.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
