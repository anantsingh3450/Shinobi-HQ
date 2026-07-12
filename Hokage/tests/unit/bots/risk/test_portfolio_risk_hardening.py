"""Unit tests for Phase 6.6C Portfolio Risk Hardening rules.

Tests verify:
- SectorConcentrationRiskRule: sector cap enforcement, unknown-sector passthrough,
  remaining headroom scaling
- PortfolioBetaRiskRule: weighted beta computation, cap enforcement, empty portfolio
- DynamicVaRSizingRule: VaR sizing at 95% confidence, rejection when budget exhausted
- ExpectedShortfallRiskRule: ES cap enforcement, ES > VaR for same position
- CompositeRiskManager integration: all four rules chained together
"""
from __future__ import annotations

from unittest.mock import MagicMock

from bots.execution.models import TradeDirection, TradeStatus
from bots.portfolio.models import Account, Position
from bots.risk.rules import (
    SectorConcentrationRiskRule,
    PortfolioBetaRiskRule,
    DynamicVaRSizingRule,
    ExpectedShortfallRiskRule,
    CompositeRiskManager,
)
from bots.strategy.models import StrategyProposal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_account(equity: float = 100_000.0, positions: dict | None = None) -> Account:
    """Create a simple Account with the given equity and optional open positions."""
    acc = Account(
        account_id="test_paper",
        initial_balance=equity,
        cash=equity,
        currency="INR",
    )
    if positions:
        acc.positions = positions
    return acc


def _make_position(
    market: str,
    quantity: float,
    current_price: float,
    direction: TradeDirection = TradeDirection.LONG,
) -> Position:
    # NOTE: Do NOT use spec=Position here. Position uses __slots__, which causes
    # MagicMock to ignore attribute assignments — pos.quantity would remain a
    # MagicMock instead of the float we assign. Without spec, assignments work.
    #
    # Also explicitly set unrealized_pnl and realized_pnl to 0.0. The
    # Account.equity property sums p.unrealized_pnl for all open positions;
    # a MagicMock unrealized_pnl would poison account.equity and every
    # downstream computation in the risk rules (e.g. max_sector_value).
    pos = MagicMock()
    pos.market = market
    pos.quantity = quantity
    pos.current_price = current_price
    pos.entry_price = current_price
    pos.direction = direction
    pos.status = TradeStatus.OPEN
    pos.unrealized_pnl = 0.0
    pos.realized_pnl = 0.0
    return pos


def _make_proposal(market: str, quantity: float = 10.0, entry_rule: str = "long") -> StrategyProposal:
    proposal = MagicMock(spec=StrategyProposal)
    proposal.market = market
    proposal.quantity = quantity
    proposal.entry_rule = entry_rule
    return proposal


# ---------------------------------------------------------------------------
# SectorConcentrationRiskRule tests
# ---------------------------------------------------------------------------

