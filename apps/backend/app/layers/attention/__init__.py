"""
Attention Layer — Measures real attention acceleration across 4 platforms.

Layer 3: Tracks social velocity across platforms.

Metrics:
- 3.1 X Velocity: mentions, unique accounts, engagement
- 3.2 Telegram Velocity: messages, unique users, new members
- 3.3 Reddit Velocity: mentions, comments, upvotes
- 3.4 Coingecko Velocity: trending rank, news mentions
"""

from dataclasses import dataclass, field
from typing import Optional

from app.core.models import AgeBucket


@dataclass
class AttentionScore:
    """Attention scoring result for a token."""
    total_score: float = 0.0  # 0-100

    # Per-platform scores
    twitter_score: float = 0.0
    telegram_score: float = 0.0
    coingecko_score: float = 0.0
    reddit_score: float = 0.0

    # Raw metrics
    twitter_mentions: int = 0
    twitter_unique_accounts: int = 0
    twitter_engagement: int = 0
    telegram_messages: int = 0
    telegram_unique_users: int = 0
    telegram_new_members: int = 0
    coingecko_trending_rank: int = 0
    coingecko_news_count: int = 0
    reddit_mentions: int = 0
    reddit_comments: int = 0
    reddit_upvotes: int = 0

    # Velocity ratios
    twitter_velocity: float = 0.0
    telegram_velocity: float = 0.0
    coingecko_velocity: float = 0.0
    reddit_velocity: float = 0.0

    # Per-source interesting flags
    twitter_interesting: bool = False
    telegram_interesting: bool = False
    coingecko_interesting: bool = False
    reddit_interesting: bool = False

    # Flags
    is_interesting: bool = False
    is_strong: bool = False
    has_telegram_signal: bool = False

    @property
    def level(self) -> str:
        if self.is_strong:
            return "strong"
        if self.is_interesting:
            return "interesting"
        return "low"


