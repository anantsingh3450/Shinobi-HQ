from __future__ import annotations

from pathlib import Path
from shared.discovery.models import HorizonMode, ProgressionPhase, RiskMode
from integrations.brokers.models import ExecutionMode
from hokage.memory.profile import (
    EnvironmentConfig,
    HorizonConfig,
    RiskConfig,
    PortfolioConfig,
    TaxConfig,
    CommanderProfile,
    ProfileService
)
from hokage.memory.resolver import PathResolver


def test_config_dataclasses_defaults():
    env = EnvironmentConfig()
    assert env.mode == ExecutionMode.PAPER
    assert env.base_currency == "INR"

    hor = HorizonConfig()
    assert hor.phase == ProgressionPhase.ALPHA
    assert hor.mode == HorizonMode.FOCUSED
    assert hor.active_universe == ["CRUDE_OIL"]

    risk = RiskConfig()
    assert risk.risk_mode == RiskMode.DEFENSIVE
    assert risk.capital_preservation is True
    assert risk.max_positions == 1

    port = PortfolioConfig()
    assert port.starting_capital == 500000.0

    tax = TaxConfig()
    assert tax.tax_aware is True

    profile = CommanderProfile()
    assert profile.commander_name == "Anant"
    assert profile.commander_title == "Elder"


def test_commander_profile_serialization():
    profile = CommanderProfile(
        commander_name="AnantTest",
        commander_title="ElderTest",
        environment=EnvironmentConfig(mode=ExecutionMode.PAPER, base_currency="INR"),
        horizon=HorizonConfig(phase=ProgressionPhase.BETA, mode=HorizonMode.TACTICAL, active_universe=["GOLD", "BTC"]),
        risk=RiskConfig(risk_mode=RiskMode.DEFENSIVE, capital_preservation=False, max_positions=3),
        portfolio=PortfolioConfig(starting_capital=1000000.0),
        tax=TaxConfig(tax_aware=False)
    )

    d = profile.to_dict()
    assert d["commander_name"] == "AnantTest"
    assert d["commander_title"] == "ElderTest"
    assert d["environment"]["mode"] == "PAPER"
    assert d["horizon"]["phase"] == "BETA"
    assert d["horizon"]["mode"] == "TACTICAL"
    assert d["horizon"]["active_universe"] == ["GOLD", "BTC"]
    assert d["risk"]["risk_mode"] == "DEFENSIVE"
    assert d["risk"]["capital_preservation"] is False
    assert d["risk"]["max_positions"] == 3
    assert d["portfolio"]["starting_capital"] == 1000000.0
    assert d["tax"]["tax_aware"] is False

    restored = CommanderProfile.from_dict(d)
    assert restored.commander_name == "AnantTest"
    assert restored.commander_title == "ElderTest"
    assert restored.environment.mode == ExecutionMode.PAPER
    assert restored.horizon.phase == ProgressionPhase.BETA
    assert restored.horizon.active_universe == ["GOLD", "BTC"]
    assert restored.risk.capital_preservation is False
    assert restored.portfolio.starting_capital == 1000000.0


def test_profile_service_flow(tmp_path: Path):
    resolver = PathResolver(tmp_path)
    service = ProfileService(resolver)

    profile_file = resolver.resolve_profile_path()
    assert not profile_file.exists()

    # Getting profile bootstraps default and writes it
    prof1 = service.get_profile()
    assert prof1.commander_name == "Anant"
    assert prof1.commander_title == "Elder"
    assert profile_file.exists()

    # Modify and save
    prof1.commander_name = "NewElder"
    service.save_profile(prof1)

    # Read from service cache
    prof2 = service.get_profile()
    assert prof2.commander_name == "NewElder"

    # Reload forces disk load
    service.reload()
    prof3 = service.get_profile()
    assert prof3.commander_name == "NewElder"


def test_profile_service_reads_utf8_bom_file(tmp_path: Path):
    """A UTF-8 BOM (written by PowerShell/Notepad) must not silently discard
    the commander's profile. Regression: BOM made json.load fail and Hokage
    ran on the DEFAULT profile (1-symbol universe, 5L capital) for a session.
    """
    import json

    resolver = PathResolver(tmp_path)
    profile_file = resolver.resolve_profile_path()
    profile_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "commander_name": "Anant",
        "horizon": {"active_universe": ["CRUDE_OIL", "NIFTY"]},
        "portfolio": {"starting_capital": 50000},
    }
    profile_file.write_bytes(b"\xef\xbb\xbf" + json.dumps(payload).encode("utf-8"))

    service = ProfileService(resolver)
    prof = service.get_profile()
    assert prof.horizon.active_universe == ["CRUDE_OIL", "NIFTY"]
    assert prof.portfolio.starting_capital == 50000.0


def test_profile_starting_capital_reads_utf8_bom_file(tmp_path: Path):
    import json
    from bots.portfolio.store import profile_starting_capital

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    payload = {"portfolio": {"starting_capital": 50000}}
    (config_dir / "commander_profile.json").write_bytes(
        b"\xef\xbb\xbf" + json.dumps(payload).encode("utf-8")
    )
    assert profile_starting_capital(tmp_path) == 50000.0