class TestSectorConcentrationRiskRule:

    def test_approves_when_no_sector_exposure(self) -> None:
        """First position in a sector is always approved."""
        rule = SectorConcentrationRiskRule(max_sector_pct=0.40)
        account = _make_account(equity=100_000.0)
        proposal = _make_proposal("TCS")
        verdict = rule.check_order(account, proposal, entry_price=3500.0)

        assert verdict.is_approved is True
        assert verdict.max_approved_quantity > 0

    def test_rejects_when_sector_cap_reached(self) -> None:
        """Rejects when total IT sector exposure meets the cap."""
        rule = SectorConcentrationRiskRule(max_sector_pct=0.40)
        # IT sector already holds ₹40,000 on ₹100,000 equity (exactly at cap)
        infy_pos = _make_position("INFY", quantity=100.0, current_price=400.0)  # ₹40,000
        account = _make_account(equity=100_000.0, positions={"p1": infy_pos})
        proposal = _make_proposal("TCS")  # also IT sector
        verdict = rule.check_order(account, proposal, entry_price=3500.0)

        assert verdict.is_approved is False
        assert "Sector concentration limit reached" in verdict.reason
        assert "IT" in verdict.reason

    def test_approves_within_sector_cap_and_caps_quantity(self) -> None:
        """Approves with capped quantity when partial headroom remains."""
        rule = SectorConcentrationRiskRule(max_sector_pct=0.40)
        # IT already at ₹20,000 → ₹20,000 headroom remains out of ₹40,000 cap
        infy_pos = _make_position("INFY", quantity=50.0, current_price=400.0)  # ₹20,000
        account = _make_account(equity=100_000.0, positions={"p1": infy_pos})
        proposal = _make_proposal("TCS")
        verdict = rule.check_order(account, proposal, entry_price=1000.0)

        assert verdict.is_approved is True
        # Remaining headroom = ₹20,000 / ₹1,000 = 20 units
        assert abs(verdict.max_approved_quantity - 20.0) < 0.01

    def test_unknown_sector_passes_through(self) -> None:
        """Assets not in the sector map are approved without sector cap."""
        rule = SectorConcentrationRiskRule(max_sector_pct=0.40)
        account = _make_account(equity=100_000.0)
        proposal = _make_proposal("XYZSTOCK")  # not in any sector map
        verdict = rule.check_order(account, proposal, entry_price=100.0)

        assert verdict.is_approved is True
        assert "sector not mapped" in verdict.reason.lower()

    def test_cross_sector_does_not_interfere(self) -> None:
        """An IT position does not affect the BANKING sector cap."""
        rule = SectorConcentrationRiskRule(max_sector_pct=0.40)
        infy_pos = _make_position("INFY", quantity=100.0, current_price=400.0)  # ₹40,000 IT
        account = _make_account(equity=100_000.0, positions={"p1": infy_pos})
        proposal = _make_proposal("HDFCBANK")  # BANKING sector
        verdict = rule.check_order(account, proposal, entry_price=1600.0)

        assert verdict.is_approved is True  # BANKING headroom is still full

    def test_custom_sector_map_is_respected(self) -> None:
        """A custom sector_map overrides the built-in defaults."""
        custom_map = {"INFY": "CUSTOM_SECTOR", "TCS": "CUSTOM_SECTOR"}
        rule = SectorConcentrationRiskRule(max_sector_pct=0.10, sector_map=custom_map)
        # Custom sector already maxed: ₹10,000 out of ₹10,000 (10% of ₹100k)
        infy_pos = _make_position("INFY", quantity=25.0, current_price=400.0)  # ₹10,000
        account = _make_account(equity=100_000.0, positions={"p1": infy_pos})
        proposal = _make_proposal("TCS")
        verdict = rule.check_order(account, proposal, entry_price=3500.0)

        assert verdict.is_approved is False


# ---------------------------------------------------------------------------
# PortfolioBetaRiskRule tests
# ---------------------------------------------------------------------------

