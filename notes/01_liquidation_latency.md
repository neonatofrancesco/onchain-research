# Liquidation latency on Ethereum lending protocols

**October 2025 – September 2026 · Aave v3 (Core and Lido), SparkLend, Morpho Blue, Compound v3**

> Research note #1. Code: `liquidation_latency.py`. Per-event dataset produced by the script. Version of
> 13 October 2026.

---

## Summary

1. **On positions backed by liquid collateral, the race is almost always over within one block.** Share of
   liquidations of at least $1,000 executed within 1 block (12 s) of the position becoming liquidatable:
   - SparkLend: 94%;
   - Compound v3: 85%;
   - Aave v3 Core: 75%.
2. **A quarter of Aave Core liquidations arrive 2 or more blocks late, but only during cascades.**
   - Few liquidations under way: 3.5% are late.
   - Many liquidations under way: 45% are late.
   - Positions below $5,000 under high load: 71% are late.
   - Positions above $5,000 in calm periods: 1% are late.
3. **The delays do not come from "silent" positions.** In 94% of cases the position becomes liquidatable
   through an oracle price update, which every liquidator can see. Accrued interest does not explain the
   delays.
4. **The value left to late liquidators is small and rare.**
   - About $1.0M over one year across all the protocols studied, or 2.4% of net blue-chip liquidation
     profit. This is an upper bound.
   - 95% of it falls on 5 days: 10 Oct 2025, 31 Jan, 5–6 Feb and 5 Jun 2026.
   - Incumbent liquidators capture even these cases, with a median delay of 3 blocks.
5. **On Morpho Blue, long delays are almost entirely a feature of exotic collateral.**
   - Exotic collateral: 53% of liquidations are late, 99 by more than a day.
   - Blue-chip collateral: 8% are late.
   - Bad debt socialised to depositors: $3.8M on exotic markets, $1,300 on blue-chip markets.

## Question

When a position on a lending protocol becomes liquidatable, how long does it take to be liquidated? The
answer matters to two audiences:
- **prospective liquidators**: systematic delays on liquid collateral would point to weak competition;
- **protocol risk managers**: long delays mean more time for bad debt to accumulate.

## Data and method

- **Events**: every liquidation on Ethereum between 1 Oct 2025 and 1 Oct 2026, blocks
  23,479,244–26,093,737, read through the Blockscout indexer. The events are `LiquidationCall` for Aave
  and Spark, `Liquidate` for Morpho Blue, and `AbsorbDebt` for the 6 Compound v3 markets. 18,919 events
  in total.
- **Size threshold**: repaid debt of at least $1,000 at DefiLlama daily prices. Below this level gas
  often exceeds the bonus, so a delay is not a missed opportunity.
- **Episodes**: only the **first** liquidation of a position counts. If the same position was liquidated
  in the previous 7,200 blocks (one day), the event is a follow-up: Aave liquidates at most 50% at a time,
  and follow-ups would look like delays without being delays.
  - Aave Core: random sample of 1,500 of its 7,989 episodes, with a fixed seed.
  - Other protocols: all episodes.
- **Latency**: blocks between the first block in which the position was liquidatable and the
  liquidation block. State is read backwards from archive nodes, with an exponential then binary search
  of up to one day.
  - Aave and Spark: health factor from `getUserAccountData`.
  - Morpho: debt, including interest accrued but not yet booked (taken from the rate model), compared
    with collateral × oracle price × LLTV.
  - Compound: `isLiquidatable`.
- **Economics**: gross bonus at the protocol oracle's prices in the liquidation block, gas from the
  receipt split across the liquidations in the same transaction. Compound v3 is excluded from this part:
  whoever calls `absorb` receives no bonus.
- **Blue-chip**: an asset counts as blue-chip only if it is on the list approved by Aave, Spark or
  Compound governance **at its canonical address**. The symbol alone is not enough: anyone can deploy a
  token called "USDC".

## Results

### 1. Latency by protocol (episodes of at least $1,000)

| Protocol | Episodes measured | 0 blocks | 1 | 2–5 | 6–50 | > 50 | Within 1 block [95% CI] |
|---|---|---|---|---|---|---|---|
| Aave v3 Core (sample) | 1,500 | 777 | 346 | 290 | 83 | 4 | **74.9%** [72.6–77.0] |
| Aave v3 Lido | 111 | 33 | 41 | 30 | 6 | 1 | 66.7% [57.5–74.7] |
| SparkLend | 205 | 153 | 39 | 11 | 2 | 0 | **93.7%** [89.5–96.3] |
| Morpho Blue | 1,091 | 565 | 155 | 87 | 106 | 178 | 66.0% [63.1–68.7] |
| Compound v3 | 266 | 167 | 59 | 22 | 11 | 7 | 85.0% [80.2–88.8] |

A latency of 0 blocks means the liquidation lands in the same block as the price update (a backrun). A
latency of 1 is still competitive: if the update comes at the end of a block, there is no practical way
to liquidate in that same block.

### 2. Delays are a cascade effect

Load counts the liquidations (all protocols, all sizes) within ±25 blocks (5 minutes) of the first
liquidatable block. The sample is 1,772 blue-chip episodes on Aave Core, Aave Lido and Spark.

