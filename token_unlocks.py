"""
Token unlocks: real effect or calendar? (data for notes/02_token_unlocks_calendar.md)

An earlier study found a CAR of -3.6% in the 7 days before the monthly unlocks of ARB/APT/STRK, but the same
decline appeared in tokens WITHOUT unlocks in the same week of the month: all three tokens unlock between the
12th and the 16th, so the unlock effect and a calendar effect were confounded. This design separates them: 10
tokens with monthly unlocks on DIFFERENT days of the month, compared with each other on the same calendar dates.

Calendar (day of the month confirmed by at least 2 sources on 2026-10-13; sources in the note):
  EIGEN 1   ZETA 1   ENA 5   JTO 7   APT 12   STRK 15   ARB 16   ZK 17   ZRO 20   ALT 25
Excluded: SUI, OP, SEI, MANTA (conflicting sources, or only one). Unlock AMOUNTS are not used: free sources
disagree and Tokenomist's history is paywalled.

HYPOTHESES STATED BEFORE LOOKING AT THE DATA (2026-10-13), Bonferroni threshold 0.05/3:
  H1  CAR*[-7,-1] < 0   CAR* = CAR of the unlocking token - mean CAR of the other panel tokens that do NOT
                        unlock within +-10 days, over the SAME dates: removes the calendar effect by construction
  H2  CAR*[0,+7]  < 0   same measure after the unlock
  H3  out-of-sample calendar effect: in the control tokens, the week of the 8th-14th underperforms the other
      weeks, over 2020-08 -> 2023-12 (before any data used in the earlier study)
Exploratory analyses (not tests): single tokens, groups of days (start/middle/end of month), large cliffs.

Method:
  - prices: daily closes of Binance perpetuals (ZETA has no spot market), log returns;
  - abnormal return AR = r - beta x market (mean of BTC and ETH), beta estimated away from unlocks;
    the first 30 days after listing are dropped;
  - p-values for H1/H2 from a CALENDAR-PRESERVING PLACEBO: each token gets a fake day of the month (at least 5
    days from the real one, same months) and the same statistic is recomputed 1,000 times;
  - confidence interval from a block bootstrap by month (events in the same month are not independent);
  - H3: for each month D = CAR(8-14) - mean CAR of the other weeks, averaged over the control tokens; one-sided
    t-test across months.

Run: python token_unlocks.py
"""

import datetime as dt
import json
import math
import os
import random
import statistics

import requests

from chain import DATA

UNLOCKS = {  # token: (day of month, first monthly unlock, last monthly unlock or None)
    "EIGEN": (1, dt.date(2025, 10, 1), None),
    "ZETA": (1, dt.date(2025, 2, 1), None),
    "ENA": (5, dt.date(2025, 4, 5), dt.date(2026, 9, 5)),
    "JTO": (7, dt.date(2025, 1, 7), dt.date(2026, 11, 7)),     # last scheduled unlock on 2026-11-07
    "APT": (12, dt.date(2024, 1, 12), None),
    "STRK": (15, dt.date(2024, 4, 15), None),
    "ARB": (16, dt.date(2024, 4, 16), None),
    "ZK": (17, dt.date(2025, 7, 17), None),
    "ZRO": (20, dt.date(2025, 7, 20), None),
    "ALT": (25, dt.date(2025, 1, 25), None),
}
# large one-off unlocks (cliff ends): descriptive only, too few for a test
CLIFFS = [("ARB", dt.date(2024, 3, 16)), ("ALT", dt.date(2024, 7, 25)), ("JTO", dt.date(2024, 12, 7)),
          ("ENA", dt.date(2025, 3, 5)), ("ZK", dt.date(2025, 6, 17)), ("ZRO", dt.date(2025, 6, 20)),
          ("ENA", dt.date(2026, 10, 5))]   # ENA 2026: last investor unlock, merged (Tokenomist)
# Controls: tokens without scheduled monthly unlocks
CONTROLS = ["SOL", "TRX", "XLM", "DOT", "ATOM", "NEAR", "FIL", "DOGE", "LTC", "BCH", "ETC", "ADA", "BNB"]
WINDOWS = {"H1 [-7,-1]": (-7, -1), "H2 [0,+7]": (0, 7)}
N_PLACEBO, N_BOOT, SEED, ALPHA, N_TESTS = 1000, 2000, 33, 0.05, 3
LAST = dt.date(2026, 10, 5)          # last IN-SAMPLE event: needs the day +7 close (data to 2026-10-12)
EST_END = dt.date(2026, 10, 12)      # betas use only data available at registration
REGISTERED = dt.date(2026, 10, 13)   # prospective test: unlocks AFTER this date had not been seen
H3_START, H3_END = dt.date(2020, 8, 1), dt.date(2023, 12, 31)
CACHE = os.path.join(DATA, "cache_bn_perp_daily.json")
FUND_CACHE = os.path.join(DATA, "cache_bn_funding_panel.json")
FEE = 0.0005                         # Binance futures taker fee, per side