class TestPortfolioBetaRiskRule:

    def test_approves_first_position_with_moderate_beta(self) -> None:
        """First position with beta well below cap is approved."""
        rule = PortfolioBetaRiskRule(max_portfolio_beta=1.50)
        account = _make_account(equity=100_000.0)
        proposal = _make_proposal("TCS")  # β=0.85
        verdict = rule.check_order(account, proposal, entry_price=3500.0)

        assert verdict.is_approved is True
        assert "0.850" in verdict.reason

    def test_rejects_when_beta_cap_breached(self) -> None:
        """Adding a high-beta crypto position that pushes portfolio beta above cap."""
        rule = PortfolioBetaRiskRule(max_portfolio_beta=1.20)
        # Existing: ₹80,000 in INFY (β=0.90) → current weighted beta = 0.90
        infy_pos = _make_position("INFY", quantity=200.0, current_price=400.0)  # ₹80,000
        account = _make_account(equity=100_000.0, positions={"p1": infy_pos})
        # Adding BTC (β=1.50) with large exposure
        proposal = _make_proposal("BTCUSDT", quantity=5.0)
        entry_price = 3_000_000.0 / 5  # total ₹3,000,000 → β pull is extreme
        verdict = rule.check_order(account, proposal, entry_price=entry_price)

        assert verdict.is_approved is False
        assert "beta cap breached" in verdict.reason.lower()

    def test_approves_low_beta_diversification(self) -> None:
        """Adding GOLD (β=0.10) to a moderate-beta portfolio is approved."""
        rule = PortfolioBetaRiskRule(max_portfolio_beta=1.50)
        infy_pos = _make_position("INFY", quantity=200.0, current_price=400.0)  # ₹80,000, β=0.90
        account = _make_account(equity=100_000.0, positions={"p1": infy_pos})
        proposal = _make_proposal("GOLD", quantity=10.0)
        verdict = rule.check_order(account, proposal, entry_price=5000.0)  # ₹50,000 GOLD

        assert verdict.is_approved is True

    def test_empty_portfolio_always_approved(self) -> None:
        """With no open positions, any trade is approved (no portfolio to push beta)."""
        rule = PortfolioBetaRiskRule(max_portfolio_beta=0.50)  # tight cap
        account = _make_account(equity=100_000.0)
        proposal = _make_proposal("TSLA", quantity=1.0)  # β=1.80
        verdict = rule.check_order(account, proposal, entry_price=25000.0)

        # Single position: new_portfolio_beta = TSLA_beta = 1.80 > 0.50 → reject
        assert verdict.is_approved is False

    def test_default_beta_used_for_unknown_symbol(self) -> None:
        """Unknown symbols use default_beta (1.0) for the calculation."""
        rule = PortfolioBetaRiskRule(max_portfolio_beta=2.0, default_beta=0.50)
        account = _make_account(equity=100_000.0)
        proposal = _make_proposal("XYZUNKNOWN", quantity=1.0)
        verdict = rule.check_order(account, proposal, entry_price=100.0)

        # Unknown → β=0.50, which is < 2.0 cap
        assert verdict.is_approved is True


# ---------------------------------------------------------------------------
# DynamicVaRSizingRule tests
# ---------------------------------------------------------------------------

