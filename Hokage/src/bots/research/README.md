# Research Bot

Gathers and synthesizes market and domain intelligence.

## Pipeline position

```
User (via Hokage) → **Research** → Strategy
```

## Inputs

- User research requests (via Hokage) as `ResearchQuery`
- Prior improvement notes (via `ResearchQuery.context`)
- External data via configured `ResearchSource` adapters (`integrations/data/`)

## Outputs

- Structured `ResearchReport` → `data/research/` (when a `ReportWriter` is configured)
- Handoff artifact for Strategy Bot

## Module layout

| File | Layer | Purpose |
|------|-------|---------|
| `models.py` | Domain | `ResearchQuery`, `ResearchFinding`, `ResearchReport`, `SourceReference` |
| `interfaces.py` | Ports | `ResearchSource`, `ResearchSynthesizer`, `ReportWriter` protocols |
| `research_bot.py` | Application | `ResearchBot` orchestration, default synthesizer, JSON writer |

## Usage

```python
from pathlib import Path

from bots.research import JsonReportWriter, ResearchBot, ResearchQuery

bot = ResearchBot(
    sources=[market_data_source, news_source],
    report_writer=JsonReportWriter(Path("data/research")),
    min_relevance_score=0.4,
    max_findings=10,
)

report = bot.research(
    ResearchQuery(
        text="Impact of ECB rate decisions on EUR/USD",
        topics=("forex", "macro"),
        context={"prior_note": "Focus on 2026 policy path"},
    ),
)
```

## Extending sources

Implement the `ResearchSource` protocol in `integrations/data/` (or another integration module):

```python
class MarketDataSource:
    @property
    def source_id(self) -> str:
        return "market-data"

    @property
    def name(self) -> str:
        return "Market Data Provider"

    def search(self, query: ResearchQuery) -> tuple[ResearchFinding, ...]:
        ...
```

Inject completed adapters into `ResearchBot(sources=[...])` at runtime. The bot handles merging, filtering, deduplication, ranking, and synthesis.

## Tests

Unit tests mirror this module under `tests/unit/bots/research/`.

```bash
pytest tests/unit/bots/research/
```
