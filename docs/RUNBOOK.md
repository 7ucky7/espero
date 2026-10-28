# Runbook — running espero unattended on a Mac

The product is two paper accounts that mark themselves every day and rebalance on their own
calendars. This document is how to keep that running, what to look at when it does not, and how to
stop it.

## Install

```bash
uv venv .venv && uv pip install -e ".[chart,tui,dev]" --python .venv/bin/python
./scripts/check.sh                   # tests + audit table + CLI smoke test
./scripts/install-launchd.sh         # daily at 07:30 local time
```

The installer renders `deploy/launchd/com.espero.daily.plist.template` into
`~/Library/LaunchAgents/com.espero.daily.plist`, runs a preflight with the exact interpreter launchd
will use, and loads the agent. Options are environment variables:

| variable | default | meaning |
|---|---|---|
| `HOUR`, `MINUTE` | `7`, `30` | local time of the daily run |
| `STATE_DIR` | repo root | where `tsmom.db`, `xs.db`, `dashboard.html`, `health.json` live |
| `ESPERO_LOG_DIR` | `~/Library/Logs/espero` | rotating `daily.log` plus launchd's stdout/stderr |
| `PYTHON` | `.venv/bin/python` | interpreter |
| `ESPERO_WEBHOOK_URL` | unset | Slack/Discord-style webhook for failures and rebalances |

07:30 local is after the 00:00 UTC crypto close everywhere from Hawaii to Moscow, and after the
previous day's ETF close. launchd runs a missed job when the Mac wakes; it does not run jobs missed
while the machine was powered off, and a day without a mark is just a gap in the equity curve, not
an error.

## What one run does

```
espero daily --state-dir <STATE_DIR>
  tsmom      mark, or rebalance on the first weekday of the month (once)
  xs         mark, or rebalance on Monday; refuses to rebalance if < 30/42 coins are fresh
  dashboard  rewrites dashboard.html
  health     rewrites health.json atomically
```

Each step is isolated. A failure in one is logged, notified, recorded, and the remaining steps still
run. The exit code is 1 if any step failed, 0 otherwise, 3 if another run holds the lock.

## Check it is alive

```bash
launchctl print gui/$(id -u)/com.espero.daily | grep -E 'state|last exit'
cat health.json                      # last_run, last_success, per-step ok/error/equity
tail -50 ~/Library/Logs/espero/daily.log
open dashboard.html
```

`health.json` is the thing to look at first. `last_success` older than two days means the run is
failing or not firing; the `steps` block says which.

## Run one now

```bash
launchctl kickstart gui/$(id -u)/com.espero.daily      # through launchd, as scheduled runs do
.venv/bin/python -m espero daily                       # by hand, same thing, output to the terminal
.venv/bin/python -m espero daily --dry-run             # preflight: no network, no account changes
```

## Pause and resume

```bash
touch KILL          # in STATE_DIR: the next runs do nothing and exit 0 with "paused"
rm KILL             # resume
```

The KILL file pauses marks too. A long pause leaves a gap, nothing else; the accounts resume from
their stored units and cash. (The same file name stops `espero live`.)

## Things that go wrong

**Yahoo fails.** The fetch retries four times with backoff, then falls back to the CSV cache in
`data/cache/` if it is younger than three days. The XS account refuses to rebalance when fewer than
30 of 42 coins have a close less than two days old (`note` reads `mark (degraded N/42)`); held coins
are marked at their last known price. The TSMOM account has six assets and no such guard: a failed
fetch fails the step, and the previous mark stands.

**Two runs at once.** `daily.lock` holds the owner's pid. A live pid aborts the second run (exit 3);
a dead pid's lock is removed and the run proceeds. The SQLite files are in WAL mode with a 5-second
busy timeout, so even a collision would wait rather than corrupt.

**It rebalanced twice.** It should not: TSMOM checks the account for a rebalance row in the current
month; XS rebalances on Mondays and `INSERT OR REPLACE` on `(ts, note)` means a second Monday run
replaces the first row. If you see two `rebalance` rows in one month, that is a bug; open an issue
with the two rows.

**The laptop was asleep.** Nothing happened. The next wake runs the job once.

**The numbers look wrong.** Every decision row stores the signals the bot saw (`signals` column) and
the weights it chose, separately. `espero tsmom --report` prints the history. The dashboard shows the
stored decision, not a recomputation.

## Remove

```bash
./scripts/install-launchd.sh --uninstall
```

The databases and logs are left in place.

## Live trading

Off, and out of scope for the scheduler. `espero live` is an experimental dry-run tool; see the
README section on it. Do not add it to the plist.
