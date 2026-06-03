"""End-to-end Twitter discovery test."""
import asyncio, logging
logging.basicConfig(level=logging.INFO)

from app.core.database import async_session_factory
from app.twitter_discovery.client import TwitterClientService
from sqlalchemy import select
from app.twitter_discovery.models import TwitterCandidateToken


async def run():
    async with async_session_factory() as session:
        svc = TwitterClientService()
        print("Starting Twitter discovery...")
        stats = await svc.collect(session)
        print()
        print("=== RESULTS ===")
        print(f"Tweets stored: {stats['tweets_stored']}")
        print(f"Mentions stored: {stats['mentions_stored']}")
        print(f"Tokens discovered: {stats['tokens_discovered']}")
        
        if stats['errors']:
            print(f"Errors ({len(stats['errors'])}):")
            for e in stats['errors'][:5]:
                print(f"  - {str(e)[:200]}")
        
        tokens = (await session.execute(
            select(TwitterCandidateToken).limit(10)
        )).scalars().all()
        
        if tokens:
            print(f"\nTokens found ({len(tokens)}):")
            for t in tokens:
                print(f"  ${t.symbol} ({t.chain or '?'}): {t.token_address[:30]}...")
        else:
            print("\nNo tokens discovered yet")
        print()

asyncio.run(run())
