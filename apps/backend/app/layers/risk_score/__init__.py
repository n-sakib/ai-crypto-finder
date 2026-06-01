"""
Risk Score Layer — Separates opportunity from danger.

Layer 13: Aggregates risk across contract, liquidity, holder, and social dimensions.

Risk categories:
- 13.1 Contract Risk: honeypot, mint, tax, upgradeability
- 13.2 Liquidity Risk: low liquidity, unlocked LP, falling liquidity
- 13.3 Holder Risk: high concentration, insider-heavy, suspicious farming
- 13.4 Social Risk: bot-like attention, influencer pump, Telegram spam burst
"""

from dataclasses import dataclass, field
from typing import Optional

from app.core.models import RiskLevel


@dataclass
class RiskReport:
    """Comprehensive risk assessment."""
    total_score: float = 0.0      # 0-100 (higher = riskier)
    risk_level: RiskLevel = RiskLevel.LOW

    # Sub-scores (0-100)
    contract_risk: float = 0.0
    liquidity_risk: float = 0.0
    holder_risk: float = 0.0
    social_risk: float = 0.0

    # Details
    risk_factors: list[str] = field(default_factory=list)
    risk_evidence: dict = field(default_factory=dict)

    # Critical flags
    has_critical_risk: bool = False
    critical_reasons: list[str] = field(default_factory=list)

    @property
    def is_low(self) -> bool:
        return self.risk_level == RiskLevel.LOW

    @property
    def is_critical(self) -> bool:
        return self.risk_level == RiskLevel.CRITICAL