class TestDynamicVaRSizingRule:

    def test_returns_quantity_within_var_budget(self) -> None:
        """VaR rule returns max quantity that fits within the budget."""
        rule = DynamicVaRSizingRule(max_var_pct=0.02, confidence=0.95)
        account = _make_account(equity=100_000.0)  # VaR budget = ₹2,000
        proposal = _make_proposal("INFY")  # annual vol 24%, daily ≈ 1.51%
        verdict = rule.check_order(account, proposal, entry_price=1500.0)

        assert verdict.is_approved is True
        assert verdict.max_approved_quantity > 0
        # VaR per unit = 1500 × (0.24/√252) × 1.645
        daily_vol = 0.24 / (252 ** 0.5)
        var_per_unit = 1500.0 * daily_vol * 1.645
        expected_max_qty = round(2000.0 / var_per_unit, 6)
        assert abs(verdict.max_approved_quantity - expected_max_qty) < 0.01

    def test_rejects_when_budget_exhausted(self) -> None:
        """Rejects when the VaR budget is exhausted (very small equity, very high vol)."""
        rule = DynamicVaRSizingRule(max_var_pct=0.001, confidence=0.99)  # tiny budget
        account = _make_account(equity=100.0)  # VaR budget = ₹0.10
        proposal = _make_proposal("BTCUSDT")  # annual vol 80%, daily ≈ 5.04%
        # At price ₹40,00,000 per BTC: VaR per unit far exceeds ₹0.10
        verdict = rule.check_order(account, proposal, entry_price=4_000_000.0)

        assert verdict.is_approved is False
        assert "VaR budget exhausted" in verdict.reason

    def test_high_vol_asset_gets_smaller_size(self) -> None:
        """High-volatility asset produces a smaller approved quantity than low-vol asset."""
        rule = DynamicVaRSizingRule(max_var_pct=0.02, confidence=0.95)
        account = _make_account(equity=100_000.0)
        proposal_it = _make_proposal("INFY")    # 24% annual vol
        proposal_crypto = _make_proposal("BTCUSDT")  # 80% annual vol

        verdict_it = rule.check_order(account, proposal_it, entry_price=1500.0)
        verdict_crypto = rule.check_order(account, proposal_crypto, entry_price=1500.0)

        assert verdict_it.is_approved is True
        assert verdict_crypto.is_approved is True
        # Crypto has higher vol → smaller max qty for same price and budget
        assert verdict_crypto.max_approved_quantity < verdict_it.max_approved_quantity

    def test_custom_vol_map_is_respected(self) -> None:
        """A custom vol_map overrides built-in default volatilities."""
        custom_vol_map = {"CUSTOM": 0.10}
        rule = DynamicVaRSizingRule(max_var_pct=0.02, confidence=0.95, vol_map=custom_vol_map)
        account = _make_account(equity=100_000.0)
        proposal = _make_proposal("CUSTOM")
        verdict = rule.check_order(account, proposal, entry_price=100.0)

        assert verdict.is_approved is True
        daily_vol = 0.10 / (252 ** 0.5)
        expected_max_qty = round(2000.0 / (100.0 * daily_vol * 1.645), 6)
        assert abs(verdict.max_approved_quantity - expected_max_qty) < 0.01


# ---------------------------------------------------------------------------
# ExpectedShortfallRiskRule tests
# ---------------------------------------------------------------------------

class TestExpectedShortfallRiskRule:

    def test_approves_within_es_budget(self) -> None:
        """ES rule approves trade with quantity within ES budget."""
        rule = ExpectedShortfallRiskRule(max_es_pct=0.03, confidence=0.95)
        account = _make_account(equity=100_000.0)  # ES budget = ₹3,000
        proposal = _make_proposal("INFY")
        verdict = rule.check_order(account, proposal, entry_price=1500.0)

        assert verdict.is_approved is True
        assert verdict.max_approved_quantity > 0

    def test_rejects_when_es_budget_exhausted(self) -> None:
        """Rejects when ES budget is exhausted by a very high-vol asset."""
        rule = ExpectedShortfallRiskRule(max_es_pct=0.001, confidence=0.99)
        account = _make_account(equity=100.0)  # ES budget ≈ ₹0.10
        proposal = _make_proposal("BTCUSDT")
        verdict = rule.check_order(account, proposal, entry_price=4_000_000.0)

        assert verdict.is_approved is False
        assert "Expected Shortfall cap breached" in verdict.reason

    def test_es_budget_is_larger_than_var_budget(self) -> None:
        """ES quantity cap is always smaller than the VaR quantity cap for same params.

        Because ES > VaR at any confidence level, the ES rule is more conservative
        and will approve a smaller maximum position size.
        """
        var_rule = DynamicVaRSizingRule(max_var_pct=0.02, confidence=0.95)
        es_rule = ExpectedShortfallRiskRule(max_es_pct=0.02, confidence=0.95)
        account = _make_account(equity=100_000.0)
        proposal = _make_proposal("INFY")
        entry_price = 1500.0

        var_verdict = var_rule.check_order(account, proposal, entry_price)
        es_verdict = es_rule.check_order(account, proposal, entry_price)

        assert var_verdict.is_approved is True
        assert es_verdict.is_approved is True
        # ES is more conservative → smaller max quantity
        assert es_verdict.max_approved_quantity < var_verdict.max_approved_quantity

    def test_es_at_99_confidence_more_conservative_than_95(self) -> None:
        """ES at 99% confidence is tighter (smaller max qty) than at 95%."""
        es_95 = ExpectedShortfallRiskRule(max_es_pct=0.03, confidence=0.95)
        es_99 = ExpectedShortfallRiskRule(max_es_pct=0.03, confidence=0.99)
        account = _make_account(equity=100_000.0)
        proposal = _make_proposal("INFY")
        entry_price = 1500.0

        verdict_95 = es_95.check_order(account, proposal, entry_price)
        verdict_99 = es_99.check_order(account, proposal, entry_price)

        assert verdict_95.is_approved is True
        assert verdict_99.is_approved is True
        assert verdict_99.max_approved_quantity < verdict_95.max_approved_quantity


