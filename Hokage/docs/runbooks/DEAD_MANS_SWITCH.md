# The dead man's switch — setup

*Three steps, about five minutes. Everything in this file is yours to do: I
do not create accounts, and I never handle the ping URL.*

## What it is and why it is shaped this way

Between **2026-09-23 06:27** and **2026-10-09 18:26** Hokage did not exist.
Sixteen days, eleven market sessions, no process, no decisions, no log file.
You were travelling and the laptop was off.

Nothing reported it. The external liveness probe exists for exactly this —
it was written after a 3h39m death Hokage reported as "Health Score
100/100", on the principle that *his own watchdog dies with him*. But it is a
Windows scheduled task on the same laptop, and every Hokage task runs as
`LogonType=Interactive`. It is independent of the **process**, not of the
**machine**, and the machine is what went away.

A probe inside the failure domain it watches cannot report that domain
failing. So the signal is inverted:

```
every 10 minutes   Hokage POSTs a heartbeat out, with a one-line status
clean shutdown     Hokage POSTs to {url}/fail saying why
anything else      silence — and the service alarms
```

The watch no longer has to reach him. He has to keep reaching it.

---

## Step 1 — create the check

Any dead-man's-switch service works. [healthchecks.io](https://healthchecks.io)
has a free tier that is more than enough; Cronitor and Better Stack are
equivalent.

Create one check with:

| setting | value | why |
|---|---|---|
| name | `Hokage` | |
| period | **15 minutes** | he pings every 10, so one lost ping is not a missed deadline |
| grace | **30 minutes** | absorbs a DNS outage twice as long as the worst measured here (13 min on 10-15) and a full restart |

Then add the alert channel you will actually see on your phone — email at
minimum, and Telegram or push if the service offers it. An alarm you do not
see is the same as no alarm.

## Step 2 — put the URL in `.env`

The check gives you a ping URL. Add one line to `.env`:

```
HOKAGE_DEADMAN_URL=https://hc-ping.com/<your-uuid>
```

**Treat it as a credential.** Anyone holding it can forge a heartbeat, which
would switch this watch off without anything appearing wrong. Hokage never
logs it — only the hostname ever reaches a log line — and it must not go into
a commit, a screenshot or a chat message, including to me.

## Step 3 — restart Hokage

```bash
powershell -File "C:\Users\anant\OneDrive\Documents\AI PROJECT\AI COMMAND CENTRE\Hokage\Stop-Hokage.ps1"
```

```bash
powershell -File "C:\Users\anant\OneDrive\Documents\AI PROJECT\AI COMMAND CENTRE\Hokage\Start-Hokage.ps1"
```

You should see, once, at boot:

```
Dead man's switch armed: heartbeat to hc-ping.com every 600s.
```

and the check should go green within a minute. **If it is not configured you
will see a warning instead**, once per boot, naming the eleven lost sessions
— that line is deliberate and it should not be ignored.

---

## What it will and will not do

**It will tell you within ~40 minutes** that Hokage has stopped: a crash, a
hang that kills the thread, a shutdown, a power cut, a laptop closed and put
in a bag.

**It will alarm on a deliberate stop too**, and that is on purpose. Any
mechanism to mute a planned absence from inside Hokage is a mechanism that
can mute a real one — and the deliberate-stop marker has already failed to
survive a scheduled task once (2026-10-09). Mute it at the service when you
plan to be away. A clean shutdown sends a reason, so the alert reads
`stopped: clean shutdown` rather than going silent, and you can tell the two
apart at a glance.

**It will not tell you he is blind.** A process alive on a dead token pings
happily. That is the liveness probe's job and the feed probe's job, and both
still run. The status line carried with each heartbeat shows `feed ok` /
`feed down` so you can see it, but the switch does not alarm on it — one
alarm, one meaning.

**It will not restart him.** Nothing here revives a crash-looping process,
for the same reason the liveness probe does not: one outage must not become a
hundred. It reports; you decide.

## Checking coverage afterwards

```bash
python tools/ops/session_coverage.py --weeks 8
```

Sessions come from the candle archive, so no holiday calendar can go stale.
Today it reads 23 of 48. That number is the point of all of this: a hundred
paper round trips is a count of **sessions** as much as of setups.
