"""
Auto-extract Twitter cookies from Chrome/Firefox/Edge on startup.
Runs inside Docker — mounts the host's browser cookie database.

The Docker container needs access to the host's Chrome profile.
Add this to docker-compose.yml under the 'web' service:
    volumes:
      - ${LOCALAPPDATA}/Google/Chrome/User Data:/chrome_data:ro
"""
import json
import os
import sys

COOKIES_OUTPUT = os.environ.get("TWITTER_COOKIES_PATH", "/app/twitter_cookies.json")


def extract_chrome_cookies() -> dict | None:
    """Extract Twitter/X cookies from Chrome profile."""
    try:
        import browser_cookie3
        cj = browser_cookie3.chrome(domain_name="x.com")
        cookies = {}
        for cookie in cj:
            if cookie.name in ("auth_token", "ct0", "twid", "kdt", "lang"):
                cookies[cookie.name] = cookie.value
        
        if "auth_token" in cookies and "ct0" in cookies:
            return cookies
    except Exception as e:
        print(f"Chrome extraction failed: {e}")
    return None


def extract_firefox_cookies() -> dict | None:
    """Extract Twitter/X cookies from Firefox profile."""
    try:
        import browser_cookie3
        cj = browser_cookie3.firefox(domain_name="x.com")
        cookies = {}
        for cookie in cj:
            if cookie.name in ("auth_token", "ct0", "twid", "kdt", "lang"):
                cookies[cookie.name] = cookie.value
        
        if "auth_token" in cookies and "ct0" in cookies:
            return cookies
    except Exception as e:
        print(f"Firefox extraction failed: {e}")
    return None


def extract_edge_cookies() -> dict | None:
    """Extract Twitter/X cookies from Edge profile."""
    try:
        import browser_cookie3
        cj = browser_cookie3.edge(domain_name="x.com")
        cookies = {}
        for cookie in cj:
            if cookie.name in ("auth_token", "ct0", "twid", "kdt", "lang"):
                cookies[cookie.name] = cookie.value
        
        if "auth_token" in cookies and "ct0" in cookies:
            return cookies
    except Exception as e:
        print(f"Edge extraction failed: {e}")
    return None


def save_cookies(cookies: dict) -> bool:
    """Save cookies to the output file."""
    try:
        os.makedirs(os.path.dirname(COOKIES_OUTPUT) or ".", exist_ok=True)
        with open(COOKIES_OUTPUT, "w") as f:
            json.dump(cookies, f)
        print(f"Cookies saved to {COOKIES_OUTPUT}")
        return True
    except Exception as e:
        print(f"Failed to save cookies: {e}")
        return False


def main():
    print("Extracting Twitter cookies from browsers...")
    
    for name, extractor in [
        ("Chrome", extract_chrome_cookies),
        ("Firefox", extract_firefox_cookies),
        ("Edge", extract_edge_cookies),
    ]:
        print(f"  Trying {name}...")
        cookies = extractor()
        if cookies:
            print(f"  Found auth_token from {name}")
            if save_cookies(cookies):
                print("Done! Twitter discovery will use these cookies.")
                return 0
    
    print("No Twitter cookies found in any browser.")
    print("Make sure you're logged into x.com in Chrome/Firefox/Edge.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
