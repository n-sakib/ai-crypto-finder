"""Direct Telegram scanner - checks all groups for token-bearing messages."""
import asyncio, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from telethon import TelegramClient
from telethon.tl.types import Message
from app.config import settings
import asyncpg

CA_RE = re.compile(r'\b(0x[a-fA-F0-9]{40}|[1-9A-HJ-NP-Za-km-z]{32,44})\b')
CASHTAG_RE = re.compile(r'\$([A-Za-z]{2,15})\b')
NON_ADDR = re.compile(r'^(https?|www|http|com|org|io|net|tg|me|join|channel|group|bot)$', re.I)

def extract_tokens(text):
    if not text: return set()
    refs = set()
    for m in CA_RE.finditer(text):
        addr = m.group(0)
        if not NON_ADDR.match(addr):
            refs.add(('CA', addr))
    for m in CASHTAG_RE.finditer(text):
        refs.add(('CASHTAG', '$' + m.group(1)))
    return refs

async def main():
    SESSION = 'telegram_discovery.session'
    if not os.path.exists(SESSION):
        SESSION = os.path.join(os.path.dirname(os.path.abspath('.')), SESSION)

    # Parse DATABASE_URL (may be postgresql+asyncpg://)
    db_url = settings.DATABASE_URL
    db_url = db_url.replace('postgresql+asyncpg://', 'postgresql://')
    conn = await asyncpg.connect(db_url)
    rows = await conn.fetch('SELECT name, source_id FROM telegram_sources ORDER BY name')
    await conn.close()

    groups = [(r['name'], r['source_id']) for r in rows]
    print(f"Scanning {len(groups)} groups via Telegram API...\n")

    client = TelegramClient(SESSION, settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH)
    await client.start()

    productive = []
    unproductive = []
    total_msgs = 0
    total_tokens = 0

    for i, (name, source_id) in enumerate(groups):
        if i % 10 == 0:
            print(f"  [{i}/{len(groups)}] scanning...")
        try:
            entity = await client.get_entity(source_id)
            messages = await client.get_messages(entity, limit=50)
        except Exception as e:
            unproductive.append(("ERROR", name, str(e)[:100], 0, 0))
            continue

        if not messages:
            unproductive.append(("NO_MSGS", name, "", 0, 0))
            continue

        token_msgs = 0
        token_count = 0
        for msg in messages:
            if not isinstance(msg, Message) or not msg.message:
                continue
            refs = extract_tokens(msg.message)
            if refs:
                token_msgs += 1
                token_count += len(refs)

        total_msgs += len(messages)
        total_tokens += token_count

        if token_count > 0:
            productive.append((name, len(messages), token_msgs, token_count))
        else:
            unproductive.append(("NO_TOKENS", name, "", len(messages), 0))

    await client.disconnect()

    productive.sort(key=lambda x: x[3], reverse=True)

    print()
    print("=" * 75)
    print(f"PRODUCTIVE GROUPS ({len(productive)}/{len(groups)}) - have tokens:")
    print("=" * 75)
    for name, msgs, tmsgs, tcount in productive:
        print(f"  ✅ {name}")
        print(f"     {msgs} msgs | {tmsgs} with tokens | {tcount} token refs")

    print()
    print("=" * 75)
    print(f"UNPRODUCTIVE GROUPS ({len(unproductive)}/{len(groups)}):")
    print("=" * 75)

    errors = [(n, e) for t, n, e, m, c in unproductive if t == "ERROR"]
    no_tokens = [(n, m) for t, n, e, m, c in unproductive if t == "NO_TOKENS"]
    no_msgs = [n for t, n, e, m, c in unproductive if t == "NO_MSGS"]

    if errors:
        print(f"\n  ERRORS ({len(errors)}):")
        for name, err in errors:
            print(f"  ❌ {name}")
            print(f"     {err}")
    if no_tokens:
        print(f"\n  HAS MESSAGES BUT NO TOKENS ({len(no_tokens)}):")
        for name, msgs in no_tokens[:20]:
            print(f"  ⚠️  {name}: {msgs} msgs, 0 tokens")
        if len(no_tokens) > 20:
            print(f"  ... +{len(no_tokens)-20} more")
    if no_msgs:
        print(f"\n  ZERO MESSAGES ({len(no_msgs)}):")
        for name in no_msgs[:15]:
            print(f"  — {name}")
        if len(no_msgs) > 15:
            print(f"  ... +{len(no_msgs)-15} more")

    print()
    print("=" * 75)
    print(f"SUMMARY: {len(productive)} productive | {len(unproductive)} unproductive")
    print(f"Total: {total_msgs} messages scanned | {total_tokens} token refs found")

asyncio.run(main())
