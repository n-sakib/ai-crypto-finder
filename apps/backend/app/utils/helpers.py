"""Utility functions for the AI Crypto Finder."""

import hashlib
import re
from typing import Optional


def normalize_address(address: str) -> str:
    """Normalize a blockchain address to lowercase."""
    return address.strip().lower() if address else ""


def is_valid_eth_address(address: str) -> bool:
    """Check if address is a valid Ethereum address."""
    return bool(re.match(r"^0x[a-fA-F0-9]{40}$", address))


def is_valid_solana_address(address: str) -> bool:
    """Check if address is a valid Solana address (base58, 32-44 chars)."""
    return bool(re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", address))


def is_valid_address(address: str) -> bool:
    """Check if address is a valid EVM or Solana address."""
    return is_valid_eth_address(address) or is_valid_solana_address(address)


def token_cache_key(chain: str, contract_address: str) -> str:
    """Generate a cache key for a token."""
    raw = f"{chain}:{contract_address}".lower()
    return f"token:{hashlib.md5(raw.encode()).hexdigest()}"


def clamp(value: float, min_val: float = 0.0, max_val: float = 100.0) -> float:
    """Clamp a value between min and max."""
    return max(min_val, min(max_val, value))


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Safely divide, returning default if denominator is 0."""
    return numerator / denominator if denominator != 0 else default


def calculate_velocity(current: float, baseline: float) -> float:
    """Calculate velocity ratio (current / baseline)."""
    return safe_divide(current, baseline, default=0.0)
