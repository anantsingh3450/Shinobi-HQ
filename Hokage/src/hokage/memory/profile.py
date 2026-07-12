"""Commander Profile model and storage service.

Enforces the persistent commander profile as Hokage's single source of truth.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from shared.discovery.models import HorizonMode, ProgressionPhase, RiskMode
from integrations.brokers.models import ExecutionMode
from hokage.memory.resolver import PathResolver


@dataclass
class EnvironmentConfig:
    """Environment execution and base settings."""
    mode: ExecutionMode = ExecutionMode.PAPER
    base_currency: str = "INR"

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "base_currency": self.base_currency,
        }

    @classmethod
    def from_dict(cls, d: dict) -> EnvironmentConfig:
        mode_val = d.get("mode", "PAPER").upper()
        # Map string to ExecutionMode enum
        try:
            mode_enum = ExecutionMode(mode_val)
        except ValueError:
            mode_enum = ExecutionMode.PAPER

        return cls(
            mode=mode_enum,
            base_currency=d.get("base_currency", "INR")
        )


@dataclass
class HorizonConfig:
    """Horizon Expansion Doctrine and universe scanning configurations."""
    phase: ProgressionPhase = ProgressionPhase.ALPHA
    mode: HorizonMode = HorizonMode.FOCUSED
    active_universe: list[str] = field(default_factory=lambda: ["CRUDE_OIL"])

    def to_dict(self) -> dict:
        return {
            "phase": self.phase.value,
            "mode": self.mode.value,
            "active_universe": self.active_universe,
        }

    @classmethod
    def from_dict(cls, d: dict) -> HorizonConfig:
        phase_val = d.get("phase", "ALPHA").upper()
        mode_val = d.get("mode", "FOCUSED").upper()
        try:
            phase_enum = ProgressionPhase(phase_val)
        except ValueError:
            phase_enum = ProgressionPhase.ALPHA
        try:
            mode_enum = HorizonMode(mode_val)
        except ValueError:
            mode_enum = HorizonMode.FOCUSED

        return cls(
            phase=phase_enum,
            mode=mode_enum,
            active_universe=d.get("active_universe", ["CRUDE_OIL"])
        )


@dataclass
class RiskConfig:
    """Sizing, position caps, and capital preservation parameters."""
    risk_mode: RiskMode = RiskMode.DEFENSIVE
    capital_preservation: bool = True
    max_positions: int = 1

    def to_dict(self) -> dict:
        return {
            "risk_mode": self.risk_mode.value,
            "capital_preservation": self.capital_preservation,
            "max_positions": self.max_positions,
        }

    @classmethod
    def from_dict(cls, d: dict) -> RiskConfig:
        mode_val = d.get("risk_mode", "DEFENSIVE").upper()
        try:
            mode_enum = RiskMode(mode_val)
        except ValueError:
            mode_enum = RiskMode.DEFENSIVE

        return cls(
            risk_mode=mode_enum,
            capital_preservation=bool(d.get("capital_preservation", True)),
            max_positions=int(d.get("max_positions", 1))
        )


@dataclass
class PortfolioConfig:
    """Portfolio capital allocation settings."""
    starting_capital: float = 500000.0

    def to_dict(self) -> dict:
        return {
            "starting_capital": self.starting_capital,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PortfolioConfig:
        return cls(
            starting_capital=float(d.get("starting_capital", 500000.0))
        )


@dataclass
class TaxConfig:
    """Tax intelligence configurations."""
    tax_aware: bool = True

    def to_dict(self) -> dict:
        return {
            "tax_aware": self.tax_aware,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TaxConfig:
        return cls(
            tax_aware=bool(d.get("tax_aware", True))
        )


@dataclass
class CommanderProfile:
    """Unified Commander Profile containing all settings and operational states."""
    commander_name: str = "Anant"
    commander_title: str = "Elder"
    environment: EnvironmentConfig = field(default_factory=EnvironmentConfig)
    horizon: HorizonConfig = field(default_factory=HorizonConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)
    tax: TaxConfig = field(default_factory=TaxConfig)

    def to_dict(self) -> dict:
        return {
            "commander_name": self.commander_name,
            "commander_title": self.commander_title,
            "environment": self.environment.to_dict(),
            "horizon": self.horizon.to_dict(),
            "risk": self.risk.to_dict(),
            "portfolio": self.portfolio.to_dict(),
            "tax": self.tax.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> CommanderProfile:
        return cls(
            commander_name=d.get("commander_name", "Anant"),
            commander_title=d.get("commander_title", "Elder"),
            environment=EnvironmentConfig.from_dict(d.get("environment", {})),
            horizon=HorizonConfig.from_dict(d.get("horizon", {})),
            risk=RiskConfig.from_dict(d.get("risk", {})),
            portfolio=PortfolioConfig.from_dict(d.get("portfolio", {})),
            tax=TaxConfig.from_dict(d.get("tax", {})),
        )


class ProfileService:
    """Access and persistence layer for the Commander Profile config."""

    def __init__(self, resolver: PathResolver) -> None:
        self.resolver = resolver
        self.profile_path = resolver.resolve_profile_path()
        self._cached_profile: CommanderProfile | None = None
        self._last_mtime: float = 0.0

    def get_profile(self) -> CommanderProfile:
        """Get the current profile. Hot reloads from disk if file modified."""
        if self.profile_path.exists():
            try:
                mtime = self.profile_path.stat().st_mtime
                if self._cached_profile is not None and mtime == self._last_mtime:
                    return self._cached_profile
                self._last_mtime = mtime
            except Exception:
                pass
        else:
            default_profile = CommanderProfile()
            self.save_profile(default_profile)
            self._cached_profile = default_profile
            return default_profile

        try:
            with open(self.profile_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            profile = CommanderProfile.from_dict(data)
            self._cached_profile = profile
            return profile
        except Exception:
            # Fallback to cached profile if available, otherwise default
            if self._cached_profile is not None:
                return self._cached_profile
            default_profile = CommanderProfile()
            self._cached_profile = default_profile
            return default_profile

    def save_profile(self, profile: CommanderProfile) -> None:
        """Write the profile to commander_profile.json atomically."""
        try:
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.profile_path.with_suffix(".json.tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(profile.to_dict(), f, indent=2)
                f.flush()
                import os
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
            temp_path.replace(self.profile_path)
            self._cached_profile = profile
            try:
                self._last_mtime = self.profile_path.stat().st_mtime
            except Exception:
                pass
        except Exception as e:
            self._cached_profile = profile
            raise e

    def reload(self) -> None:
        """Invalidate the cache to force a reload from disk."""
        self._cached_profile = None
        self._last_mtime = 0.0
