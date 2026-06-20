"""Concrete risk rules implementing RiskManager."""
from __future__ import annotations

from bots.execution.models import TradeDirection, TradeStatus
from bots.portfolio.models import Account
from bots.risk.interfaces import RiskManager
from bots.risk.models import RiskVerdict
from bots.strategy.models import StrategyProposal


class MaxDrawdownRiskRule(RiskManager):
    """Gating rule that stops new executions if account drawdown exceeds limits."""

    def __init__(self, max_drawdown_pct: float = 0.10) -> None:
        """Configure max drawdown limit.

        Args:
            max_drawdown_pct: Max allowed depreciation from initial balance.
                              Default is 10% (0.10).
        """
        self.max_drawdown_pct = max_drawdown_pct

    def check_order(
        self,
        account: Account,
        proposal: StrategyProposal,
        entry_price: float,
    ) -> RiskVerdict:
        """Reject if account equity drops below the drawdown limit."""
        limit = account.initial_balance * (1.0 - self.max_drawdown_pct)
        if account.equity < limit:
            return RiskVerdict(
                is_approved=False,
                max_approved_quantity=0.0,
                reason=(
                    f"Account equity ({account.equity}) is below the "
                    f"maximum drawdown limit ({limit})."
                ),
            )
        return RiskVerdict(
            is_approved=True,
            max_approved_quantity=float("inf"),
            reason="Approved",
        )


class MaxPositionSizeRiskRule(RiskManager):
    """Restricts the maximum exposure allowed for a single position."""

    def __init__(self, max_size_pct: float = 0.20) -> None:
        """Configure max position size.

        Args:
            max_size_pct: Max allowed percentage of account equity per position.
                          Default is 20% (0.20).
        """
        self.max_size_pct = max_size_pct

    def check_order(
        self,
        account: Account,
        proposal: StrategyProposal,
        entry_price: float,
    ) -> RiskVerdict:
        """Cap or reject order size if it exceeds the max allowed per position."""
        max_value = account.equity * self.max_size_pct
        max_qty = round(max_value / entry_price, 6)

        # Calculate existing quantity in this market
        existing_qty = 0.0
        prop_is_short = "short" in proposal.entry_rule.lower()
        prop_dir = TradeDirection.SHORT if prop_is_short else TradeDirection.LONG

        for pos in account.positions.values():
            if pos.market == proposal.market and pos.status == TradeStatus.OPEN:
                # If opposing trade direction, it closes/reduces size. Let it pass.
                if pos.direction != prop_dir:
                    return RiskVerdict(
                        is_approved=True,
                        max_approved_quantity=float("inf"),
                        reason="Reducing exposure",
                    )
                existing_qty += pos.quantity

        if existing_qty >= max_qty:
            return RiskVerdict(
                is_approved=False,
                max_approved_quantity=0.0,
                reason=(
                    f"Existing position quantity ({existing_qty}) already meets "
                    f"or exceeds maximum size limit ({max_qty})."
                ),
            )

        allowed_new_qty = round(max_qty - existing_qty, 6)
        return RiskVerdict(
            is_approved=True,
            max_approved_quantity=allowed_new_qty,
            reason="Approved within size limits",
        )


class LeverageRiskRule(RiskManager):
    """Prevents portfolio leverage from exceeding predefined ratios."""

    def __init__(self, max_leverage: float = 3.0) -> None:
        """Configure leverage ratio limits.

        Args:
            max_leverage: Ratio of gross exposure to equity. Default is 3.0x.
        """
        self.max_leverage = max_leverage

    def check_order(
        self,
        account: Account,
        proposal: StrategyProposal,
        entry_price: float,
    ) -> RiskVerdict:
        """Cap or reject order if it causes portfolio to exceed leverage rules."""
        current_exposure = sum(
            pos.quantity * pos.current_price
            for pos in account.positions.values()
            if pos.status == TradeStatus.OPEN
        )
        max_exposure = account.equity * self.max_leverage

        # If order reduces exposure (netting), let it pass
        prop_is_short = "short" in proposal.entry_rule.lower()
        prop_dir = TradeDirection.SHORT if prop_is_short else TradeDirection.LONG

        for pos in account.positions.values():
            if pos.market == proposal.market and pos.status == TradeStatus.OPEN:
                if pos.direction != prop_dir:
                    return RiskVerdict(
                        is_approved=True,
                        max_approved_quantity=float("inf"),
                        reason="Reducing leverage",
                    )

        available_exposure = max_exposure - current_exposure
        if available_exposure <= 0:
            return RiskVerdict(
                is_approved=False,
                max_approved_quantity=0.0,
                reason=(
                    f"Portfolio gross exposure ({current_exposure}) already meets "
                    f"or exceeds maximum leverage limit ({max_exposure})."
                ),
            )

        max_qty = round(available_exposure / entry_price, 6)
        return RiskVerdict(
            is_approved=True,
            max_approved_quantity=max_qty,
            reason="Approved within leverage limits",
        )


class CompositeRiskManager(RiskManager):
    """Evaluates multiple risk managers, returning the most restrictive result."""

    def __init__(self, rules: list[RiskManager]) -> None:
        """Initialize with list of rules.

        Args:
            rules: Concrete risk rules to run checks against.
        """
        self.rules = rules

    def check_order(
        self,
        account: Account,
        proposal: StrategyProposal,
        entry_price: float,
    ) -> RiskVerdict:
        """Run all rules, choosing the minimum approved quantity."""
        min_qty = float("inf")
        reasons = []

        for rule in self.rules:
            verdict = rule.check_order(account, proposal, entry_price)
            if not verdict.is_approved:
                return verdict  # Instant rejection

            min_qty = min(min_qty, verdict.max_approved_quantity)
            if verdict.reason != "Approved":
                reasons.append(verdict.reason)

        reason = "; ".join(reasons) if reasons else "Approved"
        return RiskVerdict(
            is_approved=True,
            max_approved_quantity=min_qty,
            reason=reason,
        )
