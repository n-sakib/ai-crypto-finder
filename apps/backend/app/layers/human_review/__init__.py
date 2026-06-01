"""
Human Review Layer — Prevents blind buying.

Layer 16: Provides structured due diligence checklist.

Review criteria:
- 16.1 Project Review: website, docs, team, roadmap, tokenomics
- 16.2 Market Review: chart structure, unlock schedule, market cap, exchange support, narrative fit
- 16.3 Community Review: organic vs spammy, real discussions, multiple communities
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ReviewDecision(str, Enum):
    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"
    NEEDS_MORE_INFO = "needs_more_info"


class ReviewCategory(str, Enum):
    PROJECT = "project"
    MARKET = "market"
    COMMUNITY = "community"


@dataclass
class ChecklistItem:
    """A single review checklist item."""
    category: ReviewCategory
    question: str
    status: str = "pending"  # pending, pass, fail, warning
    notes: str = ""


@dataclass
class HumanReviewReport:
    """Complete human review report."""
    decision: ReviewDecision = ReviewDecision.PENDING
    total_score: float = 0.0  # 0-100

    # Sub-scores
    project_score: float = 0.0
    market_score: float = 0.0
    community_score: float = 0.0

    # Checklist
    checklist: list[ChecklistItem] = field(default_factory=list)

    # Data
    website: str = ""
    docs_url: str = ""
    team_info: dict = field(default_factory=dict)
    roadmap_summary: str = ""
    tokenomics_summary: str = ""

    # Review metadata
    reviewer_notes: str = ""
    reviewed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_approved: bool = False

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checklist if c.status == "pass")

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checklist if c.status == "fail")

    @property
    def total_items(self) -> int:
        return len(self.checklist)


class HumanReviewLayer:
    """
    Structured human review for final watchlist approval.

    This layer is designed to be used by a human reviewer through
    a UI, but can also run automated checks where data is available.
    """

    # Default checklist (can be customized)
    DEFAULT_CHECKLIST: list[ChecklistItem] = [
        # ── 16.1 Project Review ──
        ChecklistItem(category=ReviewCategory.PROJECT,
                       question="Website exists and is functional?"),
        ChecklistItem(category=ReviewCategory.PROJECT,
                       question="Documentation / whitepaper available?"),
        ChecklistItem(category=ReviewCategory.PROJECT,
                       question="Team is identifiable (not fully anonymous)?"),
        ChecklistItem(category=ReviewCategory.PROJECT,
                       question="Roadmap exists and is realistic?"),
        ChecklistItem(category=ReviewCategory.PROJECT,
                       question="Tokenomics are reasonable (supply, distribution, inflation)?"),
        ChecklistItem(category=ReviewCategory.PROJECT,
                       question="Contract is verified on block explorer?"),

        # ── 16.2 Market Review ──
        ChecklistItem(category=ReviewCategory.MARKET,
                       question="Chart structure shows organic growth?"),
        ChecklistItem(category=ReviewCategory.MARKET,
                       question="No massive unlock events imminent?"),
        ChecklistItem(category=ReviewCategory.MARKET,
                       question="Market cap is reasonable for the stage?"),
        ChecklistItem(category=ReviewCategory.MARKET,
                       question="Has exchange support (DEX at minimum)?"),
        ChecklistItem(category=ReviewCategory.MARKET,
                       question="Fits current or emerging narrative?"),
        ChecklistItem(category=ReviewCategory.MARKET,
                       question="Liquidity is sufficient for expected trade size?"),

        # ── 16.3 Community Review ──
        ChecklistItem(category=ReviewCategory.COMMUNITY,
                       question="Community appears organic (not bot-driven)?"),
        ChecklistItem(category=ReviewCategory.COMMUNITY,
                       question="Real discussions happening (not just price hype)?"),
        ChecklistItem(category=ReviewCategory.COMMUNITY,
                       question="Active across multiple platforms (not one isolated group)?"),
        ChecklistItem(category=ReviewCategory.COMMUNITY,
                       question="Sentiment is balanced (not pure euphoria)?"),
    ]

    async def create_review(self, token_data: dict) -> HumanReviewReport:
        """
        Create a new review report with the default checklist.

        Args:
            token_data: Token information to pre-populate known fields
        """
        report = HumanReviewReport()

        # Pre-populate known data
        report.website = token_data.get("website", "")
        report.docs_url = token_data.get("docs_url", "")
        report.team_info = token_data.get("team_info", {})
        report.roadmap_summary = token_data.get("roadmap_summary", "")
        report.tokenomics_summary = token_data.get("tokenomics_summary", "")

        # Load checklist
        report.checklist = [ChecklistItem(
            category=item.category,
            question=item.question,
            status="pending",
            notes="",
        ) for item in self.DEFAULT_CHECKLIST]

        return report

    async def evaluate(self, report: HumanReviewReport) -> HumanReviewReport:
        """
        Evaluate the completed checklist and produce a decision.

        Scoring:
        - Each item: pass=2, warning=1, fail=0, pending=0
        - Max score = total_items * 2
        - Score normalized to 0-100
        """
        max_possible = report.total_items * 2 if report.total_items > 0 else 1

        # Calculate scores by category
        project_items = [c for c in report.checklist if c.category == ReviewCategory.PROJECT]
        market_items = [c for c in report.checklist if c.category == ReviewCategory.MARKET]
        community_items = [c for c in report.checklist if c.category == ReviewCategory.COMMUNITY]

        report.project_score = self._category_score(project_items)
        report.market_score = self._category_score(market_items)
        community_score = self._category_score(community_items)

        # Total
        total_score = report.project_score + report.market_score + community_score
        report.total_score = total_score  # 0-100

        # Decision
        if report.fail_count > 0:
            report.decision = ReviewDecision.REJECTED
            report.is_approved = False
        elif report.total_score >= 70 and report.pass_count >= report.total_items * 0.7:
            report.decision = ReviewDecision.APPROVED
            report.is_approved = True
        elif report.total_score >= 50:
            report.decision = ReviewDecision.NEEDS_MORE_INFO
        else:
            report.decision = ReviewDecision.PENDING

        return report

    def _category_score(self, items: list[ChecklistItem]) -> float:
        """Calculate normalized score (0-100) for a category."""
        if not items:
            return 0.0

        points = 0
        for item in items:
            if item.status == "pass":
                points += 2
            elif item.status == "warning":
                points += 1
            # fail/pending = 0

        max_points = len(items) * 2
        # Normalize to 0-100, but weight by category count relative to total
        return (points / max_points * 100) if max_points > 0 else 0.0

    async def auto_check(self, token_data: dict) -> HumanReviewReport:
        """
        Run automated checks where data is available.

        This pre-fills the checklist for human review.
        """
        report = await self.create_review(token_data)

        for item in report.checklist:
            # Auto-check items that can be validated from data
            if "website" in item.question.lower():
                if token_data.get("website"):
                    item.status = "pass"
                    item.notes = "Website found"
                else:
                    item.status = "warning"
                    item.notes = "No website found"

            elif "contract" in item.question.lower() and "verified" in item.question.lower():
                if token_data.get("contract_verified", False):
                    item.status = "pass"
                else:
                    item.status = "warning"

            elif "liquidity" in item.question.lower():
                liq = float(token_data.get("liquidity_usd", 0))
                if liq >= 500_000:
                    item.status = "pass"
                elif liq >= 100_000:
                    item.status = "warning"
                else:
                    item.status = "fail"

        return await self.evaluate(report)
