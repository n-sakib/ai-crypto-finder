"""
Run this script ONCE from your host machine (not Docker) to save Twitter cookies.
Then the Docker container will use them for all subsequent API calls.

Usage:
    cd apps/backend
    python save_twitter_cookies.py
"""
import asyncio
import sys
sys.path.insert(0, '.')

# Apply the same monkey-patch
import re as _re
_tx_mod = __import__('twikit.x_client_transaction.transaction', fromlist=['ClientTransaction'])
_tx_mod.ON_DEMAND_FILE_REGEX = _re.compile(
    r""",(\d+):["']ondemand\.s["']""", flags=(_re.VERBOSE | _re.MULTILINE))
_tx_mod.ON_DEMAND_HASH_PATTERN = r',{}:"([0-9a-f]+)"'

async def _patched_get_indices(self, home_page_response, session, headers):
    key_byte_indices = []
    response = self.validate_response(home_page_response) or self.home_page_response
    on_demand_file_index = _tx_mod.ON_DEMAND_FILE_REGEX.search(str(response)).group(1)
    regex = _re.compile(_tx_mod.ON_DEMAND_HASH_PATTERN.format(on_demand_file_index))
    filename = regex.search(str(response)).group(1)
    on_demand_file_url = f"https://abs.twimg.com/responsive-web/client-web/ondemand.s.{filename}a.js"
    on_demand_file_response = await session.request(method="GET", url=on_demand_file_url, headers=headers)
    key_byte_indices_match = _tx_mod.INDICES_REGEX.finditer(str(on_demand_file_response.text))
    for item in key_byte_indices_match:
        key_byte_indices.append(item.group(2))
    if not key_byte_indices:
        raise Exception("Couldn't get KEY_BYTE indices")
    key_byte_indices = list(map(int, key_byte_indices))
    return key_byte_indices[0], key_byte_indices[1:]

_tx_mod.ClientTransaction.get_indices = _patched_get_indices

from twikit import Client
from app.config import Settings

settings = Settings()

COOKIES_FILE = "app/layers/discovery/.twikit_cookies.json"

async def main():
    client = Client("en-US")
    
    print(f"Logging in as @{settings.TWITTER_USERNAME}...")
    await client.login(
        auth_info_1=settings.TWITTER_USERNAME,
        auth_info_2=settings.TWITTER_EMAIL or settings.TWITTER_USERNAME,
        password=settings.TWITTER_PASSWORD,
        cookies_file=COOKIES_FILE,
    )
    client.save_cookies(COOKIES_FILE)
    print(f"✅ Cookies saved to {COOKIES_FILE}")
    print("Docker container will now use these cookies automatically.")

asyncio.run(main())
