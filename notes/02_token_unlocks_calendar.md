# Token unlocks: real effect or calendar?

**Event study of 10 tokens with monthly unlocks on different days of the month · January 2024 – October 2026**

> Luigi Palmieri. Research note #2. Code: `token_unlocks.py`. Version of 13 October 2026. This is not investment advice.

---

## Summary

1. **An earlier version of this study confused two effects.** ARB, APT and STRK all unlock between the
   12th and the 16th of the month. Their decline before the unlock (−3.6%) also showed up in tokens with
   no unlocks, and I had attributed it to a mid-month calendar effect.
2. **The calendar effect does not replicate out of sample.** In 2020–2023, across 13 control tokens, the
   week from the 8th to the 14th does not underperform the other weeks: +0.14%, p = 0.58. It was almost
   certainly an artefact of the 2024–2026 period.
3. **Separating the two effects with 10 tokens that unlock on different days:**
   - **before** the unlock, the specific effect is not significant: −0.9%, p = 0.097;
   - **after** the unlock, it is: **−1.9% over the first 8 days** relative to the other tokens on the
     same dates, p = 0.008, below the Bonferroni threshold of 0.0167.
4. **The effect looks like temporary selling pressure**: it reverses in the third week (+2.75%). It is
   fragile:
   - it is absent in 2024;
   - it varies widely across tokens: STRK −7.6%, ARB +0.6%, APT +1.0%;
   - it emerged from 3 tests plus a few follow-up checks.
5. **Verdict**: a lead, not an edge. The real test is **prospective**: the rule was registered on
   13 October 2026, and the script evaluates it by itself on the coming months' unlocks, with no capital
   at risk.

## The question and the flaw in the earlier study

"90% of unlocks push the price down" is a widely cited claim, for example in a study by Keyrock. My
earlier study seemed to confirm it: −3.6% in the 7 days before the ARB, APT and STRK unlocks, p = 0.014.
It then took the result apart with a control group: tokens without unlocks also lost value in that week
of the month. The difference-in-differences was −0.58%, p = 0.24.

The design had a flaw, though. With three tokens that all unlock mid-month, **calendar and unlock
coincide**, so there is no way to tell which one matters. Separating them requires tokens that unlock on
different days.

## Data and method

**Calendar.** A token is included only if its day of the month is confirmed by at least 2 sources,
checked on 13 October 2026.