# ---------------------------------------------------------------------------
# CompositeRiskManager integration with Phase 6.6C rules
# ---------------------------------------------------------------------------

class TestPhase66CCompositeIntegration:

    def test_all_four_rules_pass_conservative_trade(self) -> None:
        """A conservatively sized trade in a low-risk asset clears all four rules."""
        rules = [
            SectorConcentrationRiskRule(max_sector_pct=0.50),
            PortfolioBetaRiskRule(max_portfolio_beta=2.0),
            DynamicVaRSizingRule(max_var_pct=0.05),
            ExpectedShortfallRiskRule(max_es_pct=0.08),
        ]
        composite = CompositeRiskManager(rules)
        account = _make_account(equity=100_000.0)
        proposal = _make_proposal("GOLD", quantity=2.0)

        verdict = composite.check_order(account, proposal, entry_price=5000.0)
        assert verdict.is_approved is True

    def test_sector_cap_blocks_trade_before_reaching_var_rules(self) -> None:
        """CompositeRiskManager returns the first rejection immediately (fast-fail)."""
        sector_rule = SectorConcentrationRiskRule(max_sector_pct=0.01)  # tiny cap
        beta_rule = PortfolioBetaRiskRule(max_portfolio_beta=2.0)
        var_rule = DynamicVaRSizingRule(max_var_pct=0.10)
        es_rule = ExpectedShortfallRiskRule(max_es_pct=0.15)

        composite = CompositeRiskManager([sector_rule, beta_rule, var_rule, es_rule])
        # Fill the IT sector cap (1% of ₹100k = ₹1,000 → only ₹1,000 allowed)
        infy_pos = _make_position("INFY", quantity=5.0, current_price=200.0)  # ₹1,000
        account = _make_account(equity=100_000.0, positions={"p1": infy_pos})
        proposal = _make_proposal("TCS")  # IT sector → sector cap reached

        verdict = composite.check_order(account, proposal, entry_price=3500.0)
        assert verdict.is_approved is False
        assert "Sector concentration" in verdict.reason

    def test_composite_returns_minimum_quantity_from_all_rules(self) -> None:
        """The composite returns the minimum max_approved_quantity across all passing rules."""
        # Use very tight VaR budget to force a small approved qty
        rules = [
            SectorConcentrationRiskRule(max_sector_pct=0.50),
            PortfolioBetaRiskRule(max_portfolio_beta=2.0),
            DynamicVaRSizingRule(max_var_pct=0.001),   # tight → small qty
            ExpectedShortfallRiskRule(max_es_pct=0.10),  # loose → large qty
        ]
        composite = CompositeRiskManager(rules)
        account = _make_account(equity=100_000.0)
        proposal = _make_proposal("GOLD", quantity=5.0)

        verdict = composite.check_order(account, proposal, entry_price=5000.0)
        assert verdict.is_approved is True
        # VaR rule is tightest → composite qty ≤ VaR qty
        var_rule = DynamicVaRSizingRule(max_var_pct=0.001)
        var_verdict = var_rule.check_order(account, proposal, entry_price=5000.0)
        assert verdict.max_approved_quantity <= var_verdict.max_approved_quantity + 0.01