| Load | Episodes | Delay ≥ 2 blocks [95% CI] |
|---|---|---|
| low (≤ 37 liquidations) | 607 | **3.5%** [2.3–5.2] |
| medium | 575 | 22.1% [18.9–25.7] |
| high (> 182) | 590 | **44.7%** [40.8–48.8] |

| Debt | Delay ≥ 2, low load | Delay ≥ 2, high load |
|---|---|---|
| < $5,000 | 6.0% (n = 302) | **70.6%** (n = 221) |
| ≥ $5,000 | 1.0% (n = 305) | 29.3% (n = 369) |

The simplest reading is that during a cascade liquidators **serve the large positions first**, and the
small ones wait a few blocks. The delay depends on how much liquidation the system can absorb, not on a
lack of competitors.

This also explains why an earlier 90-day analysis gave a cleaner picture: 28 of 30 liquidations landed
in the same block. That window was calm, and in calm periods delays are rare. **A short window can
mislead.**

### 3. It is not interest accrual

I checked whether the oracle price of the collateral or of the debt changes exactly in the first
liquidatable block.

| Group | Episodes | Become liquidatable through a price update |
|---|---|---|
| latency ≤ 1 (random control) | 300 | 89.0% |
| latency ≥ 2 | 412 | **94.2%** |

The delays therefore follow price updates that every liquidator can see. They do not involve positions
drifting below the threshold without any signal.

### 4. What the delay is worth

| | Estimated net over 12 months (blue-chip, oracle prices, after gas) |
|---|---|
| all liquidations (Aave Core, Lido, Spark, Morpho) | ~$42.6M |
| only those delayed ≥ 2 blocks | **~$1.0M** (2.4%) |
| of which on the 5 main days | 95% |

For Aave Core the sample value was scaled up to the full set of episodes (× 5.3). The median delay in
these cases is 3 blocks, the 90th percentile 11. The million is an **upper bound** on what a new entrant
could capture:
- the entrant would have to beat, during cascades, the bots that close these cases today within
  36 seconds;
- net profit is computed at oracle prices, but in a cascade selling collateral on DEXs costs more
  (slippage), which may be exactly why small positions wait;
- builder tips paid through internal transfers are not included.

### 5. Morpho Blue: exotic collateral and bad debt

| Collateral | Delay ≥ 2 blocks | Liquidations with bad debt | Bad debt |
|---|---|---|---|
| blue-chip | 36 / 455 (7.9%) | 42 | $1,283 |
| exotic | 335 / 636 (52.7%) | 437 | **$3.80M** |

The markets with the most bad debt are REKT→USDS ($1.38M), RLP→USDC ($1.18M, in a single event on 6 Jun
2026), PEPE→USDS ($0.54M), sNUSD→USDC ($0.29M) and Mog→USDS ($0.21M). On exotic collateral the oracle
price often cannot be realised in the market. When nobody liquidates for days, it is usually because
liquidating does not pay, not because nobody is watching. Depositors in the market bear the cost.

### 6. Who liquidates

- **Liquidator contracts**: 210 on Aave Core, 159 on Morpho, 39 on Compound, 26 on Spark, 23 on Aave
  Lido. On the smaller protocols the top 3 contracts execute 51–58% of relevant liquidations, on Aave
  Core 28%.
- **Overlap**: 48 contracts operate on at least 2 protocols and execute **65.5%** of all relevant
  liquidations. The same bots serve every protocol: a "smaller" protocol does not have a separate and
  weaker set of competitors.

## Implications

- **For a prospective liquidator**: there is no gap to fill on liquid collateral, because the same bots
  cover every protocol. The only residual is in cascades:
  - it is worth about $1M a year gross across the whole market;
  - it is concentrated in a few days;
  - it has to be contested with high priority fees and with DEXs short of liquidity.
- **For protocol risk** (the most useful part of this note):
  - during cascades liquidation **capacity** saturates and small positions wait;
  - Spark, with fewer and larger positions, shows fewer delays than Aave Core;
  - the metric a risk manager should watch is the latency of small positions in high-load hours, not
    the average latency;
  - on Morpho, the choice of accepted collateral matters far more than liquidator speed.

## Limitations

- Only positions that were actually liquidated are observed. Positions that recovered on their own, or
  that were liquidated below $1,000, are not in the sample.
- Block time for Morpho interest is estimated at 12 s per slot. With few missed slots, the effect on
  interest is negligible.
- Net profit is computed at oracle prices. Slippage, builder tips paid by transfer and flash-loan costs
  are excluded, so true net profit is lower.
- Tokens with inconsistent decimals are excluded. The case found is wUSDL: it reports 6 decimals while
  its shares have 18, and its 7 events on Morpho came out at $10¹⁴. The safety filter on gross bonus
  above 25% of debt (inconsistent oracle) removed no further events.
- Compound v3: only `absorb` latency. The profit lies in buying back the collateral (`buyCollateral`),
  which is not analysed.
- Ethereum only. For L2s such as Base, event history requires a paid indexer plan. Aave EtherFi (3 events
  in 12 months) is excluded.

## Reproducibility

```bash
python liquidation_latency.py
```

A free Blockscout API key is required in `.env`. The script queries three free archive RPCs in parallel;
the first run takes about an hour, after which the data is cached. The Aave Core sample uses a fixed seed,
so it is reproducible.
