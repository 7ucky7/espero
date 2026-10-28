# Pre-registration — perpetual funding carry, delta-neutral, hourly (#11)

Committed **before** any funding or price series is fetched for this test. Eleven hypotheses in
this repo have asked which way price goes next, and none found an answer at any horizon
([RESULTS_LEADLAG2.md](RESULTS_LEADLAG2.md), [RESULTS_DEGEN.md](RESULTS_DEGEN.md)). This one does
not ask. It asks whether the funding that perpetual longs pay shorts is, net of the costs of
collecting it, income.

## The claim

On a perpetual, when funding is positive the longs pay the shorts every settlement. A position
that is short the perp and long the same amount of spot has no price exposure and collects that
payment. The strategy is **carry**: it earns a yield and bears the risks that funding turns
negative, that the basis between perp and spot moves against it between entry and exit, and
that the venue fails. The question is whether the yield clears the costs and the basis.

This is distinct from hypothesis #1, which used funding *extremes* as a directional signal and
failed. Here funding is the payment, not the forecast.

## Universe — frozen

Hyperliquid perpetuals, the **top 20 by open interest** at the time of the fetch (`metaAndAssetCtxs`),
BTC and ETH included, each paired with its Coinbase USD spot product; a perp with no Coinbase
spot pair is dropped. Survivorship is disclosed: today's top 20 by open interest are coins that
have been popular to be long, which is a bias *for* positive historical funding. The forward test
is the control.

## Data

- Hyperliquid `fundingHistory`, hourly, as far back as the venue has it (BTC from May 2023), the
  fetcher already in `features.hyperliquid_funding`.
- Hyperliquid `candleSnapshot` hourly perp closes; Coinbase hourly spot closes. The basis per
  hour is `perp_close − spot_close` and the hedged position is marked on it.
- Minimum history per coin: 90 days of funding, or the coin is excluded.

## The rule — frozen

Per coin, on hourly data, all causal:

```
f_ann     = mean(funding over the trailing 168 hours) × 8760     trailing-week annualised funding
enter     if f_ann > 15% and no position
exit      if f_ann < 5%, or after 30 days without re-qualifying
```

Hyperliquid's baseline funding is 0.01% per 8 hours, 10.95% annualised, which is what an idle
market pays; 15% requires the market to be paying above idle, and 5% is below it. Both are the
first values written down.

**Position:** on entry, short the perp and buy spot in equal notional. Capital is split in half:
half is the spot leg, half is the perp margin at 1× leverage, so each coin's hedged notional is
`equity / (2 × N)` where N is the number of coins currently qualifying, capped at **5** coins
(the five with the highest `f_ann`). Yield on *equity* is therefore half the funding yield on
notional; that is the honest number and the one the criteria are written on.

No leverage beyond 1× on the perp leg, so the liquidation price of the short is roughly double
the entry; no stop is placed and none is needed at that distance.

## Costs — frozen

| leg | fee | slippage |
|---|---|---|
| spot buy / sell (Binance.US) | 2 bps taker per side | 5 bps per side |
| perp sell / buy (Hyperliquid base tier) | 4.5 bps taker per side | 5 bps per side |

One cycle in and out costs 2 × (2 + 4.5) + 4 × 5 = **33 bps of notional**, which at 15%
annualised takes about eight days of funding to earn back. The basis change between entry and
exit is charged as it falls. Funding is credited hourly at the venue's rate on the perp notional;
there is no assumed rate.

## Evaluation and pass criteria

**Backtest:** the full available history, one run. **Forward:** a paper loop on Hyperliquid
funding and prices for **30 days** from its start (slow strategy, few cycles; 14 days would show
nothing).

All five required, in both:

1. net annualised return on equity **> 8%** — a hedged yield has to beat a Treasury bill by enough
   to pay for the exchange risk, or it is not worth running
2. maximum drawdown of equity **< 5%** — a delta-neutral book that draws down more than that is
   not delta-neutral
3. annualised Sharpe of the hourly equity curve **> 1.5**
4. funding paid (negative hours while in a position) **< 25%** of funding received
5. net annualised return **> 4%** with the spot leg on Kraken fees (40 bps taker) — it must
   survive a worse spot venue than the cheapest one

All five, or FAIL. A result that passes on the backtest and fails forward is a FAIL.

**On FAIL** the result is recorded and the carry scanner (which coins are paying what today)
stays as a read-only command. **On PASS** the strategy stays paper for a further 60 days. Note
the venue: Hyperliquid excludes US persons from trading. Passing is a reason to look for a venue
the account can use, not a reason to use this one.

## Multiple testing

Twelfth test in the repo. No parameter (168, 15%, 5%, 30 days, 5 coins, 1×, the top-20 cut,
90-day minimum) was searched; each is the first value written down. One backtest run, one forward
run, no re-tuning on either. Changing any of them after the fetch is hypothesis #12.