# ------------------------------------------------------------------ data
def _stale(series):
    yesterday = (dt.datetime.now(dt.UTC) - dt.timedelta(days=1)).date().isoformat()
    return not series or max(series) < yesterday


def perp_daily(symbol, cache):
    if symbol in cache and not _stale(cache[symbol]):          # up-to-date cache: no download
        return {dt.date.fromisoformat(k): v for k, v in cache[symbol].items()}
    out, t = {}, int(dt.datetime(2020, 1, 1, tzinfo=dt.UTC).timestamp() * 1000)
    while True:
        rows = requests.get("https://fapi.binance.com/fapi/v1/klines",
                            params={"symbol": symbol, "interval": "1d", "startTime": t, "limit": 1500}, timeout=30).json()
        if not rows:
            break
        for k in rows:
            out[dt.datetime.fromtimestamp(k[0] / 1000, dt.UTC).date()] = float(k[4])
        t = rows[-1][0] + 86_400_000
        if len(rows) < 1500:
            break
    out.pop(dt.datetime.now(dt.UTC).date(), None)            # today's candle is not closed
    cache[symbol] = {d.isoformat(): v for d, v in out.items()}
    return out


def funding_daily(symbol, cache):
    """Daily funding (sum of periods) of the Binance perpetual since 2024: positive = the short receives."""
    if symbol not in cache or _stale(cache[symbol]):
        out, t = {}, int(dt.datetime(2024, 1, 1, tzinfo=dt.UTC).timestamp() * 1000)
        while True:
            rows = requests.get("https://fapi.binance.com/fapi/v1/fundingRate",
                                params={"symbol": symbol, "startTime": t, "limit": 1000}, timeout=30).json()
            if not rows:
                break
            for r in rows:
                d = dt.datetime.fromtimestamp(r["fundingTime"] / 1000, dt.UTC).date().isoformat()
                out[d] = out.get(d, 0.0) + float(r["fundingRate"])
            t = rows[-1]["fundingTime"] + 1
            if len(rows) < 1000:
                break
        cache[symbol] = out
    return {dt.date.fromisoformat(k): v for k, v in cache[symbol].items()}


def log_returns(px, skip=30):
    days = sorted(px)[skip:]                                  # first 30 days after listing dropped
    return {d: math.log(px[d] / px[p]) for p, d in zip(days, days[1:]) if (d - p).days == 1}


def month_dates(day, first, last):
    out, d = [], first
    while d <= last:
        out.append(d)
        y, m = d.year + (d.month == 12), d.month % 12 + 1
        d = dt.date(y, m, min(day, 28))
    return out


def abnormal(r, mkt, exclude=()):
    est = [d for d in r if d in mkt and d not in exclude and d <= EST_END]
    mx, my = statistics.mean(mkt[d] for d in est), statistics.mean(r[d] for d in est)
    beta = sum((mkt[d] - mx) * (r[d] - my) for d in est) / sum((mkt[d] - mx) ** 2 for d in est)
    return {d: r[d] - beta * mkt[d] for d in r if d in mkt}, beta


def car(ar, e, lo, hi):
    vals = [ar.get(e + dt.timedelta(days=k)) for k in range(lo, hi + 1)]
    return None if any(v is None for v in vals) else sum(vals)


# ------------------------------------------------------------------ H1/H2 statistics
def adjusted_cars(ar, events, real_events, lo, hi, extra=None):
    """CAR* per event: CAR of the token - mean CAR, over the same dates, of the tokens that do not unlock within
    +-10 days (according to the REAL calendar, even when 'events' is a fake calendar)."""
    out = []
    for tok, evs in events.items():
        for e in evs:
            c = car(ar[tok], e, lo, hi)
            if c is None:
                continue
            bench = [cb for j in ar if j != tok
                     and not any(abs((x - e).days) <= 10 for x in real_events[j])
                     and (cb := car(ar[j], e, lo, hi)) is not None]
            bench += [cb for a in (extra or {}).values() if (cb := car(a, e, lo, hi)) is not None]
            if len(bench) >= 3:
                out.append((e, tok, c - statistics.mean(bench), c))
    return out


