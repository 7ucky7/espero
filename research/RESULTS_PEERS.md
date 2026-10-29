# Result — altcoins led by their peers (#16), ETH-ecosystem coins led by ETH (#17)

**Verdict: both FAIL, on all four criteria.** Neither a coin's own peer group nor ETH leads it in
the way the scan's BTC signal assumes. If anything, ETH's "lead" points the wrong way.

Spec: [PREREGISTRATION_PEERS.md](PREREGISTRATION_PEERS.md) (committed `c25a459`, before any data);
code committed before the fetch (`b30284c`). One run, output in [peers_run.txt](peers_run.txt).

## Data

Coinbase hourly candles, **2024-10-27 → 2025-10-27**, the year before #9b's and one no test here
had seen: 8,755 hours, 39 of the 42 coins (RUNE, THETA and TRX are not on Coinbase). In the final
hour 28 coins were eligible as peers; the ETH group had all 11 coins listed, 6 eligible in the
final hour, and at least 6 eligible in 8,036 hours. 7,313 hours were out of sample.

## Criteria, at the 3-hour horizon, out of sample

| criterion | required | #16 `push_peers` | #17 `push_eth` |
|---|---|---|---|
| rank IC t | > 3 | −0.93 (NW −0.97) **no** | −2.54 (NW −2.61) **no** |
| Fama-MacBeth t with `rev_1` | > 3 | −0.58 (NW −0.59) **no** | −1.30 (NW −1.32) **no** |
| top-minus-bottom spread | > 10 bps | −0.7 bps **no** | −1.5 bps (terciles) **no** |
| hit rate | > 0.52 | 0.503 **no** | 0.486 **no** |

Expected best |t| among the 56 comparisons printed, if all were null: 2.32.

## What the tables say

1. **The peer basket carries no lead.** A coin's beta to its leave-one-out peer basket, times the
   basket's last hour, says nothing about the next hours: its IC is within ±0.007 at 1, 3, 6 and 12
   hours (t from −0.9 to +1.9).
2. **ETH's lead points the wrong way, weakly.** `push_eth` is negative at every horizon: after ETH
   rose, the tokens most tied to it did slightly *worse* than the rest of the group. That is the
   opposite of catching up. Its |t| of 2.54 is about what the best of 56 null comparisons gives
   (2.32), so it is not a finding either way.
3. **The #9 identity holds again.** The unscaled gaps print exactly `rev_1`'s statistics
   (t 10.7334 for the peers, 4.7428 for the ETH group), as the pre-registration said they must.
   The beta-scaled gaps score slightly below plain reversal again (10.05 vs 10.73; 4.66 vs 4.74):
   as with BTC in #9b, the leader term subtracts information.
4. **Reversal replicates on a fresh year.** `rev_1` has t 10.73, hit rate 0.55 and a spread of
   +4 bps per three hours, against #9b's 14.18 and +3.7 bps on 2025–26. The bid-ask-bounce reading
   stands, and so does its price: 4 bps does not pay a 9 bps Hyperliquid taker round trip.
5. **Information only: BTC's leader term is negative too.** On the #16 cross-section, BTC's move
   scaled by each coin's beta (`push_btc`) has t −3.45 (NW −3.54) on Coinbase and −2.06 on
   Hyperliquid: after BTC rises, the high-beta coins do slightly worse over the next three hours.
   It is one comparison of 56, near the luck line, and the opposite of the catch-up the scan's
   signal assumes; testing it would take its own document and data.

**Hyperliquid perps** (the last 208 days, information only; it overlaps #9b's window): the same
picture. `push_peers` t −2.22, `push_eth` +0.77, `rev_1` 7.83.

## What this changes

Nothing ships. As the pre-registration fixed, the scan keeps BTC as its only leader and now says
why on screen (`fast.REFERENCE_NOTE`, pointing here).

Lead-lag has now been tested four ways: BTC unscaled (#9), BTC scaled by beta (#9b), the peer
basket (#16) and ETH for its ecosystem (#17), on two different years and two venues. Every time,
the part of a coin's move that is about its leader shows no catch-up, and what survives is
one-hour reversal, which is the bid-ask bounce. This repo's lead-lag line ends here.

## Transparency

- One run. The Coinbase fetch timed out six times, each retried successfully. The numpy warnings in
  the output are hours where a factor's ranks were all tied; their IC is undefined and dropped, as
  in #8 and #9b.
- #17's spread is top-minus-bottom **tercile**, as pre-registered; the table's column is labelled
  "Q5-Q1" because the evaluator's label is fixed.
- The test panel (`data/panel_peers/`) and the Hyperliquid panel (`data/panel_peers_hl/`) are
  committed. The second because Hyperliquid serves only its last 5,000 hourly bars: it cannot be
  fetched again later.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 12 | Carry with swap gap + maker execution (Hyperliquid) | pass, provisional — forward test to 2026-11-27 |
| 13 | 打板 on 1h bars, one entry per bar, beats BTC | fail — negative before fees |
| 14 | #12's carry rule on Kraken Futures | fail — funding rarely clears the bar |
| 15 | Multi-asset trend (1/3/12 months), vol-sized | fail — cuts drawdown, adds no return beyond vol sizing |
| **16** | **Altcoins led by their peer basket, hourly** | **fail** — no lead at any horizon |
| **17** | **ETH-ecosystem coins led by ETH, hourly** | **fail** — wrong sign, within luck |
