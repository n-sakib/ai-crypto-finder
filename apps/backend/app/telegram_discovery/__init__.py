"""
Telegram Token Discovery Service.

Monitors configured Telegram groups/channels for crypto token mentions,
extracts token identifiers, resolves them to canonical tokens, and ranks
discovered tokens by mention frequency.

Components:
    - TelegramClientService: Telethon-based message reader
    - TokenExtractor: Regex-based token identifier extraction
    - TokenResolver: Converts extracted references to canonical tokens
    - TelegramDiscoveryAggregator: Aggregates mentions and produces rankings
"""
