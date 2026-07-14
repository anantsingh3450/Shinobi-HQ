# Hokage Strategy Dojo — Plan (v1, 2026-07-14)

Commander vision: multiple book-derived strategies compete on live paper data;
evidence promotes winners, demotes losers; time/regime specialists emerge;
Hokage evolves weekly until it surpasses reference traders. NO code from this
document is implemented until the commander approves.

---

## Part 1 — Audit of existing strategies vs the books

Current portfolio (`strategy/portfolio.py`): AutoTrend (trend following),
MacroBreakout (volatility breakout), MeanReversion (range trading).

Findings:
1. **Lineage confirmed for exits, not entries.** The exit ladder (Assassin
   stop, Connoisseur scale-out) is directly Lee Freeman-Shor's *Art of
   Execution* tribes — kill losses fast, drink winners slowly. This part is
   book-faithful and battle-worthy. The ENTRY rules however are generic
   one-liners ("enter when momentum indicators align") — they predate the
   books and carry no testable edge definition.
2. **Fabricated track records.** Seed strategies ship with invented stats
   (win_rate 65%, trade_count 10, expectancy 500 — trades that never
   happened). Kelly sizing and strategy selection consume these. Must be
   zeroed before the dojo opens; every number must be earned on live paper.
3. **Psychology layer already present.** *Trading in the Zone* (Douglas) and
   five other books exist as knowledge modules feeding conviction/anti-pattern
   checks. The new books add mechanical RULES, which is what's missing.

## Part 2 — Six candidates from the books

Each spec below is precise enough to code without interpretation. All trade
via the options router (ATM CE/PE buy) with every existing gate unchanged.

### S1 — Wyckoff Spring/Upthrust Reversal (*Trades About to Happen*, ch. 5-6)
- Detect trading range: >= 20 bars (15m) with high/low band containing >= 80%
  of closes.
- **Spring (long):** bar penetrates range low by <= 30% of range height, then
  closes back INSIDE the range within 2 bars, with the reclaim bar closing in
  its top third. Volume on penetration NOT expanding beyond 1.5x average
  (supply vacuum), or expanding with immediate reversal (absorption).
- **Upthrust (short):** mirror at range high.
- Stop: beyond the spring/upthrust extreme (the "danger point" — smallest
  risk). Target: opposite side of range, then trail.
- Context filter: springs in a larger uptrend only, upthrusts in a downtrend
  only (book: "springs in an uptrend have a higher percentage of success").
- Expected habitat: SIDEWAYS regime, mid-session.

### S2 — Open-Conviction Drive (*Mind Over Markets*, ch. 4 open types)
- Classify the first 30 minutes (09:15-09:45 NSE / 09:00-09:30 MCX):
  **Open-Drive** = one-directional move from the bell, no return to open
  price, opening outside the previous day's value area.
