"""
Manipulation / Spam Filter — Detects fake attention, fake volume, and fake adoption.

Layer 5: Filters out manipulated signals.

Checks:
- 5.1 Twitter Spam Filter
- 5.2 Telegram Spam Filter
- 5.3 Wash Trading Filter
- 5.4 Holder Farming Filter
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum


class SpamDecision(str, Enum):
    CLEAN = "clean"
    SUSPICIOUS = "suspicious"
    SPAM = "spam"


@dataclass
class ManipulationReport:
    """Result of manipulation/spam checks."""
    decision: SpamDecision = SpamDecision.CLEAN
    flags: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)

    # Per-source spam scores (0-1, higher = more spammy)
    twitter_spam_score: float = 0.0
    telegram_spam_score: float = 0.0
    wash_trading_score: float = 0.0
    holder_farming_score: float = 0.0

    @property
    def is_clean(self) -> bool:
        return self.decision == SpamDecision.CLEAN

    @property
    def total_spam_score(self) -> float:
        return (
            self.twitter_spam_score +
            self.telegram_spam_score +
            self.wash_trading_score +
            self.holder_farming_score
        ) / 4.0


class ManipulationFilter:
    """
    Detects and filters manipulated signals across social and on-chain data.

    Each check produces a 0-1 spam score. Scores > 0.7 are flagged.
    """

    SPAM_THRESHOLD = 0.7
    SUSPICIOUS_THRESHOLD = 0.4

    async def check(self, token: dict, social_data: dict = None,
                    onchain_data: dict = None) -> ManipulationReport:
        """
        Run all manipulation checks.

        Args:
            token: Token data dict
            social_data: Recent social mentions with account-level detail
            onchain_data: Trade-level and holder-level detail
        """
        report = ManipulationReport()

        social_data = social_data or {}
        onchain_data = onchain_data or {}

        # 5.1 Twitter Spam Filter
        report.twitter_spam_score = self._check_twitter_spam(social_data.get("twitter", {}))

        # 5.2 Telegram Spam Filter
        report.telegram_spam_score = self._check_telegram_spam(social_data.get("telegram", {}))

        # 5.3 Wash Trading Filter
        report.wash_trading_score = self._check_wash_trading(token, onchain_data)

        # 5.4 Holder Farming Filter
        report.holder_farming_score = self._check_holder_farming(onchain_data)

        # Aggregate
        self._aggregate(report)

        return report

    def _check_twitter_spam(self, twitter_data: dict) -> float:
        """
        5.1 Twitter Spam Filter.

        Checks:
        - Repeated posts from same accounts
        - Low-quality new accounts
        - Engagement from bot-like accounts

        Criteria: unique accounts must rise, not only total mentions.
        """
        score = 0.0

        total_mentions = twitter_data.get("total_mentions", 0)
        unique_accounts = twitter_data.get("unique_accounts", 0)
        new_accounts = twitter_data.get("new_accounts", 0)
        avg_account_age_days = twitter_data.get("avg_account_age_days", 0)
        repeat_posters = twitter_data.get("repeat_poster_count", 0)

        if total_mentions == 0:
            return 0.0

        # Check: unique accounts should grow with mentions
        if total_mentions > 20 and unique_accounts < 3:
            score += 0.5  # Very few accounts producing many mentions
        elif total_mentions > 10 and unique_accounts < 5:
            score += 0.3

        # Check: too many new/bot accounts
        if unique_accounts > 0 and new_accounts / unique_accounts > 0.5:
            score += 0.3  # >50% new accounts

        # Check: accounts with very low age
        if avg_account_age_days < 30 and unique_accounts > 0:
            score += 0.2

        # Check: many repeat posts from same accounts
        if total_mentions > 0 and repeat_posters / total_mentions > 0.3:
            score += 0.2

        return min(score, 1.0)

    def _check_telegram_spam(self, telegram_data: dict) -> float:
        """
        5.2 Telegram Spam Filter.

        Checks:
        - Repeated contract spam
        - Few users producing most messages
        - Sudden bot-like member growth

        Criteria: unique users and new members must both increase.
        """
        score = 0.0

        total_messages = telegram_data.get("total_messages", 0)
        unique_users = telegram_data.get("unique_users", 0)
        new_members = telegram_data.get("new_members", 0)
        repeat_posts = telegram_data.get("repeat_contract_posts", 0)
        user_message_concentration = telegram_data.get("user_message_concentration", 0.0)

        if total_messages == 0:
            return 0.0

        # Check: few users producing most messages
        if total_messages > 50 and unique_users < 5:
            score += 0.5
        elif total_messages > 20 and unique_users < 3:
            score += 0.3

        # Check: high user concentration (one user = most messages)
        if user_message_concentration > 0.6:
            score += 0.3

        # Check: repeated contract spam (same contract posted many times)
        if repeat_posts > 10:
            score += 0.2

        # Check: new member spike without user diversity
        if new_members > 100 and unique_users < 10:
            score += 0.3  # Bot-like growth

        # Positive: both unique users AND new members increasing
        if unique_users >= 5 and new_members >= 5:
            score = max(score - 0.2, 0.0)

        return min(score, 1.0)

    def _check_wash_trading(self, token: dict, onchain_data: dict) -> float:
        """
        5.3 Wash Trading Filter.

        Checks:
        - Volume rising but unique buyers not rising
        - Many trades from few wallets
        - Buy/sell pattern looks artificial

        Criteria: volume must be supported by buyer growth.
        """
        score = 0.0

        volume_24h = float(token.get("volume_24h", 0))
        unique_buyers = int(onchain_data.get("unique_buyers_24h", token.get("unique_buyers_24h", 0)))
        unique_sellers = int(onchain_data.get("unique_sellers_24h", token.get("unique_sellers_24h", 0)))
        trade_count = int(onchain_data.get("trade_count_24h", token.get("trade_count_24h", 0)))
        top_wallet_share = float(onchain_data.get("top_3_wallets_volume_share", 0))

        if trade_count == 0:
            return 0.0

        # Check: high volume but low buyer count
        if volume_24h > 100_000 and unique_buyers < 10:
            score += 0.4

        # Check: trades per buyer ratio too high (few wallets doing many trades)
        if unique_buyers > 0:
            trades_per_buyer = trade_count / unique_buyers
            if trades_per_buyer > 20:
                score += 0.3

        # Check: volume concentrated in few wallets
        if top_wallet_share > 0.5:  # Top 3 wallets > 50% of volume
            score += 0.3

        # Check: buy/sell pattern — balanced ratio is natural
        if unique_buyers > 0 and unique_sellers > 0:
            ratio = unique_buyers / unique_sellers
            # Extreme ratios suggest artificial activity
            if ratio > 5 or ratio < 0.2:
                score += 0.2

        return min(score, 1.0)

    def _check_holder_farming(self, onchain_data: dict) -> float:
        """
        5.4 Holder Farming Filter.

        Checks:
        - Many tiny wallets created together
        - Wallets funded from same source
        - Holders with meaningless balances

        Criteria: meaningful holders must increase.
        """
        score = 0.0

        total_holders = int(onchain_data.get("total_holders", 0))
        meaningful_holders = int(onchain_data.get("meaningful_holders", 0))
        dust_holders = int(onchain_data.get("dust_holders", 0))
        same_source_wallets = int(onchain_data.get("same_source_wallets", 0))
        created_together = int(onchain_data.get("wallets_created_together", 0))

        if total_holders == 0:
            return 0.0

        # Check: high dust holder ratio
        if total_holders > 0:
            dust_ratio = dust_holders / total_holders
            if dust_ratio > 0.7:
                score += 0.4  # >70% dust wallets
            elif dust_ratio > 0.5:
                score += 0.2

        # Check: wallets funded from same source
        if total_holders > 0 and same_source_wallets / total_holders > 0.3:
            score += 0.3

        # Check: wallets created together (time cluster)
        if created_together > 50:
            score += 0.3

        # Check: meaningful holders vs total
        if total_holders > 100 and meaningful_holders < 20:
            score += 0.2

        return min(score, 1.0)

    def _aggregate(self, report: ManipulationReport):
        """
        Determine final spam decision based on all checks.
        """
        scores = [
            report.twitter_spam_score,
            report.telegram_spam_score,
            report.wash_trading_score,
            report.holder_farming_score,
        ]

        # Build flags
        if report.twitter_spam_score > self.SUSPICIOUS_THRESHOLD:
            report.flags.append(f"Twitter spam ({report.twitter_spam_score:.2f})")
        if report.telegram_spam_score > self.SUSPICIOUS_THRESHOLD:
            report.flags.append(f"Telegram spam ({report.telegram_spam_score:.2f})")
        if report.wash_trading_score > self.SUSPICIOUS_THRESHOLD:
            report.flags.append(f"Wash trading ({report.wash_trading_score:.2f})")
        if report.holder_farming_score > self.SUSPICIOUS_THRESHOLD:
            report.flags.append(f"Holder farming ({report.holder_farming_score:.2f})")

        # Decision
        if any(s > self.SPAM_THRESHOLD for s in scores):
            report.decision = SpamDecision.SPAM
        elif any(s > self.SUSPICIOUS_THRESHOLD for s in scores):
            report.decision = SpamDecision.SUSPICIOUS
        else:
            report.decision = SpamDecision.CLEAN

        report.evidence = {
            "spam_scores": {
                "twitter": report.twitter_spam_score,
                "telegram": report.telegram_spam_score,
                "wash_trading": report.wash_trading_score,
                "holder_farming": report.holder_farming_score,
            }
        }