def fake_calendar(rng):
    ev = {}
    for tok, (day, first, last) in UNLOCKS.items():
        choices = [d for d in range(1, 29) if min(abs(d - day), 28 - abs(d - day)) >= 5]
        fd = rng.choice(choices)
        start = first.replace(day=fd)
        ev[tok] = [e for e in month_dates(fd, start, last or LAST) if e <= LAST]
    return ev


def cluster_boot(rows, rng):
    by_month = {}
    for e, _, x, _ in rows:
        by_month.setdefault((e.year, e.month), []).append(x)
    keys = list(by_month)
    means = []
    for _ in range(N_BOOT):
        s = [x for k in (rng.choice(keys) for _ in keys) for x in by_month[k]]
        means.append(statistics.mean(s))
    means.sort()
    return means[int(0.025 * N_BOOT)], means[int(0.975 * N_BOOT)]


def t_onesided_p(xs):
    n, m, s = len(xs), statistics.mean(xs), statistics.stdev(xs)
    t = m / (s / math.sqrt(n))
    return t, 0.5 * math.erfc(-t / math.sqrt(2))             # P(T <= t), normal approximation (n ~ 40)


def trade_pnl(rows, ret, fund, all_real, lo, hi):
    """Short the token, equal-weighted long in the other panel tokens that are not unlocking; actual returns,
    4 taker fees, actual funding (the short receives positive funding, the long pays it)."""
    pnl = []
    for e, tok, _, _ in rows:
        span = [e + dt.timedelta(days=k) for k in range(lo, hi + 1)]
        rt = sum(ret[tok][d] for d in span)
        bench = [j for j in UNLOCKS if j != tok and not any(abs((x - e).days) <= 10 for x in all_real[j])
                 and all(d in ret[j] for d in span)]
        rb = statistics.mean(sum(ret[j][d] for d in span) for j in bench)
        f_short = sum(fund[tok].get(d, 0.0) for d in span)
        f_long = statistics.mean(sum(fund[j].get(d, 0.0) for d in span) for j in bench)
        gross = -(math.exp(rt) - 1) + (math.exp(rb) - 1)
        pnl.append((e, gross, gross - 4 * FEE + f_short - f_long))
    return pnl


