# Tests

Test suites mirror the `src/` layout.

| Folder | Scope |
|--------|-------|
| `unit/` | Individual modules in isolation |
| `integration/` | Bot-to-bot and workflow pipelines |
| `fixtures/` | Sample strategy specs, mock data, expected outputs |

## Running tests

Requires `pip install -e ".[dev]"` from the project root.

```bash
pytest
pytest tests/unit/bots/research/
```

## Current coverage

| Module | Test path |
|--------|-----------|
| Research Bot models | `tests/unit/bots/research/test_models.py` |
| Research Bot service | `tests/unit/bots/research/test_research_bot.py` |

Shared fixtures live in `tests/conftest.py`.
