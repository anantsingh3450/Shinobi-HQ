"""JSON persistence store for Account records.

Allows saving and restoring simulated account states to disk.
"""
from __future__ import annotations

import json
from pathlib import Path

from bots.portfolio.models import Account


class JsonPortfolioStore:
    """Persists Account state as a JSON file under a configured directory."""

    def __init__(self, output_directory: Path) -> None:
        """Initialize the store.

        Args:
            output_directory: Directory folder (e.g. data/portfolio/).
                              Created automatically on first save.
        """
        self._output_directory = output_directory
        
        # Determine if SQLite is active
        from hokage.memory.resolver import PathResolver
        from shared.persistence.sqlite_engine import SqliteStorageEngine
        from shared.persistence.sqlite_stores import SqlitePortfolioStore
        
        resolver = PathResolver(output_directory.parent)
        if SqliteStorageEngine.is_active(resolver):
            engine = SqliteStorageEngine(resolver)
            self._delegate = SqlitePortfolioStore(engine)
        else:
            self._delegate = None

    @property
    def output_directory(self) -> Path:
        """Target folder path."""
        return self._output_directory

    def account_file(self, account_id: str) -> Path:
        """Get the filepath for a specific account identifier.

        Args:
            account_id: The ID of the account.

        Returns:
            Path object pointing to the JSON file.
        """
        # Ensure name is filesystem friendly
        clean_id = "".join(c for c in account_id if c.isalnum() or c in ("-", "_"))
        return self._output_directory / f"account_{clean_id}.json"

    def save_account(self, account: Account) -> None:
        """Persist an Account record.

        Args:
            account: The Account state object to save.
        """
        if self._delegate is not None:
            self._delegate.save_account(account)
            return

        self._output_directory.mkdir(parents=True, exist_ok=True)
        filepath = self.account_file(account.account_id)
        with filepath.open("w", encoding="utf-8") as fh:
            json.dump(account.to_dict(), fh, indent=2)

    def load_account(self, account_id: str, default_balance: float = 10000.0) -> Account:
        """Load a persisted Account state, or initialize a default if none exists.

        Args:
            account_id:      The ID of the account to load.
            default_balance: Balance to use if initializing a new account.

        Returns:
            The loaded or newly initialized Account state.
        """
        if self._delegate is not None:
            return self._delegate.load_account(account_id, default_balance)

        filepath = self.account_file(account_id)
        if not filepath.exists():
            # Initialize new account
            return Account(
                account_id=account_id,
                initial_balance=default_balance,
                cash=default_balance,
            )

        with filepath.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return Account.from_dict(data)