class AttentionLayer:
    """Calculates attention velocity across X, Telegram, Coingecko, and Reddit."""

    INTERESTING_TWITTER = 3.0
    STRONG_TWITTER = 5.0
    INTERESTING_TELEGRAM = 3.0
    STRONG_TELEGRAM = 5.0
    INTERESTING_COINGECKO = 2.0
    STRONG_COINGECKO = 4.0
    INTERESTING_REDDIT = 2.0
    STRONG_REDDIT = 4.0

    WEIGHT_TWITTER = 0.25
    WEIGHT_TELEGRAM = 0.25
    WEIGHT_COINGECKO = 0.25
    WEIGHT_REDDIT = 0.25

    async def score(
        self,
        token_id: str,
        twitter_data: Optional[dict] = None,
        telegram_data: Optional[dict] = None,
        coingecko_data: Optional[dict] = None,
        reddit_data: Optional[dict] = None,
        baselines: Optional[dict] = None,
    ) -> AttentionScore:
        """Calculate attention score from X, Telegram, Coingecko, and Reddit."""
        result = AttentionScore()
        twitter_data = twitter_data or {}
        telegram_data = telegram_data or {}
        coingecko_data = coingecko_data or {}
        reddit_data = reddit_data or {}
        baselines = baselines or {}

        self._score_twitter(result, twitter_data, baselines)
        self._score_telegram(result, telegram_data, baselines)
        self._score_coingecko(result, coingecko_data, baselines)
        self._score_reddit(result, reddit_data, baselines)

        result.total_score = (
            result.twitter_score * self.WEIGHT_TWITTER
            + result.telegram_score * self.WEIGHT_TELEGRAM
            + result.coingecko_score * self.WEIGHT_COINGECKO
            + result.reddit_score * self.WEIGHT_REDDIT
        )

        if result.total_score >= 70:
            result.is_strong = True
            result.is_interesting = True
        elif result.total_score >= 40:
            result.is_interesting = True

        result.twitter_interesting = result.twitter_velocity >= self.INTERESTING_TWITTER
        result.telegram_interesting = result.telegram_velocity >= self.INTERESTING_TELEGRAM
        result.coingecko_interesting = result.coingecko_velocity >= self.INTERESTING_COINGECKO
        result.reddit_interesting = result.reddit_velocity >= self.INTERESTING_REDDIT

        return result

    def _score_twitter(self, result: AttentionScore, data: dict, baselines: dict):
        """
        6.1 Twitter Velocity.

        Metrics: mentions, unique accounts, engagement.
        Interesting: > 3x baseline. Strong: > 5x baseline.
        """
        result.twitter_mentions = data.get("mentions", 0)
        result.twitter_unique_accounts = data.get("unique_accounts", 0)
        result.twitter_engagement = data.get("engagement", 0)

        baseline = baselines.get("avg_twitter_mentions", 1.0)
        current = max(result.twitter_mentions, 1)

        if baseline > 0:
            velocity = current / baseline
        else:
            velocity = 0.0

        result.twitter_velocity = velocity

        # Score: map velocity to 0-100
        # 3x -> 40, 5x -> 70, 10x -> 100
        if velocity >= 10:
            result.twitter_score = 100.0
        elif velocity >= self.STRONG_TWITTER:
            result.twitter_score = 70.0 + (velocity - 5) * 6  # 70-100
        elif velocity >= self.INTERESTING_TWITTER:
            result.twitter_score = 40.0 + (velocity - 3) * 15  # 40-70
        elif velocity >= 1.5:
            result.twitter_score = 20.0 + (velocity - 1.5) * 13  # 20-40
        else:
            result.twitter_score = velocity * 13  # 0-20

        result.twitter_score = min(result.twitter_score, 100.0)

    def _score_telegram(self, result: AttentionScore, data: dict, baselines: dict):
        """
        6.2 Telegram Velocity.

        Metrics: messages, unique users, new members.
        Interesting: > 3x baseline. Strong: > 5x baseline.

        Strongest signal: new members + unique users rising together.
        """
        result.telegram_messages = data.get("messages", 0)
        result.telegram_unique_users = data.get("unique_users", 0)
        result.telegram_new_members = data.get("new_members", 0)

        baseline = baselines.get("avg_telegram_messages", 1.0)
        current = max(result.telegram_messages, 1)

        if baseline > 0:
            velocity = current / baseline
        else:
            velocity = 0.0

        result.telegram_velocity = velocity

        # Base score from velocity
        if velocity >= 10:
            result.telegram_score = 100.0
        elif velocity >= self.STRONG_TELEGRAM:
            result.telegram_score = 70.0 + (velocity - 5) * 6
        elif velocity >= self.INTERESTING_TELEGRAM:
            result.telegram_score = 40.0 + (velocity - 3) * 15
        elif velocity >= 1.5:
            result.telegram_score = 20.0 + (velocity - 1.5) * 13
        else:
            result.telegram_score = velocity * 13

        # Bonus: new members + unique users rising together (strongest signal)
        if result.telegram_unique_users >= 5 and result.telegram_new_members >= 5:
            result.has_telegram_signal = True
            result.telegram_score = min(result.telegram_score * 1.25, 100.0)

        result.telegram_score = min(result.telegram_score, 100.0)

    def _score_coingecko(self, result: AttentionScore, data: dict, baselines: dict):
        """
        Coingecko Velocity — trending rank & news mentions.

        Lower trending rank = hotter. More news mentions = more attention.
        """
        result.coingecko_trending_rank = data.get("trending_rank", 999)
        result.coingecko_news_count = data.get("news_count", 0)

        baseline = baselines.get("avg_coingecko_mentions", 1.0)
        current = max(result.coingecko_news_count, 1)

        velocity = current / baseline if baseline > 0 else 0.0
        result.coingecko_velocity = velocity

        # Score from news velocity + trending bonus
        if velocity >= 8:
            news_score = 100.0
        elif velocity >= self.STRONG_COINGECKO:
            news_score = 70.0 + (velocity - 4) * 7.5
        elif velocity >= self.INTERESTING_COINGECKO:
            news_score = 40.0 + (velocity - 2) * 15
        elif velocity >= 1.2:
            news_score = 20.0 + (velocity - 1.2) * 25
        else:
            news_score = velocity * 16

        # Trending bonus: top 100 = +15, top 10 = +30
        trending_bonus = 0
        if result.coingecko_trending_rank <= 10:
            trending_bonus = 30
        elif result.coingecko_trending_rank <= 100:
            trending_bonus = 15

        result.coingecko_score = min(news_score + trending_bonus, 100.0)

    def _score_reddit(self, result: AttentionScore, data: dict, baselines: dict):
        """Reddit Velocity — mentions, comments, upvotes. Confirmation signal."""
        result.reddit_mentions = data.get("mentions", 0)
        result.reddit_comments = data.get("comments", 0)
        result.reddit_upvotes = data.get("upvotes", 0)

        baseline = baselines.get("avg_reddit_mentions", 1.0)
        current = max(result.reddit_mentions, 1)
        velocity = current / baseline if baseline > 0 else 0.0
        result.reddit_velocity = velocity

        if velocity >= 8:
            result.reddit_score = 100.0
        elif velocity >= self.STRONG_REDDIT:
            result.reddit_score = 70.0 + (velocity - 4) * 7.5
        elif velocity >= self.INTERESTING_REDDIT:
            result.reddit_score = 40.0 + (velocity - 2) * 15
        elif velocity >= 1.2:
            result.reddit_score = 20.0 + (velocity - 1.2) * 25
        else:
            result.reddit_score = velocity * 16

        result.reddit_score = min(result.reddit_score, 100.0)
