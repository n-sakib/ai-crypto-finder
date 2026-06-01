"""
Safety Layer — Removes obviously dangerous tokens.

Layer 4: Checks contract safety, liquidity, volume, and holder concentration.

Checks:
- 4.1 Liquidity Check (tiered minimums)
- 4.2 Volume Check (minimum daily volume)
- 4.3 Holder Concentration (top holder limits)
- 4.4 Contract Safety (honeypot, mint, sell block, tax)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from app.config import settings
from app.core.models import AgeBucket


class SafetyDecision(str, Enum):
    PASS = "pass"
    WARN = "warn"
    REJECT = "reject"


@dataclass
class SafetyReport:
    """Safety check result for a single token."""
    decision: SafetyDecision = SafetyDecision.PASS
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Detailed check results
    liquidity_check: bool = True
    volume_check: bool = True
    holder_concentration_check: bool = True
    contract_check: bool = True

    # Metrics
    liquidity_usd: float = 0.0
    volume_24h: float = 0.0
    top_holder_pct: float = 0.0
    is_honeypot: bool = False
    has_sell_block: bool = False
    has_mint_risk: bool = False
    is_liquidity_locked: bool = False
    buy_tax_pct: float = 0.0
    sell_tax_pct: float = 0.0

    @property
    def is_safe(self) -> bool:
        return self.decision != SafetyDecision.REJECT

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


class SafetyLayer:
    """
    Applies safety checks to filter out dangerous tokens.

    Checks are tiered by age bucket:
    - New launches: $25k minimum liquidity
    - Growing: $100k minimum liquidity
    - Mature: $500k minimum liquidity
    """

    # Tiered liquidity minimums
    MIN_LIQUIDITY: dict[AgeBucket, float] = {
        AgeBucket.NEW_LAUNCH: 25_000,
        AgeBucket.YOUNG: 50_000,
        AgeBucket.GROWING: 100_000,
        AgeBucket.MATURE: 500_000,
    }

    # Known non-threatening wallets (burn, LP, CEX, bridge, contracts)
    KNOWN_NON_THREATENING = {
        "burn", "lp", "cex", "bridge", "contract", "locker",
        "multisig", "treasury", "foundation", "team_vesting",
    }

    async def check(self, token: dict, age_bucket: AgeBucket = AgeBucket.NEW_LAUNCH) -> SafetyReport:
        """
        Run all safety checks on a token.

        Returns SafetyReport with pass/warn/reject decision.
        """
        report = SafetyReport()

        # 4.1 Liquidity Check (tiered)
        self._check_liquidity(token, age_bucket, report)

        # 4.2 Volume Check
        self._check_volume(token, report)

        # 4.3 Holder Concentration
        self._check_holder_concentration(token, report)

        # 4.4 Contract Safety
        await self._check_contract(token, report)

        # Determine final decision
        self._finalize_decision(report)

        return report

    def _check_liquidity(self, token: dict, age_bucket: AgeBucket, report: SafetyReport):
        """
        4.1 Liquidity Check — Tiered minimums by age.

        - New Launch: $25k
        - Young: $50k
        - Growing: $100k
        - Mature: $500k
        """
        liquidity = float(token.get("liquidity_usd", 0))
        min_liq = self.MIN_LIQUIDITY.get(age_bucket, 100_000)
        report.liquidity_usd = liquidity

        if liquidity < min_liq:
            report.liquidity_check = False
            report.reasons.append(
                f"Liquidity ${liquidity:,.0f} below {age_bucket.value} minimum ${min_liq:,.0f}"
            )

    def _check_volume(self, token: dict, report: SafetyReport):
        """
        4.2 Volume Check — Minimum daily volume.
        """
        volume = float(token.get("volume_24h", 0))
        report.volume_24h = volume

        if volume < settings.MIN_VOLUME_24H:
            report.volume_check = False
            report.reasons.append(
                f"24h volume ${volume:,.0f} below minimum ${settings.MIN_VOLUME_24H:,.0f}"
            )

    def _check_holder_concentration(self, token: dict, report: SafetyReport):
        """
        4.3 Holder Concentration Check.

        Reject if top holder > 40% (critical).
        Warn if top holder > 25%.
        Ignore known burn, LP, CEX, bridge, and contract wallets.

        In production: fetch holder distribution from on-chain or DEXScreener.
        """
        top_pct = float(token.get("top_holder_pct", 0))
        top_holder_is_known = token.get("top_holder_type", "") in self.KNOWN_NON_THREATENING
        report.top_holder_pct = top_pct

        if top_holder_is_known:
            # Known non-threatening wallet — don't penalize
            return

        if top_pct > settings.MAX_TOP_HOLDER_CRITICAL:
            report.holder_concentration_check = False
            report.reasons.append(
                f"Top holder owns {top_pct:.1f}% (critical threshold: {settings.MAX_TOP_HOLDER_CRITICAL}%)"
            )
        elif top_pct > settings.MAX_TOP_HOLDER_PCT:
            report.holder_concentration_check = False
            report.warnings.append(
                f"Top holder owns {top_pct:.1f}% (warning threshold: {settings.MAX_TOP_HOLDER_PCT}%)"
            )

    async def _check_contract(self, token: dict, report: SafetyReport):
        """
        4.4 Contract Safety Check.

        Reject: honeypot, selling blocked, suspicious minting.
        Penalize: unlocked liquidity, extreme buy/sell tax.

        In production: use contract scanners (GoPlus, Honeypot.is, TokenSniffer)
        or Web3 to check contract code.
        """
        contract_address = token.get("contract_address", "")

        # Honeypot check
        is_honeypot = token.get("is_honeypot", False)
        report.is_honeypot = is_honeypot

        if is_honeypot:
            report.contract_check = False
            report.reasons.append("Token is a suspected honeypot")

        # Sell block check
        has_sell_block = token.get("has_sell_block", False)
        report.has_sell_block = has_sell_block

        if has_sell_block:
            report.contract_check = False
            report.reasons.append("Selling appears to be blocked")

        # Mint risk
        has_mint_risk = token.get("has_mint_risk", False)
        report.has_mint_risk = has_mint_risk

        if has_mint_risk:
            report.contract_check = False
            report.reasons.append("Suspicious minting capability detected")

        # Liquidity lock
        is_locked = token.get("is_liquidity_locked", False)
        report.is_liquidity_locked = is_locked

        if not is_locked:
            report.warnings.append("Liquidity is not locked")

        # Tax checks
        buy_tax = float(token.get("buy_tax_pct", 0))
        sell_tax = float(token.get("sell_tax_pct", 0))
        report.buy_tax_pct = buy_tax
        report.sell_tax_pct = sell_tax

        if buy_tax > 10:
            report.warnings.append(f"High buy tax: {buy_tax:.1f}%")
        if sell_tax > 10:
            report.warnings.append(f"High sell tax: {sell_tax:.1f}%")
        if sell_tax > 25 or buy_tax > 25:
            report.contract_check = False
            report.reasons.append(f"Extreme tax: buy {buy_tax:.1f}% / sell {sell_tax:.1f}%")

    def _finalize_decision(self, report: SafetyReport):
        """
        Determine final decision based on all checks.

        REJECT: any contract safety failure (honeypot, sell block, mint risk)
        WARN: liquidity, volume, or concentration issues
        PASS: all checks clear
        """
        if not report.contract_check:
            report.decision = SafetyDecision.REJECT
        elif not report.liquidity_check or not report.volume_check or not report.holder_concentration_check:
            report.decision = SafetyDecision.WARN
        else:
            report.decision = SafetyDecision.PASS