# ------------------------------------------------------------------ main
def main():
    os.makedirs(DATA, exist_ok=True)
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    px = {s: perp_daily(s + "USDT", cache) for s in ["BTC", "ETH", *UNLOCKS, *CONTROLS]}
    json.dump(cache, open(CACHE, "w"))
    ret = {s: log_returns(p) for s, p in px.items()}
    mkt = {d: (ret["BTC"][d] + ret["ETH"][d]) / 2 for d in ret["BTC"] if d in ret["ETH"]}

    today = dt.datetime.now(dt.UTC).date()
    full = {tok: month_dates(day, first, last or max(LAST, today)) for tok, (day, first, last) in UNLOCKS.items()}
    real = {tok: [e for e in evs if e <= LAST] for tok, evs in full.items()}
    fwd = {tok: [e for e in evs if REGISTERED < e <= today - dt.timedelta(days=8)] for tok, evs in full.items()}
    cliff_days = {}
    for t, d in CLIFFS:
        cliff_days.setdefault(t, []).append(d)
    all_real = {t: full[t] + cliff_days.get(t, []) for t in UNLOCKS}
    ar, betas = {}, {}
    for tok in UNLOCKS:
        near = {e + dt.timedelta(days=k) for e in all_real[tok] for k in range(-10, 11)}
        ar[tok], betas[tok] = abnormal(ret[tok], mkt, near)
    print("1. Panel: 10 tokens with monthly unlocks on different days of the month")
    for tok, (day, *_) in UNLOCKS.items():
        print(f"   {tok:5} day {day:2} | {len(real[tok]):2} unlocks {real[tok][0]} -> {real[tok][-1]} | beta {betas[tok]:.2f}")

    print("\n2. Main tests H1 and H2: CAR* = unlocking token - other panel tokens on the same dates")
    rng = random.Random(SEED)
    for wname, (lo, hi) in WINDOWS.items():
        rows = adjusted_cars(ar, real, all_real, lo, hi)
        stat = statistics.mean(x for *_, x, _ in rows)
        raw = statistics.mean(c for *_, c in rows)
        placebo = [statistics.mean(x for *_, x, _ in adjusted_cars(ar, fake_calendar(rng), all_real, lo, hi))
                   for _ in range(N_PLACEBO)]
        p = (sum(m <= stat for m in placebo) + 1) / (N_PLACEBO + 1)
        lo95, hi95 = cluster_boot(rows, rng)
        print(f"   {wname}: n={len(rows)} | raw CAR {100 * raw:+.2f}% | CAR* {100 * stat:+.2f}%"
              f" [95% CI {100 * lo95:+.2f}; {100 * hi95:+.2f}] | negative {100 * sum(x < 0 for *_, x, _ in rows) / len(rows):.0f}%"
              f" | placebo p {p:.3f}{'  *' if p < ALPHA / N_TESTS else ''}")
        if wname.startswith("H1"):
            h1_rows = rows
        else:
            h2_rows = rows

    print("\n3. H3: out-of-sample calendar effect (controls, 2020-08 -> 2023-12, before the earlier study's data)")

    def calendar_gap(first, last):
        """For each month: mean over the controls of CAR(days 8-14) - mean CAR of weeks 1-7, 15-21, 22-28."""
        per_month = {}
        for c in CONTROLS:
            a, _ = abnormal(ret[c], mkt)
            d = first
            while d <= last:
                weeks = {}
                for st in (1, 8, 15, 22):
                    vals = [a.get(dt.date(d.year, d.month, st + k)) for k in range(7)]
                    if all(v is not None for v in vals):
                        weeks[st] = sum(vals)
                if len(weeks) == 4:
                    per_month.setdefault((d.year, d.month), []).append(
                        weeks[8] - statistics.mean(weeks[x] for x in (1, 15, 22)))
                d = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        return [statistics.mean(v) for v in per_month.values() if len(v) >= 5]

    D = calendar_gap(H3_START, H3_END)
    t, p3 = t_onesided_p(D)
    print(f"   {len(D)} months, {len(CONTROLS)} tokens: week 8-14 minus the others {100 * statistics.mean(D):+.2f}%"
          f" | negative in {100 * sum(x < 0 for x in D) / len(D):.0f}% of months | t {t:.2f} | p {p3:.3f}"
          f"{'  *' if p3 < ALPHA / N_TESTS else ''}")
    D2 = calendar_gap(dt.date(2024, 1, 1), dt.date(2026, 9, 1))      # period in which the effect was noticed
    t2, p2 = t_onesided_p(D2)
    print(f"   for comparison, 2024-01 -> 2026-09 (in sample): {100 * statistics.mean(D2):+.2f}% over {len(D2)} months,"
          f" t {t2:.2f}, p {p2:.3f}")
    print(f"   * = significant after Bonferroni (p < {ALPHA / N_TESTS:.4f}, 3 tests)")

    print("\n4. Exploratory: by token and by part of the month (H1, CAR*)")
    for tok in UNLOCKS:
        xs = [x for _, t_, x, _ in h1_rows if t_ == tok]
        if xs:
            print(f"   {tok:5} n={len(xs):2} CAR* {100 * statistics.mean(xs):+6.2f}% | negative {100 * sum(x < 0 for x in xs) / len(xs):3.0f}%")
    for lab, days in (("start (1-7)", range(1, 8)), ("middle (12-17)", range(12, 18)), ("end (20-25)", range(20, 26))):
        xs = [x for _, t_, x, _ in h1_rows if UNLOCKS[t_][0] in days]
        print(f"   {lab:15} n={len(xs):3} CAR* {100 * statistics.mean(xs):+6.2f}%")

    print("\n5. Descriptive: large one-off unlocks (cliff ends); one event per row, not a test")
    for tok, d in CLIFFS:
        cells = []
        for lo, hi in ((-30, -1), (-7, -1), (0, 7), (0, 30)):
            c = car(ar[tok], d, lo, hi)
            cells.append(f"[{lo},{hi:+}] {'   n/a' if c is None else f'{100 * c:+6.1f}%'}")
        print(f"   {tok:5} {d} | " + " | ".join(cells))

    # ------------------------------------------------------------------ robustness (chosen AFTER seeing the results)
    print("\n6. Robustness of H2 (checks chosen after seeing the results: they aid understanding, they are not new tests)")
    lo, hi = WINDOWS["H2 [0,+7]"]
    ctrl_ar = {c: abnormal(ret[c], mkt)[0] for c in CONTROLS}
    rows = adjusted_cars(ar, real, all_real, lo, hi, extra=ctrl_ar)
    stat = statistics.mean(x for *_, x, _ in rows)
    rng = random.Random(SEED + 1)
    pl = [statistics.mean(x for *_, x, _ in adjusted_cars(ar, fake_calendar(rng), all_real, lo, hi, extra=ctrl_ar))
          for _ in range(300)]
    print(f"   a) panel + 13 controls as comparison: n={len(rows)} | CAR* {100 * stat:+.2f}%"
          f" | placebo p {(sum(m <= stat for m in pl) + 1) / 301:.3f} (300 draws)")
    loo = []
    for tok in UNLOCKS:
        xs = [x for _, t_, x, _ in h2_rows if t_ != tok]
        loo.append((statistics.mean(xs), tok))
    print(f"   b) leaving out one token at a time: CAR* from {100 * min(loo)[0]:+.2f}% (without {min(loo)[1]})"
          f" to {100 * max(loo)[0]:+.2f}% (without {max(loo)[1]})")
    for wl, (a_, b_) in (("[0,+3]", (0, 3)), ("[0,+14]", (0, 14)), ("[+8,+14]", (8, 14)), ("[+15,+21]", (15, 21))):
        rr = adjusted_cars(ar, real, all_real, a_, b_)
        print(f"   c) window {wl:9}: n={len(rr)} CAR* {100 * statistics.mean(x for *_, x, _ in rr):+.2f}%")
    by_year = {}
    for e, _, x, _ in h2_rows:
        by_year.setdefault(e.year, []).append(x)
    print("   d) by year: " + " | ".join(f"{y}: {100 * statistics.mean(v):+.2f}% (n={len(v)})" for y, v in sorted(by_year.items())))
    print("   e) by token: " + ", ".join(f"{t} {100 * statistics.mean(xs):+.1f}%" for t in UNLOCKS
                                       if (xs := [x for _, t_, x, _ in h2_rows if t_ == t])))

    print("\n7. H2 tradability (estimate): short the token from close -1 to close +7, equal-weighted long in the other")
    print("   panel tokens that are not unlocking; actual returns (not beta-adjusted), actual fees and funding")
    fcache = json.load(open(FUND_CACHE)) if os.path.exists(FUND_CACHE) else {}
    fund = {t: funding_daily(t + "USDT", fcache) for t in UNLOCKS}
    json.dump(fcache, open(FUND_CACHE, "w"))
    pnl = trade_pnl(h2_rows, ret, fund, all_real, lo, hi)
    net = [x for *_, x in pnl]
    sd = statistics.stdev(net)
    print(f"   {len(net)} trades: mean gross {100 * statistics.mean(g for _, g, _ in pnl):+.2f}% | mean net"
          f" {100 * statistics.mean(net):+.2f}% | median {100 * statistics.median(net):+.2f}% | positive"
          f" {100 * sum(x > 0 for x in net) / len(net):.0f}% | std dev {100 * sd:.1f}%")
    print(f"   worst {100 * min(net):+.1f}%, best {100 * max(net):+.1f}%; mean/std dev per trade {statistics.mean(net) / sd:.2f}")
    for y in sorted({e.year for e, *_ in pnl}):
        v = [x for e, _, x in pnl if e.year == y]
        print(f"   {y}: n={len(v):3} mean net {100 * statistics.mean(v):+.2f}%, sum {100 * sum(v):+.1f}%")

    print(f"\n8. PROSPECTIVE TEST of H2 (rule registered on {REGISTERED}, later unlocks never seen)")
    print("   Rule: CAR*[0,+7] < 0 and the short/long trade of section 7. Check the calendar first: unlock")
    print("   schedules can change (e.g. ENA merged its remaining unlocks into October 2026).")
    rows = adjusted_cars(ar, fwd, all_real, lo, hi)
    if not rows:
        print("   no unlock with 7 days of data after registration yet: rerun in a few weeks.")
        nxt = {t: [e for e in month_dates(d, f, l or today + dt.timedelta(days=60)) if e > REGISTERED]
               for t, (d, f, l) in UNLOCKS.items()}
        print("   Next: " + ", ".join(f"{t} {v[0]}" for t, v in sorted(nxt.items(), key=lambda kv: kv[1][:1]) if v))
    else:
        xs = [x for *_, x, _ in rows]
        fwd_pnl = [x for *_, x in trade_pnl(rows, ret, fund, all_real, lo, hi)]
        print(f"   {len(xs)} unlocks: mean CAR* {100 * statistics.mean(xs):+.2f}% | negative {100 * sum(x < 0 for x in xs) / len(xs):.0f}%"
              f" | mean net trade {100 * statistics.mean(fwd_pnl):+.2f}%")
        if len(xs) >= 30:
            t, p = t_onesided_p(xs)
            print(f"   one-sided t-test: t {t:.2f}, p {p:.3f}")
        else:
            print("   fewer than 30 events: too few for a verdict (about 3 months of unlocks are needed)")


if __name__ == "__main__":
    main()
