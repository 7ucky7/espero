# Result — 2x funds push small coins into the US close (#34)

**Part A (the placebo): flat, criterion 1 met.** On the coins whose US 2x funds hold only $1–3M
(ADA, XLM and LINK since 2026-04-01, AVAX since 2026-05-15), the last 15 minutes before 16:00 ET
moved with the day's move by **+0.5 bps** (t 0.25, 145 trading days). That is against +8.1 bps on
XRP and +3.3 on SOL in #28. The push does not show where the funds are too small to make one, as
the mechanism says.

**Part B is open.** SOL and XRP forward, 2026-10-30 → 2027-03-31, from #29's rows; judged after the
window. Until then the verdict is pending.

Spec: [PREREGISTRATION_LEVPUSH.md](PREREGISTRATION_LEVPUSH.md) (`022f4e6`); code `4f9c59f`. One run
of part A, output in [levpush_run.txt](levpush_run.txt), rows in [levpush_days.csv.gz](levpush_days.csv.gz).

## Part A, coin by coin (information)

| coin | trading days | closed days | after the close, 16:00 → 16:15 |
|---|---|---|---|
| ADA | −3.7 bps (t −1.5) | −3.5 bps | −4.5 bps (t −1.5) |
| XLM | +7.4 bps (t 2.1) | −4.8 bps | −4.1 bps (t −1.0) |
| LINK | −0.4 bps (t −0.2) | −1.3 bps | −4.6 bps (t −1.8) |
| AVAX | −1.0 bps (t −0.4) | −9.8 bps | −7.2 bps (t −1.8) |
| DOGE (fund size unknown) | +1.1 bps (t 0.6) | −2.8 bps | −4.7 bps (t −2.5) |

- **One of four placebo coins** (XLM) shows a push at t 2.1. Among four coins, one at that level is
  what chance gives, and the four together are flat.
- **The after-close reversal (#29's lead) shows on every one of these coins**, −4 to −7 bps in
  15 minutes. Information only, and it supports #29's reading that the US session's flows wear off
  after 16:00 across the market, not just in BTC and ETH.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 28 | Leveraged-ETF rebalancing pushes BTC/ETH into the close | fail; lead: XRP +8.1 bps, SOL +3.3 bps |
| **34** | **2x funds push small coins into the close (placebo now, SOL/XRP forward)** | **placebo flat (+0.5 bps); forward part running** |