class RiskScoreLayer:
    """
    Calculates aggregate risk across all dimensions.

    Risk scores are 0-100 (higher = more risk).
    Critical risks (honeypot, sell block, etc.) automatically trigger CRITICAL level.
    """

    # Risk level thresholds
    LOW_THRESHOLD = 25.0
    MEDIUM_THRESHOLD = 50.0
    HIGH_THRESHOLD = 75.0

    # Weights
    WEIGHT_CONTRACT = 0.30
    WEIGHT_LIQUIDITY = 0.25
    WEIGHT_HOLDER = 0.25
    WEIGHT_SOCIAL = 0.20

    # Critical risk triggers (immediate CRITICAL regardless of score)
    CRITICAL_TRIGGERS = [
        "honeypot",
        "sell_blocked",
        "suspicious_minting",
        "rugpull_risk_high",
    ]

    async def assess(
        self,
        safety_report=None,          # Layer 4 output
        manipulation_report=None,    # Layer 5 output
        liquidity_report=None,       # Layer 9 output
        holder_data: Optional[dict] = None,
    ) -> RiskReport:
        """
        Aggregate risk from all sources.

        Args:
            safety_report: SafetyReport from Layer 4
            manipulation_report: ManipulationReport from Layer 5
            liquidity_report: LiquidityQualityScore from Layer 9
            holder_data: Holder concentration and distribution data
        """
        report = RiskReport()

        # 13.1 Contract Risk
        report.contract_risk = self._assess_contract_risk(safety_report)

        # 13.2 Liquidity Risk
        report.liquidity_risk = self._assess_liquidity_risk(safety_report, liquidity_report)

        # 13.3 Holder Risk
        report.holder_risk = self._assess_holder_risk(safety_report, holder_data)

        # 13.4 Social Risk
        report.social_risk = self._assess_social_risk(manipulation_report)

        # Check for critical triggers
        self._check_critical_triggers(report, safety_report)

        # Calculate total risk score
        if report.has_critical_risk:
            report.total_score = 100.0
            report.risk_level = RiskLevel.CRITICAL
        else:
            report.total_score = (
                report.contract_risk * self.WEIGHT_CONTRACT +
                report.liquidity_risk * self.WEIGHT_LIQUIDITY +
                report.holder_risk * self.WEIGHT_HOLDER +
                report.social_risk * self.WEIGHT_SOCIAL
            )

            # Determine risk level
            if report.total_score >= self.HIGH_THRESHOLD:
                report.risk_level = RiskLevel.HIGH
            elif report.total_score >= self.MEDIUM_THRESHOLD:
                report.risk_level = RiskLevel.MEDIUM
            else:
                report.risk_level = RiskLevel.LOW

        return report

    def _assess_contract_risk(self, safety_report) -> float:
        """
        13.1 Contract Risk.

        Factors: honeypot, mint risk, tax risk, upgradeability.
        """
        if safety_report is None:
            return 25.0  # Unknown = moderate risk

        risk = 0.0

        # Honeypot = instant high risk
        if getattr(safety_report, "is_honeypot", False):
            risk += 50.0

        # Sell blocked = instant high risk
        if getattr(safety_report, "has_sell_block", False):
            risk += 50.0

        # Mint risk
        if getattr(safety_report, "has_mint_risk", False):
            risk += 30.0

        # Tax risk
        buy_tax = getattr(safety_report, "buy_tax_pct", 0)
        sell_tax = getattr(safety_report, "sell_tax_pct", 0)
        max_tax = max(buy_tax, sell_tax)

        if max_tax > 25:
            risk += 30.0
        elif max_tax > 10:
            risk += 15.0
        elif max_tax > 5:
            risk += 5.0

        return min(risk, 100.0)

    def _assess_liquidity_risk(self, safety_report, liquidity_report) -> float:
        """
        13.2 Liquidity Risk.

        Factors: low liquidity, unlocked LP, falling liquidity.
        """
        risk = 0.0

        # From safety report
        if safety_report is not None:
            liquidity_usd = getattr(safety_report, "liquidity_usd", 0)
            if liquidity_usd < 25_000:
                risk += 40.0
            elif liquidity_usd < 100_000:
                risk += 20.0
            elif liquidity_usd < 500_000:
                risk += 10.0

            if not getattr(safety_report, "is_liquidity_locked", False):
                risk += 25.0

        # From liquidity quality report
        if liquidity_report is not None:
            trend = getattr(liquidity_report, "liquidity_trend", "")
            if trend == "falling" or trend == "falling_fast":
                risk += 20.0

        return min(risk, 100.0)

    def _assess_holder_risk(self, safety_report, holder_data: Optional[dict]) -> float:
        """
        13.3 Holder Risk.

        Factors: high concentration, insider-heavy, suspicious farming.
        """
        risk = 0.0
        holder_data = holder_data or {}

        # From safety report
        if safety_report is not None:
            top_pct = getattr(safety_report, "top_holder_pct", 0)
            if top_pct > 40:
                risk += 40.0
            elif top_pct > 25:
                risk += 20.0
            elif top_pct > 15:
                risk += 10.0

        # From holder data
        meaningful_ratio = holder_data.get("meaningful_ratio", 1.0)
        if meaningful_ratio < 0.3:
            risk += 20.0  # Most holders are dust/bots
        elif meaningful_ratio < 0.5:
            risk += 10.0

        # Suspicious farming evidence
        if holder_data.get("suspected_farming", False):
            risk += 25.0

        # Insider concentration
        if holder_data.get("insider_concentration", 0) > 0.5:
            risk += 20.0

        return min(risk, 100.0)

    def _assess_social_risk(self, manipulation_report) -> float:
        """
        13.4 Social Risk.

        Factors: bot-like attention, influencer pump, Telegram spam burst.
        """
        if manipulation_report is None:
            return 10.0  # Unknown = low-moderate

        risk = 0.0

        spam_score = getattr(manipulation_report, "total_spam_score", 0)
        risk += spam_score * 100  # Convert 0-1 to 0-100

        # Check specific flags
        flags = getattr(manipulation_report, "flags", [])
        for flag in flags:
            if "spam" in flag.lower():
                risk += 15.0
            if "wash" in flag.lower():
                risk += 20.0
            if "farming" in flag.lower():
                risk += 20.0

        return min(risk, 100.0)

    def _check_critical_triggers(self, report: RiskReport, safety_report):
        """
        Check for any critical risk triggers that override the score.

        Critical risks: honeypot, sell blocked, suspicious minting.
        """
        if safety_report is None:
            return

        if getattr(safety_report, "is_honeypot", False):
            report.has_critical_risk = True
            report.critical_reasons.append("Token is a confirmed honeypot")

        if getattr(safety_report, "has_sell_block", False):
            report.has_critical_risk = True
            report.critical_reasons.append("Selling is blocked")

        if getattr(safety_report, "has_mint_risk", False):
            report.has_critical_risk = True
            report.critical_reasons.append("Suspicious minting capability detected")
