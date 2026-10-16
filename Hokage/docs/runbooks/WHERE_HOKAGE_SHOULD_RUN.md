# Where Hokage should run

*Written 2026-10-16. Every number here was measured on this machine or read
off an official page; the sources are at the bottom.*

## The short version

**Do not move him to Oracle's free tier. I recommended that, and I was wrong.**
Oracle reclaims an Always Free instance that is idle, and Hokage measures
**0.77% of one core**. He would be flagged and deleted.

**The static IP is not blocking anything today.** Zerodha's rule applies to
**order placement only**. Hokage is paper-only and places no real orders;
market data, historical candles, orderbook and positions are served to any IP.
That rule becomes binding on the day he goes live, not before.

So the host question today is not compliance. It is **uptime**, and the two
faults that actually cost uptime are both fixable on this laptop for nothing.

---

## 1. What he actually needs

Measured on PID 18648, up 52.6 hours:

| | measured |
|---|---|
| CPU | **24.4 CPU-minutes in 52.6 hours = 0.77% of one core** |
| Memory | 98 MB working set, 429 MB private |
| Threads | 33 |
| Brain on disk | 107 MB total (`hokage.db` 41 MB, `candles.db` 6 MB) |

This is a very small program. 1 vCPU, 2 GB RAM and 20 GB of disk is
comfortable, with room for the candle and VIX archives to grow for years.

## 2. Why the free tier fails, and it is our own fault

Oracle's Always Free terms reclaim an instance that, over a 7-day window, has
95th-percentile **CPU below 20%**, **network below 20%**, and (on the ARM A1
shapes) **memory below 20%**.

Hokage fails all three by a wide margin. He is a 0.77%-of-a-core process
holding 429 MB. **And the reason he is that quiet is work we did on purpose**
— the SSE health thread was burning 22.7% of a core for zero subscribers and
we took it to 0.9%. The optimisation that made him efficient is the thing that
would get him deleted.

Burning CPU to look busy enough to keep a free VM is not engineering. Rule it
out.

Two further changes since I last recommended it:

- The Always Free ARM allowance was **cut from 4 OCPU / 24 GB to 2 OCPU /
  12 GB** (reported effective 2026-06-15, with no announcement; the official
  page now reads 2/12).
- Over-provisioning past the allowance disables and then deletes instances
  after 30 days.

## 3. What is actually breaking, measured

### DNS — 144 failures, 44 distinct minutes, across 10-14 and 10-15

```
api.telegram.org   79
api.kite.trade     65
[Errno 11001] getaddrinfo failed
```

**Both hosts fail in the same minutes.** That is not a Zerodha outage and not
a Telegram outage — it is name resolution on this box. The box has three
serial dependencies for a DNS answer, any one of which produces exactly this:

- the Wi-Fi link (`Realtek RTL8821CE`, 433 Mbps — there is no wired link up)
- Tailscale, which is running and puts `100.201.30.24` on the Ethernet
  interface's resolver list
- the router at `192.168.31.1`, forwarding to the ISP

The Wi-Fi adapter has **one** DNS server configured: the router. A blip
anywhere in that chain takes out every hostname at once.

**What it has cost so far: nothing measurable.** No trade was missed to it —
there were no entries on either day. The Telegram alerts that failed are now
deferred and flushed rather than dropped. So this is a reliability risk that
has not yet become a loss, which is the right time to deal with it.

### The 7.5-hour suspension

`BATACTIONCRIT = 2` (hibernate) at `BATLEVELCRIT = 7%`, on **both** AC and DC.
That is the setting that suspended him mid-session with an open position and
no stops running.

Idle sleep and idle hibernate are already disabled (`STANDBYIDLE = 0`,
`HIBERNATEIDLE = 0`), so the only path to a suspension is the battery
genuinely reaching 7% — a power cut long enough to drain it. No setting
prevents that; only a UPS does.

## 4. What to do, in order

**These are changes to your machine, so they are yours to make — I have not
touched any of them.**

1. **Add a second DNS server to the Wi-Fi adapter.** One resolver with no
   fallback is the single cheapest fault here. `1.1.1.1` and `8.8.8.8` as
   secondary/tertiary alongside the router. Free, two minutes, removes the
   most frequent measured failure.
2. **Prefer a wired connection** if the router is reachable by cable. Wi-Fi
   plus a Tailscale DNS proxy is two moving parts where one would do.
3. **A UPS**, if power cuts are common where the machine sits. This is the
   only thing that addresses the 7% hibernate, and it is cheaper than a year
   of VPS.
4. **Leave the host move until the live canary.** On that day the static IP
   stops being optional and the host becomes mandatory anyway — and by then
   there will be a measured reason to pick one, because `live_readiness` will
   have to pass first.

## 5. When you do move: what it costs and what moves

### Cost, stated against the actual plan

A 1 vCPU / 2 GB instance in an India region runs roughly **₹500–1,200 a
month**. Third-party comparisons disagree, so check the provider's own
checkout page before committing; AWS Lightsail Mumbai, Vultr Mumbai and
Contabo are the usual candidates, and DigitalOcean's India region is Bangalore
rather than Mumbai.

Put that against the plan — ₹30,000 seed, ₹10,000 a month, 20% annualised:

- 20% a year is **1.53% a month**. On ₹30,000 that is about **₹460 a month**.
- **A ₹600/month host costs more than the seed earns.**
- The account has to reach roughly **₹39,000** before its return covers the
  host. On the contribution schedule that is about month two.

That is not an argument against the host. It is an argument for not paying for
it a moment before it does something — which, today, it does not.

### What moves across

| | notes |
|---|---|
| `HOKAGE_BRAIN_ROOT` | the whole point of the 10-09 resolver work; set it and everything follows |
| `hokage.db`, `candles.db` | 48 MB. Copy with Hokage **stopped** — a running Hokage rewrites portfolio state from memory |
| `.env` | credentials. **You move this, not me** |
| Scheduled tasks | `Sync-Candles.ps1` (now also the VIX archive), the liveness probe, `job_watch` |
| Launcher | `Start-Hokage.ps1` / `Stop-Hokage.ps1` and the stop marker — all PowerShell; a Linux host needs systemd units instead |
| Login | still yours. The callback URL and the Kite app's redirect have to point at the new host |

The last row is the one people forget: the daily Zerodha login is interactive
and stays interactive. A VPS does not make Hokage self-logging-in.

---

## Sources

- [Zerodha — Static IP for Kite Connect](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/static-ip)
  (order placement only, from 1 April 2026; up to 2 IPs; one change per
  calendar week)
- [Oracle — Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm)
  (2 OCPU / 12 GB A1; idle reclaim thresholds; 200 GB block storage)
- [InfoQ — Oracle Cloud free tier limits](https://infoq.com/news/2026/07/oracle-cloud-free-tier-limits/)
  (the 4/24 → 2/12 cut, reported unannounced)
- Everything under "measured" came from this machine on 2026-10-16:
  `Get-Process 18648`, `powercfg /query`, `Get-DnsClientServerAddress`, and
  `logs/hokage_1791960101_err.log`.
