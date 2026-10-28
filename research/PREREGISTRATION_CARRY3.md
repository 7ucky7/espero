# Pre-registration — #12's carry rule on a second venue, Kraken Futures (#14)

Committed **before** any Kraken funding, price or open-interest number is fetched. Before
writing it, only HTTP status codes were checked, to learn which public APIs answer from this
network (Kraken Futures, OKX, Coinbase, dYdX: 200; Binance: 451; Bybit: 403). No response body
was read.

## Why

[#12](PREREGISTRATION_CARRY2.md) passed its five criteria on Hyperliquid, provisionally: the rule
was post-hoc, designed on the sample it was scored on, and its maker fills were an upper bound.
Its 30-day forward test runs to 2026-11-27 and cannot be shortened. #12's own spec forbids another
carry test on that sample. This one runs **the same rule, unchanged, on a different venue's
funding**, so it is a second sample, not a second try. It also answers the practical question:
Hyperliquid excludes US persons, so a carry edge that exists only there is of no use to this
account.

Venue choice, written before any data: Kraken Futures is the only venue that answers from here,
publishes multi-year funding history and belongs to an exchange this account can already use for
spot. OKX and dYdX answer but exclude US persons; Coinbase's US perpetuals publish no funding
history; Binance and Bybit are blocked. Whether Kraken's perpetuals can be traded from this
account is **not** assumed and would be checked before any money moves.

## Universe — frozen

Kraken Futures linear multi-collateral perpetuals (`PF_` symbols), the **top 20 by open interest
in USD** (`openInterest × markPrice` from the public tickers) at the time of the fetch, BTC and ETH
included, each paired with its Coinbase USD spot product; a perp with no Coinbase spot pair is
dropped. Minimum 90 days of funding per coin, or it is excluded. Survivorship as in #11: today's
top 20 by open interest biases the test *for* positive funding.

## Data — frozen

- Funding: Kraken Futures public `historical-funding-rates` per symbol, its `relativeFundingRate`.
  *(Amended 2026-10-28 before any fetch, see below.)* Kraken's contract specification says the
  rate is "standardised to a per-hour basis" and paid as rate × position × hours elapsed, and the
  API's `timestamp` is the start of the period the rate applies to. So each rate is an **hourly**
  rate, applied unchanged to every hour from its timestamp to the next one (at most 8 hours; a
  longer gap is left missing, which blocks entry like any missing hour). That is the same scale
  as Hyperliquid's hourly series, credited hour by hour as #12 credits Hyperliquid's.
- Perp price: Kraken Futures public hourly trade candles (`charts/v1/trade/{symbol}/1h`), close.
- Spot price: Coinbase hourly closes, as in #11 and #12.

**Primary window, where the criteria are judged:** from the earliest hour that has funding, perp
and spot for a coin, **up to 2026-04-02 00:00 UTC**, the hour #12's primary window began. The two
samples share no hours, so #14 does not reuse any period #12 was designed on. Anything later is
cut off before the replay.

**Reported, not a criterion:** 2026-04-02 → the fetch, the same months as #12 on a different
venue. Funding on two venues in the same months moves together, so this is the weaker check, and
it is kept apart for that reason.

## The rule — #12's, unchanged

Everything in [PREREGISTRATION_CARRY.md](PREREGISTRATION_CARRY.md) and
[PREREGISTRATION_CARRY2.md](PREREGISTRATION_CARRY2.md), with no parameter changed: trailing
168-hour annualised funding, enter above 15%, exit below 5%, 30-day time stop, at most 5 coins,
1×, half the capital on each leg, a 5-point swap gap and a 7-day minimum hold.

Disclosed, not adjusted: Hyperliquid's idle funding is about 10.95% a year, and #11 chose 15% to
mean "above idle". Kraken's funding has no fixed idle component, so on Kraken the same 15% is a
stricter bar. Changing the threshold to compensate would be tuning; it stays at 15%.

## Costs — frozen

Only the perp leg changes, from Hyperliquid's schedule to Kraken Futures' published base tier:

| leg | maker (primary) | taker (reported) |
|---|---|---|
| spot, Binance.US | 0 bps + 0 slippage | 2 bps + 5 bps |
| spot, Kraken (criterion 5) | 25 bps + 0 | 40 bps + 5 bps |
| perp, Kraken Futures base tier | **2 bps + 0** | **5 bps + 5 bps** |

As in #12, maker fills at the hour's close are an upper bound. If Kraken's published base-tier
perp fees differ from 2 / 5 bps on the day of the fetch, the published values are used and the
difference is recorded in the result. Nothing else may change on that basis.

## Pass criteria — #12's five, unchanged

On the primary window, all required: net annualised return on equity > 8%; max drawdown < 5%;
annualised Sharpe of the hourly equity curve > 1.5, with the daily-resampled Sharpe reported
beside it (ERRATA 2026-10-28); funding paid < 25% of funding received; net annualised > 4% with
the spot leg on Kraken maker fees. Reported beside them: the taker-cost run.

**On PASS:** #12 has a second, independent sample, and a forward paper book on Kraken funding
becomes worth building. It stays paper. **On FAIL:** #12's edge is recorded as seen on
Hyperliquid only, and #12's forward test still runs to 2026-11-27 and decides #12.

## Multiple testing

Fifteenth test in the repo, the third on carry, the first on this venue. The venue, the window
cut and the fee values are written down before the fetch; no rule parameter is chosen at all.
One run. Any change after the fetch is a new hypothesis with a new number.

## Amendment, 2026-10-28, before any fetch

The first version of the Data section said each settlement's rate would be *spread* over the
hours since the previous settlement, which treats the rate as a per-settlement amount. Kraken's
perpetual contract specification (support.kraken.com, "Perpetual Futures Contract
Specifications", read 2026-10-28) says the rate is standardised per hour. Spreading it would have
divided funding by the period length and biased the test toward FAIL. Corrected to the venue's
definition above, before any Kraken number was fetched. No rule parameter, window, universe, cost
or criterion changed.
