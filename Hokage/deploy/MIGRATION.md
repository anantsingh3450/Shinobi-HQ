# Moving Hokage to a server

## Why

Between 2026-09-02 and 2026-09-22 Hokage was alive for **2 of 14 trading days**
and placed **one** trade. The host suspended itself for 17.1 days, the broker
token died, and 471 auth failures accumulated unseen.

```
Sep  2 - Sep  4   alive, traded once
Sep  4 - Sep 21   HOST SUSPENDED  "Loop gap of 24643 minutes detected"
Sep 21            woke, token dead, blind
```

Earlier the same month: a critical-battery sleep cost 7.5 hours *with a position
open*, and a silent death cost 3h39m while the watchdog reported 100.0/100.

The aim is ~20% annualised with survival as the metric. **No edge compounds at
14% uptime.** Uptime is the binding constraint — not the strategy.

## What this does NOT solve

**The daily Zerodha login.** Kite access tokens expire around 07:30 IST and
require an interactive login. A server keeps the *bot* alive; it does not keep
the *token* alive. You will still log in daily, through the server's dashboard
instead of the laptop's.

This is the single biggest remaining operational cost, and it is worth knowing
before the move rather than after.

## Migration surface: smaller than it looks

Only **one** source file is platform-specific — `src/shared/power.py`, the
Windows sleep guard — and it already returns `False` off Windows. Nothing else
in `src/` needs changing.

What does need replacing is the ops layer:

| Windows | Linux |
|---|---|
| `Start-Hokage.ps1` | `deploy/hokage.service` (auto-restart) |
| `Stop-Hokage.ps1` | `systemctl stop hokage` + stop marker |
| `Watch-Hokage.ps1` + task | cron, every 15 min |
| `Sync-Candles.ps1` + task | cron, 23:40 daily |
| `Run-WeeklyAudit.ps1` + task | cron, Friday 23:45 |
| Windows sleep guard | unnecessary — that failure class disappears |

## Steps

### 1. Decide the brain is authoritative

Once Hokage runs on the server, **the server's brain is the real one** — its
trades, chests, candle archive, snapshots. Local becomes a development copy that
**never trades**.

Skipping this gives you two Hokages with divergent histories. Given that a
running Hokage rewrites portfolio JSON from memory, that divergence is silent.

### 2. Provision

Small VPS is plenty — Hokage is I/O-bound, not CPU-bound. 2 GB RAM, 20 GB disk.

**Set the timezone to `Asia/Kolkata` before anything else:**

```bash
sudo timedatectl set-timezone Asia/Kolkata
timedatectl        # verify before continuing
```

Every window check in the codebase reads local time. A UTC box computes market
hours, the MCX session clock and the liveness window all wrong, and none of it
raises an error.

### 3. Create the user and pull the code

```bash
sudo adduser --system --group --home /opt/hokage hokage
sudo -u hokage git clone <your-remote> /opt/hokage
cd /opt/hokage
sudo -u hokage python3 -m venv .venv
sudo -u hokage .venv/bin/pip install -e .
```

`-e .` installs from `pyproject.toml` — there is no `requirements.txt` in this
repo, and `pip install -r requirements.txt` fails outright. Dependencies are
`kiteconnect`, `Flask`, `pandas`, `numpy`, `xgboost`, `scikit-learn`, `ccxt`,
`yfinance`, `psutil`, `keyring`, `pytest`.

**`xgboost` and `scikit-learn`** pull large wheels and can need build tooling on
minimal images — the one place to expect trouble.

**`keyring` is NOT a blocker**, which is worth knowing because it looks like
one on a headless box. `SecretManager.get_secret` reads the **environment first**
(`ZERODHA_API_KEY`, `ZERODHA_ACCESS_TOKEN`, …, loaded from `.env`) and only
falls back to keyring, wrapping that call in a `try/except` that logs and
returns `None`. With `.env` in place, a server with no secret service works
exactly as the laptop does.

Confirm it end to end before trusting the login flow:

```bash
sudo -u hokage .venv/bin/python tools/check_broker_session.py
```

Expect `LIVE <name>` or `EXPIRED`. Anything else — especially a keyring error —
is a problem to solve *before* migration day, not during it.

### 4. Move the brain — and leave the backups behind

```
SEND          hokage_brain/hokage.db            ~1.4 GB   the live ledger
SEND          hokage_brain/candles.db                     the compounding asset
SEND          hokage_brain/portfolio/  research/  journal/  state/
DO NOT SEND   hokage_brain/*.bak                ~2.3 GB   pre-restructure copies
DO NOT SEND   hokage_brain_archive/             ~478 MB
DO NOT SEND   logs/
```

The `.bak` files are July/August ledger snapshots. Keep them on the laptop.

**`.env` is credentials — you move it yourself, by hand.** I never touch it.

### 5. Install the service and schedules

```bash
sudo cp deploy/hokage.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hokage
sudo cp deploy/hokage-cron /etc/cron.d/hokage
sudo chmod 644 /etc/cron.d/hokage
journalctl -u hokage -f
```

### 6. Set the dashboard password

The dashboard can place trades, close positions and write the broker token.
Authentication now ships with it, and it **fails closed**: a remote request with
no password configured gets a 503, never an open terminal.

```bash
sudo -u hokage .venv/bin/python tools/ops/set_dashboard_password.py
```

Type the password at the hidden prompt, put the printed
`HOKAGE_DASHBOARD_PASSWORD_HASH=` line in `.env`, and restart. The password is
never stored, logged, or shown to anyone — only its PBKDF2 hash.

**Loopback stays exempt**, so this works untouched:

```bash
ssh -L 5000:127.0.0.1:5000 hokage@<server>
```

That is the recommended way to do the daily Kite login, and it needs no TLS.

#### If you put nginx or Caddy in front for TLS

Requests then arrive from `127.0.0.1`, so the proxy **must** send a forwarding
header — the auth layer treats the presence of `X-Forwarded-For` / `X-Real-IP`
as proof a request is *not* local, precisely so that adding TLS cannot switch
authentication off:

```nginx
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
```

Then, and **only** once TLS is genuinely in front, add `HOKAGE_DASHBOARD_HTTPS=1`
to `.env`. It marks the session cookie Secure; setting it without TLS means the
cookie is never sent back and you are locked out with no visible error.

`/healthz` stays reachable without a session for uptime checks, and reports
liveness only — nothing about the portfolio.

### 7. Run paper for a full week

Compare against what he would have done locally. **This is what proves the
migration** — not the fact that the process started.

### 8. Only then, the live canary

All safeties ON. Wire `StrictPaperModeRiskRule` first — it refuses LIVE
execution and is currently registered nowhere, which means the one guard written
specifically for this moment is not connected.

## Deploying changes afterwards

Code does **not** propagate by itself:

```bash
cd /opt/hokage && ./deploy/deploy.sh
```

It stops Hokage, pulls, runs the suite, and **refuses to restart on a red
suite** — he stays down rather than trading on code that cannot prove itself.

It stops him *first* because a running Hokage rewrites portfolio JSON from
memory. On 2026-08-26 that silently reverted the CRUDEOIL park and he traded a
parked asset all day.
