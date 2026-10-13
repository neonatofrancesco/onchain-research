# On-chain research notes

Independent, reproducible research on DeFi market structure and token events, built from public on-chain
data and free APIs. Each note states its hypotheses before looking at the data, tests them against placebo
and control groups, and lists its own limitations.

## Notes

### 1. [Liquidation latency on Ethereum lending protocols](notes/01_liquidation_latency.md)

Twelve months (Oct 2025 – Sep 2026) of liquidations on Aave v3 (Core and Lido), SparkLend, Morpho Blue and
Compound v3. For each liquidation, the script walks back on archive nodes to find the first block in which
the position became liquidatable.

- 75–94% of liquidations of $1,000 or more on liquid collateral execute within one block.
- Delays are a **cascade effect**:
  - under low load, 3.5% of liquidations are late;
  - under high load, 45% are late, and 71% for positions below $5,000.
  - In 94% of cases the trigger is a price update visible to everyone.
- The value left to late liquidators is about $1M a year across the market, 95% of it on 5 days. 48
  contracts active on several protocols execute 65% of all relevant liquidations.
- On Morpho Blue, long delays and $3.8M of bad debt are concentrated in exotic collateral.

### 2. [Token unlocks: real effect or calendar?](notes/02_token_unlocks_calendar.md)

An event study of 10 tokens whose monthly unlocks fall on different days of the month, so that unlock and
calendar effects can be separated.

- Before the unlock there is no specific effect: about three quarters of the apparent decline is shared by
  tokens that are not unlocking.
- After the unlock: −1.9% over 8 days relative to the other tokens on the same dates, p = 0.008, but
  fragile:
  - absent in 2024;
  - uneven across tokens;
  - reverses in the third week.
- A mid-month calendar effect observed in 2024–2026 does **not** replicate in 2020–2023.
- The rule was registered on 13 Oct 2026 for a **prospective test** on future unlocks.

## Reproduce

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # add a free Blockscout API key (only needed by liquidation_latency.py)
python token_unlocks.py           # < 1 minute, public Binance API only
python liquidation_latency.py     # ~1 hour on first run (free archive RPCs), then cached in data/
```

| File | What it does |
|---|---|
| `liquidation_latency.py` | data and statistics for note 1: events from Blockscout, state checks on archive nodes, oracle-priced economics, cascade load, causes of delay, bad debt, liquidator overlap |
| `token_unlocks.py` | data and statistics for note 2: calendar-matched abnormal returns, calendar-preserving placebo, block bootstrap, out-of-sample calendar test, robustness, tradability estimate, prospective test |
| `chain.py` | shared helpers: public RPCs with fallback, Blockscout API with explicit status checks |

## Method principles

- **Hypotheses before data**: the main tests and their multiple-testing correction are fixed in the code
  before the results are seen. Checks added afterwards are labelled as such.
- **Controls that remove the obvious explanation**: a placebo that preserves the calendar, control groups
  with different dates, and out-of-sample periods.
- **Prospective tests** when a result is new: the rule is registered and evaluated on data that did not
  exist yet.
- **Data hygiene**: rate-limited APIs that return empty results are treated as errors rather than as "no
  data"; tokens are identified by canonical address, not by symbol; gas is split across multi-liquidation
  transactions.

## Disclaimer

This is research, not investment advice. Figures depend on free public data sources that can change or
contain errors; the notes list known limitations.

## License

MIT, see [LICENSE](LICENSE).
