# Cheatsheet

Everything runs from the project folder:

```bash
cd "/Users/fredp/Espero Trading QuantBot/espero"
```

## The one command you actually need

```bash
.venv/bin/espero          # the home screen: status on top, arrow-key menu below
```

Every menu item is one of the commands in the drawers below; the two most useful without the menu:

```bash
cat health.json          # did this morning's run work? last_success, per-step ok/error/equity
open dashboard.html      # what the accounts hold, their equity curves, and what the trades cost
```

The bot itself needs nothing from you. launchd runs it every day at 07:30.

## Pause / resume / is it alive

```bash
touch KILL                                                       # pause everything (marks too)
rm KILL                                                          # resume
launchctl print gui/$(id -u)/com.espero.daily | grep 'last exit'  # 0 = last run was fine
tail -30 ~/Library/Logs/espero/daily.log                         # what happened, in order
```

## Drawer 1: the paper accounts (hand-driving)

Always use a throwaway `--state` file for experiments. The real ones are `tsmom.db` and `xs.db`
in this folder, and every row written to them is part of the track record.

```bash
.venv/bin/python -m espero tsmom --state /tmp/t.db --cash 1000 --force   # monthly cross-asset trend, rebalance now
.venv/bin/python -m espero xs    --state /tmp/x.db --cash 1000 --force   # weekly top-10 crypto, rebalance now
.venv/bin/python -m espero tsmom --deposit 500                           # add paper capital to the REAL account
.venv/bin/python -m espero tsmom --report                                # history of the real account
.venv/bin/python -m espero dashboard --open                              # rebuild the dashboard now
.venv/bin/python -m espero daily --dry-run                               # preflight: no network, no changes
```

## Drawer 2: research

```bash
.venv/bin/python -m espero matrix                     # the audit table (timing x fees x sizing) on BTC
.venv/bin/python -m espero backtest --fee-bps 60      # one configuration of the bar strategy
.venv/bin/python -m espero factors                    # rank-IC table of the factor zoo, 42 coins
python research/multifactor.py                        # hypothesis #8, exactly as pre-registered
./scripts/check.sh                                    # tests + audit table + CLI smoke test
```

A new idea gets a `research/PREREGISTRATION_<name>.md` committed **before** its script runs, then a
`RESULTS_<name>.md`. No exceptions; that discipline is the product.

## Drawer 3: the fast screen (resting orders, semi-automatic, paper)

```bash
.venv/bin/python -m espero fast --product ETH-USD                 # live Coinbase book, paper fills
.venv/bin/python -m espero fast --product ETH-USD --venue binanceus --record   # charge Binance.US maker, record the book
.venv/bin/python -m espero fast --replay data/book/ETH-USD_2026-10-27T1200.jsonl --speed 20
```

The machine proposes a post-only order with the evidence beside it (signal inputs, measured edge vs
cost, regime, whether the signal is working lately). Nothing is placed until **Enter**. `n` declines,
`r` reprices to the touch, `c` cancels, `j` writes a journal note, `k` kills, `q` quits. Fills and
notes go to `fast.db` with the "why" as it stood at decision time.

## Drawer 4: the single-coin bar strategy (original bot, loses after fees)

```bash
.venv/bin/python -m espero paper --state /tmp/p.db --loop --interval 60              # BTC-USD, $500, hourly
.venv/bin/python -m espero paper --product ETH-USD --state /tmp/p-eth.db --loop      # another coin, own state
.venv/bin/python -m espero paper --venue perp --granularity 300 --state /tmp/p-perp.db --loop  # perp fees + 8h funding
.venv/bin/python -m espero paper-compare /tmp/paper-5m-fees.db --granularity 300     # same bars, every venue's bill
```

Kept because its journal loop is the template for the live path. Not scheduled, not a basket.

## Drawer 6: degen altcoins, 打板 (hypothesis #10, paper)

```bash
.venv/bin/python -m espero degen scan                                   # who is breaking out on volume right now
.venv/bin/python -m espero degen backtest --days 30                     # replay through every venue's fees, print the verdict
.venv/bin/python -m espero degen paper --venue binanceus --state degen.db --loop   # the live 5m paper loop
```

Top 60 Coinbase altcoins by 24h volume, new 4h high on a 2-sigma volume spike, stop 2 ATR, trail
2.5 ATR, target 3 ATR, time stop 3h, three slots. Rules and pass criteria are frozen in
`research/PREREGISTRATION_DEGEN.md`; the loop refuses to start twice on one journal. The 30-day
backtest **failed** before fees (`research/RESULTS_DEGEN.md`): use the scan as a view, not the loop as a plan.

## Drawer 7: funding carry on Hyperliquid (hypothesis #11, paper)

```bash
.venv/bin/python -m espero carry scan                                   # what perp shorts are being paid right now, top 20 by OI
.venv/bin/python research/carry.py fetch                                # funding since 2023, perp and spot candles -> research/data/carry
.venv/bin/python research/carry.py run                                  # one replay, the five criteria, the verdict
.venv/bin/python -m espero hl account 0xYourAddress                    # testnet account view, read-only (or HL_WALLET_ADDRESS in .env)
```

Short the perp, hold the same spot, collect the funding longs pay. Enter above 15% annualised on
the trailing week, exit below 5% or after 30 days, five coins at most, 1x, half the capital on each
leg. Rules and criteria are frozen in `research/PREREGISTRATION_CARRY.md`; the result is in
`research/RESULTS_CARRY.md` (**FAIL**: hedge clean, fees took half the funding, regime faded after 2024).
Hyperliquid excludes US persons: paper only, and a pass would mean finding a venue the account can use.
Development runs against the testnet (`HL_NETWORK=testnet` in `.env`, UI and faucet at
app.hyperliquid-testnet.xyz); market data always comes from mainnet. Nothing signs orders.

## Drawer 5: live money. Off.

`espero live` is experimental and needs `.env` keys, `ESPERO_ALLOW_LIVE=1` and `--confirm-live`
before it sends anything. Leave this drawer shut; see the README section before opening it.

## Where things are

| what | where |
|---|---|
| account state, dashboard, health | this folder |
| logs | `~/Library/Logs/espero/daily.log` |
| the launchd job | `~/Library/LaunchAgents/com.espero.daily.plist` |
| remove the job | `./scripts/install-launchd.sh --uninstall` |
| full operating procedure | `docs/RUNBOOK.md` |