- Entry: with the drive direction on the first pullback that holds above/below
  the open price. No entry if open is inside prior value area (that's an
  Open-Auction = balance day, S3's habitat).
- Stop: the open price (drive invalidated if recrossed). Exit: EOD square-off
  or Connoisseur ladder.
- Expected habitat: trend days, opening session. Complements the existing
  Opening Bell Observation window (entry fires only after 09:30 per current
  protocol — protocol wins).

### S3 — Value-Area Rotation (*Mind Over Markets*, value-area rule)
- Compute previous day's value area (70% of volume around POC) from 15m data.
- Entry (the 80% rule): price opens outside the value area, then re-enters
  and holds 2 consecutive 15m closes inside — target is a rotation across the
  full value area to the far edge. Long from below, short from above (short =
  buy PE via router).
- Stop: back outside the entry edge. Time stop: exit if target unreached by
  14:30.
- Expected habitat: SIDEWAYS/balance days, NIFTY primarily.

### S4 — Regime-Filtered Time-Series Momentum (Chan, *Algorithmic Trading*)
- Classic momentum with the book's two hard warnings encoded: transaction
  costs in the backtest gate, and regime dependence.
- Entry: 20-bar return > +1 ATR AND existing volume gate confirms (>= 1.5x
  14-day avg) AND regime classifier says trending. Short mirror.
- Exit: momentum decay (10-bar return flips sign) or Assassin/Connoisseur.
- This is AutoTrend/MacroBreakout done honestly — if it can't beat them in
  shadow, the old two retire into it.

### S5 — IV-Percentile Premium Guard (Natenberg, *Option Volatility & Pricing*) — OVERLAY, not a strategy
- Hokage BUYS options; buying when implied volatility is rich means paying
  for movement that must exceed the inflated premium. Guard: track India VIX
  percentile over trailing 60 sessions.
  - VIX percentile > 80: block new option buys (premium too rich) unless the
    signal is an Open-Drive trend day (movement pays for itself).
  - VIX percentile < 20: favorable buying window — no change to gates, but
    logged so the scoreboard can verify the edge.
- Applies to ALL strategies' option execution. Cheap to compute from the
  already-mapped NSE:INDIA VIX quote.

### S6 — Triple-Barrier Meta-Label Gatekeeper (Lopez de Prado, *Advances in Financial ML*) — EVOLUTION BACKBONE
- Every signal (taken or shadow) gets labeled by the triple-barrier method:
  profit barrier / stop barrier (both ATR-scaled) / time barrier. First touch
  = label.
- Weekly, a simple meta-model (start: logistic regression on regime, VIX
  bucket, time-of-day, strategy id, spread, volume ratio) learns
  P(signal succeeds). It never GENERATES signals — it sizes/filters them
  (meta-labeling: separate the side decision from the bet decision).
- Until 100+ labeled signals exist, it runs in observe-only mode.
- This replaces gut-feel weekly review with statistics and directly powers
  the "special strategy for particular times" goal: the model's feature
  importances ARE the time/regime specialization map.

## Part 3 — The Arena (evaluation discipline)

1. All six enter SHADOW mode — full logging, zero capital. Production
   continues on current strategies meanwhile.
2. Scoreboard buckets: strategy x regime x session-third x VIX band.
   **Minimum 30 trades per bucket before any conclusion.**
3. Ladder: shadow (30+ trades, expectancy > 0, PF > 1.3) -> PROBATION (real
   paper, half allocation) -> 2 clean weeks -> ACTIVE. Rolling 20-trade
   negative expectancy = auto-demotion. Max 6 ACTIVE at once.
4. Time-specialists get scoped schedules (e.g., S3 only 10:30-14:30) once
   their winning bucket is statistically separable.
5. No-trade scoreboard: every refused signal tracked with would-have-been
   outcome (triple-barrier labels make this free).
6. Weekly evolution report (Sunday): scoreboard, promotions/demotions, one
   mutation proposal per losing strategy, commander approves mutations.

## Part 4 — Order of work (after commander approval)

1. Zero fabricated seed stats (prerequisite for honest Kelly).
2. S5 VIX guard (smallest, protects capital immediately).
3. Triple-barrier labeler + scoreboard schema (S6 foundation — everything
   else reports into it).
4. S2 + S3 (Market Profile pair — day-structure data source shared).
5. S1 Wyckoff (needs range-detection utility).
6. S4 momentum (mostly exists; needs honest rewrite).
7. Meta-model weekly job (after 100+ labels accumulated).

Estimated: items 1-3 one day; 4-5 two days; 6-7 across the following week.
Books' psychology (Douglas discipline, Freeman-Shor execution) stays encoded
where it already lives — exits and conviction gates.

## Part 5 — Rival benchmark (pending)

Commander will supply a document describing a live trading bot. Hokage's
scoreboard gains a BENCHMARK row: same-day P&L comparison, win rate, and
drawdown vs the rival's published results. Surpass criteria defined after
reading the document.
