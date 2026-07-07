from __future__ import annotations

from bots.execution.models import TradeDirection, TradeRecord
from integrations.tax.mock_provider import SimulatedTaxProvider
from integrations.tax.models import TaxComponentType, TaxJurisdiction
from integrations.tax.store import JsonTaxLedger


def test_simulated_tax_provider_creates_indian_tax_components() -> None:
    provider = SimulatedTaxProvider()
    trade = TradeRecord(
        proposal_id="p-1",
        market="RELIANCE",
        direction=TradeDirection.LONG,
        quantity=1,
        entry_price=2950.0,
        simulated_value=2950.0,
        strategy_name="Indian Equity Strategy",
        sources_cited=("test",),
    )

    event = provider.to_tax_event(trade)

    assert event.jurisdiction is TaxJurisdiction.INDIA
    assert event.total_tax > 0
    assert {component.component_type for component in event.components} == {
        TaxComponentType.BROKERAGE,
        TaxComponentType.STT,
        TaxComponentType.GST,
        TaxComponentType.STAMP_DUTY,
        TaxComponentType.EXCHANGE_FEES,
        TaxComponentType.SEBI_TURNOVER,
    }


def test_json_tax_ledger_roundtrip(tmp_path) -> None:
    provider = SimulatedTaxProvider()
    ledger = JsonTaxLedger(tmp_path)
    trade = TradeRecord(
        proposal_id="p-1",
        market="BTC/USD",
        direction=TradeDirection.LONG,
        quantity=1,
        entry_price=65000.0,
        simulated_value=65000.0,
        strategy_name="Crypto Strategy",
        sources_cited=("test",),
    )
    event = provider.to_tax_event(trade)

    ledger.record_event(event)
    loaded = ledger.load_events()

    assert len(loaded) == 1
    assert loaded[0].trade_id == trade.trade_id
    assert loaded[0].total_tax == event.total_tax