| Token | Day | Monthly unlocks used | Sources |
|---|---|---|---|
| EIGEN | 1 | 10/2025 → | [KuCoin](https://www.kucoin.com/news/flash/39-5-million-eigen-tokens-unlock-on-september-1-2026), [Tokenomist](https://tokenomist.ai/eigenlayer/unlock-events) (Tokenomics.com gives the 11th: disagreement flagged) |
| ZETA | 1 | 02/2025 → | [Tokenomics.com](https://app.tokenomics.com/tokenomics/zetachain/unlocks), [Tokenomist](https://tokenomist.ai/zetachain) |
| ENA | 5 | 04/2025 → 09/2026 | [Ethena docs](https://docs.ethena.fi/ena/tokenomics) (vesting from 5 Mar 2024, 1-year cliff then monthly), [Tokenomist](https://tokenomist.ai/research/ethena-bought-out-its-sellers-and-deleted-the-investor-unlock-calendar-the-buyback-replacing-it-arms-at-7-5b-usde) (final unlock merged into 5 Oct 2026) |
| JTO | 7 | 01/2025 → 11/2026 | [Jito blog](https://jito.network/blog/announcing-jto-the-jito-governance-token) (1-year cliff from 7 Dec 2023), [Tokenomics.com](https://app.tokenomics.com/tokenomics/jito/unlocks) (DefiLlama shows daily linear vesting: disagreement flagged) |
| APT | 12 | 01/2024 → | [BlockEden](https://blockeden.xyz/blog/2026/04/11/aptos-apt-april-12-token-unlock-move-vm-tvl-growth/) |
| STRK | 15 | 04/2024 → | [Decrypt](https://decrypt.co/218626/starknet-ethereum-scaler-revises-token-unlock-schedule) |
| ARB | 16 | 04/2024 → | [Tokenomist](https://www.tokenomist.ai/arbitrum/unlock-events) |
| ZK | 17 | 07/2025 → | [ZK Nation docs](https://docs.zknation.io/zk-token) (monthly after June 2025), [Tokenomist](https://tokenomist.ai/zksync/unlock-events) |
| ZRO | 20 | 07/2025 → | [Tokenomics.com](https://app.tokenomics.com/tokenomics/layerzero/unlocks), [CryptoTicker](https://cryptoticker.io/en/layerzero-zro-unlock-monthly-dilution/) |
| ALT | 25 | 01/2025 → | [official AltLayer announcement](https://t.me/s/altlayer/190) (resumed 25 Jan 2025), [DefiLlama](https://defillama.com/unlocks/altlayer) |

SUI, OP, SEI and MANTA are excluded: the sources contradict each other, or there is only one. Unlock
**amounts** are not used: free sources disagree and Tokenomist's history is paywalled.

**Measure.** The starting point is the abnormal return, AR = return − β × market, where the market is the
average of BTC and ETH. Prices are daily closes of Binance perpetuals, and the first 30 days after
listing are dropped.

The key statistic is **CAR\***: the cumulative abnormal return of the unlocking token **minus the average
for the other panel tokens that do not unlock within ±10 days, over the same dates**. A calendar effect
shared by all tokens cancels out by construction. An event is kept only if it has at least 3 comparison
tokens: 180 of 217 remain.

**Hypotheses stated before looking at the data** (Bonferroni threshold 0.05/3 = 0.0167):
- **H1**: negative CAR\* in the 7 days before the unlock;
- **H2**: negative CAR\* on the unlock day and the 7 days after;
- **H3**: in 2020–2023, across 13 control tokens, the week of the 8th–14th underperforms the other weeks.

**Inference.**
- **Calendar-preserving placebo**: each token gets a fake day of the month, at least 5 days from the real
  one, and everything is recomputed 1,000 times.
- **Confidence interval**: block bootstrap by month.
- **H3**: t-test over the 41 months.

## Results

### 1. Main tests

| Test | n | Unadjusted | CAR\* | 95% CI | Negative | p |
|---|---|---|---|---|---|---|
| H1: before, [−7, −1] | 180 | −4.05% | −0.92% | [−2.27; +0.51] | 56% | 0.097 |
| H2: after, [0, +7] | 180 | −2.43% | **−1.89%** | [−3.55; −0.20] | 61% | **0.008** ✱ |
| H3: calendar 2020–2023 | 41 months | — | +0.14% | — | 46% of months | 0.58 |

The "unadjusted" column shows how much the calendar matters. Before the unlock, the adjustment moves the
figure from −4.05% to −0.92%: almost all of the apparent decline was shared by the other tokens on the
same dates.

### 2. The earlier calendar effect was an artefact of the period

| Period | Week 8–14 minus the other weeks | p |
|---|---|---|
| Jan 2024 → Sep 2026 (where I had noticed it) | −1.80% | 0.024 |
| Aug 2020 → Dec 2023 (out of sample) | **+0.14%** | 0.58 |

A genuine calendar effect should also show up in the earlier period. It does not. The "calendar"
explanation from the earlier study is therefore **withdrawn**. Its practical conclusion still stands:
there is no unlock-specific effect before the unlock.

### 3. Robustness of H2 (checks chosen *after* seeing the results)

| Check | Result |
|---|---|
| Comparison group widened to the 13 control tokens (217 events) | −1.99%, p = 0.033 |
| Leaving out one token at a time | from −1.40% to −2.49%: never positive |
| By year | 2024: **+0.67%** (n = 28); 2025: −2.29%; 2026: −2.43% |
| By token | negative for 7 of 10. STRK −7.6%, ZETA and ZK −5.5%, EIGEN −2.6%, ENA −2.2%; positive for APT +1.0%, JTO +0.8%, ARB +0.6% |
| Path over time | [0,+3] −0.82%; [0,+7] −1.89%; [+8,+14] +0.31%; **[+15,+21] +2.75%** |

The path is that of **temporary selling pressure**: recipients sell in the days after the unlock, then
the price recovers. This is consistent with the literature on supply events in traditional markets, but
here the reversal is an exploratory finding, not a test.

### 4. What it would return (an estimate, not a recommendation)

The strategy estimated is a short in the token from close −1 to close +7, with an equal-weighted long in
the other panel tokens. It includes 4 taker fees (0.05% each) and actual Binance funding.

| | Value |
|---|---|
| Trades | 180 |
| Mean / median net | +1.74% / +1.68% |
| Positive | 57% |
| Standard deviation | **10.8%** per trade (worst −28%, best +48%) |
| By year | 2024: −0.54% on average; 2025: +2.02%; 2026: +2.33% |

The mean-to-standard-deviation ratio is 0.16 per trade: each individual trade carries high risk relative
to its expected gain. After taxes on gains (33% for an Italian resident), and with real slippage on the
less liquid tokens (ALT, ZETA), the margin shrinks further.

### 5. Large one-off unlocks (descriptive)

Six cliff ends: ARB, ALT, JTO, ENA, ZK, ZRO. In the 30 days before, 4 of 6 lose more than 30% relative to
the market, but ENA and JTO do not. With one event per token this is an anecdote, not evidence.

## Implications

- **For traders**: the claim that "unlocks push prices down" holds far more weakly than usually stated.
  - Roughly three quarters of the decline "before the unlock" is shared by tokens that do not unlock.
  - What remains, about −1.9% in the week after, is statistically significant in this sample, but noisy,
    uneven across tokens and absent in 2024.
- **For research**: the methodological lesson is that a control group needs **different dates**, not just
  different tokens. Without this, the earlier study produced a wrong explanation (the calendar) for a
  correct result (no effect before the unlock).

## Prospective test

The rule was registered on 13 October 2026. Section 8 of the script computes the results on later unlocks
by itself.

| Next unlocks | Date |
|---|---|
| STRK | 15 Oct |
| ARB | 16 Oct |
| ZK | 17 Oct |
| ZRO | 20 Oct |
| ALT | 25 Oct |
| EIGEN and ZETA | 1 Nov |
| JTO (last) | 7 Nov |
| APT | 12 Nov |

At least 30 events are needed, which takes about 3–4 months. The verdict criteria are set before seeing
the outcome:
- **holds**: a negative mean CAR\* with p < 0.05 on the new events. Then it is worth investigating further
  with unlock amounts and liquidity;
- **does not hold**: otherwise the result in this note should be treated as a false positive.

Before each evaluation the calendar must be re-checked, because schedules change: ENA, for example,
merged its remaining unlocks into October 2026.

## Limitations

- The calendars come from consistent secondary sources, not from on-chain checks of the vesting
  contracts. For EIGEN and JTO there are conflicting sources, flagged in the table.
- Only dates are used, not amounts: it cannot be checked whether larger unlocks weigh more.
- The tokens are chosen because they have known monthly unlocks. The comparison is between tokens of the
  same kind, so their general underperformance cancels out, but a selection bias remains possible.
- 3 stated tests plus follow-up checks and exploratory analyses: the risk of a false positive is not
  zero. That is why the prospective test is needed.
- Daily UTC closes do not capture the exact time of each unlock.

## Reproducibility

```bash
python token_unlocks.py
```

The script uses only public Binance APIs, with prices and funding cached, and runs in under a minute.
When rerun in the coming months it updates the prospective test by itself.
